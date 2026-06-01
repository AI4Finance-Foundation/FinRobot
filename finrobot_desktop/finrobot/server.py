import asyncio
import json
import logging
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from pydantic_ai.ui.vercel_ai import VercelAIAdapter

from finrobot.config import get_settings
from finrobot.obs import bind_session, setup_logging
from finrobot.obs.middleware import RequestTraceMiddleware
from finrobot.data_layer_factory import build_data_layer
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.orchestrator import create_lead_agent
from finrobot.engine.skills.registry import SkillRegistry
from finrobot.artifact.migrate import migrate_filesystem_to_sqlite
from finrobot.artifact.store import ArtifactStore
from finrobot.paths import SETTINGS_JSON, ensure_home
from finrobot.audit.transcript import TranscriptWriter
from finrobot.routes.artifacts import router as artifacts_router
from finrobot.routes.compute import router as compute_router
from finrobot.routes.dashboard import router as dashboard_router
from finrobot.routes.data import router as data_router
from finrobot.routes.health import router as health_router
from finrobot.routes.diagnostics import router as diagnostics_router
from finrobot.routes.notify import router as notify_router
from finrobot.routes.runs import router as runs_router
from finrobot.routes.search import router as search_router
from finrobot.routes.settings import load_non_secret_settings
from finrobot.routes.settings import router as settings_router
from finrobot.routes.sentiment import router as sentiment_router
from finrobot.routes.valuation import router as valuation_router
from finrobot.run_store import RunStore
from finrobot.secret_store import SecretStore, create_secret_store

logger = logging.getLogger(__name__)


async def hydrate_settings_from_secrets(settings: Any, secret_store: SecretStore) -> Any:
    """Return settings with API keys loaded from SecretStore."""
    update: dict[str, str] = {}
    # Keep this list in sync with routes.settings._SECRET_FIELDS — secrets
    # live in the keychain, not in settings.json, and must be hydrated back
    # into FinRobotSettings on every boot so downstream code (data layer,
    # LLM providers, notification channels) sees the same values whether
    # the user originally configured them via .env or via the UI.
    for key in (
        "anthropic_api_key",
        "deepseek_api_key",
        "openai_api_key",
        "fmp_api_key",
        "finnhub_api_key",
        "alpha_vantage_api_key",
        "adanos_api_key",
        "telegram_bot_token",
    ):
        value = await secret_store.get(key)
        if value:
            update[key] = value
    return settings.model_copy(update=update)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Ensure ~/.finrobot/ exists before any storage class tries to open a
    # file under it. Cheap + idempotent.
    ensure_home()

    settings_path = SETTINGS_JSON
    settings = get_settings(**load_non_secret_settings(settings_path))
    secret_store, secret_storage_mode = create_secret_store()
    settings = await hydrate_settings_from_secrets(settings, secret_store)

    # Configure runtime logging as soon as settings are known so every
    # subsequent startup step (validation, warmup, migration) is captured.
    setup_logging(settings)
    logger.info("FinRobot server starting (log_to_file=%s)", settings.log_to_file)

    # Fail-fast config validation — but DO NOT crash the server. The desktop
    # app needs HTTP to be up so the UI can render the SettingsView and the
    # user can paste a missing API key. Instead we stash the error on
    # app.state.startup_error; LLM-touching routes read this flag and reply
    # 503 with the same error message, and the UI shows a top banner.
    #
    # Without this gate, the user's first symptom was a 60-second hang on
    # the first analysis attempt, followed by an OpenAIError missing-key
    # exception buried in Python stderr — invisible inside the Tauri shell.
    startup_error: str | None = None
    try:
        settings.validate_runtime_config()
    except ValueError as exc:
        startup_error = str(exc)
        logger.error("Runtime config validation failed: %s", startup_error)
    app.state.startup_error = startup_error

    # Load skills if available
    skills_path = Path(settings.skills_dir)
    registry = SkillRegistry(skills_path) if skills_path.exists() else None

    data_layer = build_data_layer(settings)

    # Artifact store: SQLite-backed (since 2026-05-23). The ``ArtifactStore``
    # name is a shim that delegates to ``SqliteArtifactStore`` — the old
    # ~/.finrobot-desktop/artifacts/<ticker>/<id>.json filesystem layout is
    # gone; data lives in ~/.finrobot/artifacts.db with secondary indexes on
    # (ticker, created_at), verdict, archived. Eliminates the N+1 reads
    # that dominated landing cold-start.
    artifact_store = ArtifactStore()

    # Sub-agents are shared between the LLM-side (lead agent's @agent.tool
    # closures) and the REST-side (runs.py reaches into app.state.sub_agents).
    # Build once and inject both ways — without this they were constructed
    # twice, creating duplicate model connections every boot.
    from finrobot.engine.agents.factory import create_sub_agents

    sub_agents = create_sub_agents(settings, skill_registry=registry)
    agent = create_lead_agent(settings, skill_registry=registry, sub_agents=sub_agents)
    deps = FinRobotDeps(
        data_layer=data_layer,
        settings=settings,
        skill_runtime=registry,
        artifact_store=artifact_store,
    )

    app.state.agent = agent
    app.state.deps = deps
    app.state.secret_store = secret_store
    app.state.secret_storage_mode = secret_storage_mode
    app.state.settings_path = settings_path
    app.state.run_store = RunStore()
    app.state.run_tasks = {}
    app.state.artifact_store = artifact_store
    # Bounded LRU dict for transcript writers.  Using OrderedDict lets us
    # evict the least-recently-used entry in O(1) when the cap is reached.
    # TranscriptWriter is open-on-write (no persistent file handle), so
    # eviction is purely a memory-size guard — no flush/close needed.
    # Cap at 256: a desktop user will never have 256 concurrent chat sessions;
    # anything beyond that is a test or a leak worth discarding.
    transcript_writers: OrderedDict[str, TranscriptWriter] = OrderedDict()
    app.state.transcript_writers = transcript_writers
    app.state.sub_agents = sub_agents

    # Background task: archive stale artifacts (unviewed for 30 days).
    # Was 24h until 2026-05-27 — too aggressive for a desktop research
    # tool. The user's workflow is "skim landing → drill into a stale
    # ticker a week later", and a 24h cutoff was hiding everything from
    # the recent-research drawer within a day. 30d matches both the
    # analyst-research review cycle and the FinRobot dashboard's "all"
    # window expectation; the user can still hard-archive a ticker
    # explicitly from the UI when they want it gone.
    async def _archive_stale_background() -> None:
        try:
            count = await artifact_store.archive_stale(hours=24 * 30)
            if count:
                logger.info("Startup artifact archive: %d artifacts archived", count)
        except (OSError, ValueError, TypeError, RuntimeError):
            logger.exception("Startup artifact archive failed — non-fatal")

    # One-shot legacy migration: pull every ~/.finrobot-desktop/artifacts/
    # JSON file into the new SqliteArtifactStore. Idempotent (saves are
    # upserts) — re-runs on every startup but only does real work the first
    # time after the user upgrades.
    async def _migrate_legacy_artifacts_background() -> None:
        try:
            count = await migrate_filesystem_to_sqlite(store=artifact_store)
            if count:
                logger.info("Migrated %d legacy filesystem artifacts to SQLite", count)
        except (OSError, ValueError, TypeError, RuntimeError):
            logger.exception("Legacy artifact migration failed — non-fatal")

    # Initialize warmup status so /api/health/quotes-warmed has a defined
    # value before the background task fires (= False, "still warming").
    app.state.quotes_warmed = False
    app.state.quotes_warmed_ticker_count = 0

    # Warm the QuoteCache for every studied ticker so the first landing
    # page load doesn't pay the cold yfinance penalty (4-5s pre-fix). The
    # cache TTL is 60s; if the user touches the dashboard before warmup
    # completes they fall through to the same fetch they would have made
    # without this hook, so the warmup is a strict latency improvement —
    # never a correctness dependency.
    #
    # Sequenced AFTER the legacy artifact migration so that, on the very
    # first boot after upgrading, the warmup sees the migrated tickers
    # instead of an empty SQLite. Without this await, an upgrading user
    # paid the cold yfinance cost on their first dashboard load.
    #
    # The `warmed` flag is set in a `finally` block so a yfinance outage
    # or one-off exception cannot leave the frontend polling forever.
    #
    # Hard cap (_WARMUP_BUDGET_SECONDS): if yfinance is rate-limited or
    # otherwise slow, warmup must not delay the rest of boot. After the
    # cap we surrender and mark warmed=True so the UI stops polling; the
    # first dashboard request will lazy-fetch any tickers we didn't get.
    _WARMUP_BUDGET_SECONDS = 8.0

    async def _warm_quote_cache_background() -> None:
        ticker_count = 0
        try:
            summaries = await artifact_store.list_by_ticker(
                ticker=None, include_archived=False, limit=500
            )
            tickers = sorted({s.ticker for s in summaries if s.ticker})
            ticker_count = len(tickers)
            if not tickers:
                return
            from finrobot.engine.data.quote_batch import fetch_quotes_batch_cached

            try:
                await asyncio.wait_for(
                    fetch_quotes_batch_cached(tickers, data_layer),
                    timeout=_WARMUP_BUDGET_SECONDS,
                )
                logger.info("Quote cache warmed for %d studied tickers", len(tickers))
            except asyncio.TimeoutError:
                logger.warning(
                    "Quote cache warmup exceeded %.1fs budget for %d tickers — "
                    "lazy fetch will fill the gap",
                    _WARMUP_BUDGET_SECONDS,
                    len(tickers),
                )
        except (OSError, ValueError, TypeError, RuntimeError):
            logger.exception("Quote cache warmup failed — non-fatal")
        finally:
            app.state.quotes_warmed = True
            app.state.quotes_warmed_ticker_count = ticker_count

    async def _migrate_then_warm_background() -> None:
        await _migrate_legacy_artifacts_background()
        await _warm_quote_cache_background()

    async def _refresh_sec_holdings_background() -> None:
        if not settings.sec_holdings_auto_refresh:
            return
        from finrobot.engine.data.providers.edgar_provider import (
            _is_valid_identity,
            _sec_header_identity,
        )
        from finrobot.engine.data.sec_holdings_cache import cache_status
        from scripts.refresh_sec_holdings import (
            _latest_completed_quarter_end,
            _refresh_quarter,
        )

        if not _is_valid_identity(settings.sec_user_agent):
            logger.info("SEC 13F holdings refresh skipped: SEC identity not configured")
            return
        header_identity = _sec_header_identity(settings.sec_user_agent)
        if header_identity is None:
            logger.info("SEC 13F holdings refresh skipped: SEC identity not configured")
            return
        try:
            status = await cache_status()
            latest_raw = status.get("latest_period_end")
            if latest_raw:
                latest = date.fromisoformat(str(latest_raw))
                if (date.today() - latest).days <= 60:
                    logger.info(
                        "SEC 13F holdings refresh skipped: cache fresh at %s",
                        latest.isoformat(),
                    )
                    return
            period = _latest_completed_quarter_end()
            from edgar import set_identity

            set_identity(header_identity)
            logger.info("SEC 13F holdings refresh starting: period_end=%s", period.isoformat())
            # Offload to a worker thread with its own event loop. _refresh_quarter
            # is declared async, but its core is a *synchronous* edgartools parse
            # of an entire quarter of 13F filings (get_filings → f.obj() →
            # holdings_df) that blocks between awaits. Awaiting it directly on the
            # server loop would freeze every concurrent request — dashboard
            # included — for the duration of the parse (architecture red line:
            # tests/audit/test_architecture.py::TestEventLoopNotBlocked).
            #
            # The previous design used a ``python -m scripts...`` subprocess for
            # this isolation, but that cannot work in the frozen desktop sidecar
            # (sys.executable is the bundled binary, not a Python interpreter, and
            # the repo tree does not exist). A worker thread gives the same
            # off-loop isolation and works identically in dev and in the bundle.
            summary = await asyncio.to_thread(asyncio.run, _refresh_quarter(period))
            logger.info("SEC 13F holdings refresh complete: %s", summary)
        except asyncio.CancelledError:
            raise
        except (ImportError, OSError, RuntimeError, ValueError, TypeError, AttributeError):
            logger.exception("SEC 13F holdings refresh failed — non-fatal")

    app.state.background_tasks = [
        asyncio.create_task(_archive_stale_background()),
        asyncio.create_task(_migrate_then_warm_background()),
        asyncio.create_task(_refresh_sec_holdings_background()),
    ]

    yield
    for task in list(getattr(app.state, "background_tasks", [])):
        if not task.done():
            task.cancel()
    await asyncio.gather(*getattr(app.state, "background_tasks", []), return_exceptions=True)
    for task in list(app.state.run_tasks.values()):
        if not task.done():
            task.cancel()
    # Await cancelled tasks so in-flight pipelines finish cleanup before
    # we tear down shared resources (data_layer, run_store).
    await asyncio.gather(*app.state.run_tasks.values(), return_exceptions=True)
    await data_layer.close()
    await app.state.run_store.close()
    # Close every aiosqlite-backed store explicitly so the WAL gets
    # checkpointed before the asyncio loop tears down. Without this the
    # connection worker thread races the loop close and produces noisy
    # "Event loop is closed" warnings on every Tauri shutdown / pytest run.
    try:
        await artifact_store.close()
    except (OSError, RuntimeError):
        logger.exception("ArtifactStore shutdown error")
    from finrobot.engine.data.quote_batch import close_quote_cache_singleton

    try:
        await close_quote_cache_singleton()
    except (OSError, RuntimeError):
        logger.exception("QuoteCache shutdown error")
    from finrobot.engine.data.sec_holdings_cache import close_singleton as close_sec_holdings_cache

    try:
        await close_sec_holdings_cache()
    except (OSError, RuntimeError):
        logger.exception("SEC holdings cache shutdown error")
    # Flush all open transcript writers so session_end events are recorded.
    for writer in list(app.state.transcript_writers.values()):
        try:
            await writer.log_session_end()
            await writer.close()
        except (OSError, ValueError, RuntimeError):
            logger.exception("TranscriptWriter shutdown error (session=%s)", writer.session_id)


# WARNING: This server has no authentication. For local development only.
# Do not expose to public network without adding auth middleware.
app = FastAPI(title="FinRobot", lifespan=lifespan)

# CORS: allow Vite dev server origin (electron dev mode uses http://localhost:5173).
# Production Electron loads from file:// so this has no effect on packaged builds.
app.add_middleware(RequestTraceMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(compute_router)
app.include_router(data_router)
app.include_router(health_router)
app.include_router(settings_router)
app.include_router(runs_router)
app.include_router(artifacts_router)
app.include_router(dashboard_router)
app.include_router(search_router, prefix="/api/search", tags=["search"])
app.include_router(valuation_router)
app.include_router(sentiment_router)
app.include_router(notify_router)
app.include_router(diagnostics_router)


def _extract_user_text(message: dict[str, Any]) -> str:
    """Extract user text from any of the three supported message shapes.

    Vercel AI SDK v4+ and the Claude messages format use a ``parts`` array
    instead of a string ``content`` field.  The previous implementation only
    handled string content, silently writing empty strings to the audit log
    for every parts-based client.

    Supported shapes:
        - ``{"role": "user", "content": "string"}``               (legacy)
        - ``{"role": "user", "content": [{"type": "text", ...}]}`` (mixed)
        - ``{"role": "user", "parts":   [{"type": "text", ...}]}`` (modern)

    Non-text parts are rendered as placeholders so the transcript still
    records that something non-text was sent:
        - ``image``                → ``"[image]"``
        - ``file``                 → ``"[attached: <filename>]"``
        - anything else / unknown  → skipped silently
    """
    content = message.get("content")
    if isinstance(content, str):
        return content

    # parts-based — could live on ``parts`` (modern) or be a list ``content``
    parts: list[Any] = []
    if isinstance(message.get("parts"), list):
        parts = message["parts"]
    elif isinstance(content, list):
        parts = content

    text_fragments: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue  # non-dict parts (raw strings, ints, etc.) silently skipped
        part_type = part.get("type")
        if part_type == "text":
            text_value = part.get("text")
            if isinstance(text_value, str):
                text_fragments.append(text_value)
        elif part_type == "image":
            text_fragments.append("[image]")
        elif part_type == "file":
            fname = part.get("filename") or "file"
            text_fragments.append(f"[attached: {fname}]")
        # Unknown part types are intentionally skipped.

    return "\n".join(text_fragments)


_TRANSCRIPT_WRITERS_MAX = 256


async def _get_or_create_writer(
    app_state: Any, session_id: str, model_hint: str
) -> TranscriptWriter:
    """Return an existing TranscriptWriter or create a new one with session_start.

    Writers are kept in a bounded LRU OrderedDict (cap: _TRANSCRIPT_WRITERS_MAX).
    When the cap is reached the oldest entry is discarded.  TranscriptWriter
    uses open-on-write semantics (no persistent file handle), so eviction is a
    pure memory guard — no flush or close is required on removal.

    Defensively creates the ``transcript_writers`` dict on ``app_state`` if it
    is missing (e.g. tests that bypass lifespan and set state manually).
    """
    if not hasattr(app_state, "transcript_writers"):
        app_state.transcript_writers = OrderedDict()
    writers: OrderedDict[str, TranscriptWriter] = app_state.transcript_writers
    if session_id in writers:
        # Move to end (most-recently-used) on access.
        writers.move_to_end(session_id)
        return writers[session_id]

    writer = TranscriptWriter(session_id)
    try:
        await writer.log_session_start(user_id="local", model=model_hint)
    except OSError:
        logger.exception("TranscriptWriter: failed to write session_start for %s", session_id)

    # Evict LRU entry before inserting so we never exceed the cap.
    if len(writers) >= _TRANSCRIPT_WRITERS_MAX:
        evicted_id, _ = writers.popitem(last=False)
        logger.debug("TranscriptWriter LRU eviction: session=%s", evicted_id)

    writers[session_id] = writer
    return writer


async def _intercept_native_events(
    native_stream: AsyncIterator[Any],
    writer: TranscriptWriter,
) -> AsyncIterator[Any]:
    """Pass-through wrapper that mirrors pydantic_ai native events to the transcript.

    Handles:
      - ``PartEndEvent`` with ``TextPart``        → ``assistant_text``
      - ``FunctionToolCallEvent``                  → ``tool_call``
      - ``FunctionToolResultEvent``               → ``tool_result``

    Uses ``PartEndEvent`` (not ``PartStartEvent``) for text so we log the
    complete text of each part in one write instead of streaming deltas.
    """
    from pydantic_ai.messages import (
        FunctionToolCallEvent,
        FunctionToolResultEvent,
        PartEndEvent,
        TextPart,
        ToolReturnPart,
    )

    # Accumulate text parts per index so we can log the full text on PartEndEvent.
    _text_parts: dict[int, str] = {}

    async for event in native_stream:
        # --- assistant text ---
        if isinstance(event, PartEndEvent) and isinstance(event.part, TextPart):
            text = event.part.content
            try:
                await writer.log_assistant_text(text)
            except OSError:
                logger.exception("TranscriptWriter: failed to log assistant_text")

        # --- tool call ---
        elif isinstance(event, FunctionToolCallEvent):
            part = event.part
            try:
                args = part.args_as_dict() if hasattr(part, "args_as_dict") else {}
            except (ValueError, TypeError):
                args = {}
            try:
                await writer.log_tool_call(part.tool_name, part.tool_call_id, args)
            except OSError:
                logger.exception("TranscriptWriter: failed to log tool_call")

        # --- tool result ---
        elif isinstance(event, FunctionToolResultEvent):
            result_part = event.result
            is_error = getattr(result_part, "outcome", "success") == "failed"
            # Extract artifact_id if the tool returned it in a dict payload.
            artifact_id: str | None = None
            if isinstance(result_part, ToolReturnPart):
                try:
                    obj = result_part.model_response_object()
                    if isinstance(obj, dict):
                        artifact_id = obj.get("artifact_id")
                except (ValueError, TypeError, AttributeError):
                    pass
            try:
                content = (
                    result_part.content if hasattr(result_part, "content") else str(result_part)
                )
                await writer.log_tool_result(
                    result_part.tool_call_id,
                    result_part.tool_name or "",
                    content,
                    is_error=is_error,
                    artifact_id=artifact_id,
                )
            except OSError:
                logger.exception("TranscriptWriter: failed to log tool_result")

        yield event


async def _chat_impl(
    request: Request,
    body_json: dict[str, Any],
    session_id: str,
    model_hint: str,
) -> Response:
    # Log the user's latest message before streaming begins.
    writer = await _get_or_create_writer(request.app.state, session_id, model_hint)
    messages: list[Any] = body_json.get("messages", [])
    if messages:
        last_msg = messages[-1]
        if isinstance(last_msg, dict) and last_msg.get("role") == "user":
            text_content = _extract_user_text(last_msg)
            try:
                await writer.log_user_message(text_content)
            except OSError:
                logger.exception(
                    "TranscriptWriter: failed to log user_msg for session %s", session_id
                )

    # Build the adapter manually so we can intercept the native event stream.
    # Starlette caches request._body after the first read, so calling
    # from_request here (which calls request.body() again) is safe.
    try:
        adapter = await VercelAIAdapter.from_request(
            request,
            agent=request.app.state.agent,
        )
    except ValidationError as exc:
        # Mirror the behaviour of VercelAIAdapter.dispatch_request which catches
        # ValidationError from build_run_input and returns 422.
        return JSONResponse(
            content=exc.errors(include_url=False),
            media_type="application/json",
            status_code=422,
        )

    native_stream = adapter.run_stream_native(deps=request.app.state.deps)
    instrumented_stream = _intercept_native_events(native_stream, writer)
    event_stream = adapter.transform_stream(instrumented_stream)
    return adapter.streaming_response(event_stream)


@app.post("/chat")
async def chat(request: Request) -> Response:
    """Handle a Vercel AI SDK chat request with transcript side-logging.

    The transcript hook intercepts native pydantic_ai stream events to write
    user messages, assistant text, tool calls, and tool results to a per-session
    JSONL file at ``~/.finrobot-desktop/sessions/<session_id>.jsonl``.

    Transcript write failures are logged and never surface to the client —
    the Vercel AI stream is unaffected by transcript I/O errors.
    """
    body = await request.body()
    try:
        body_json: dict[str, Any] = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        body_json = {}

    session_id: str = body_json.get("id") or body_json.get("session_id") or "default"
    model_hint: str = str(body_json.get("model") or "unknown")
    with bind_session(session_id):
        return await _chat_impl(request, body_json, session_id, model_hint)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ready"}
