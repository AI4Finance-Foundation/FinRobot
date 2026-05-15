import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from pydantic_ai.ui.vercel_ai import VercelAIAdapter

from finagent.config import get_settings
from finagent.data_layer_factory import build_data_layer
from finagent.engine.data.interface import ProviderError
from finagent.engine.deps import FinAgentDeps
from finagent.engine.orchestrator import build_report_context, create_lead_agent
from finagent.engine.skills.registry import SkillRegistry
from finagent.artifact.store import ArtifactStore
from finagent.audit.transcript import TranscriptWriter
from finagent.routes.analyze import router as analyze_router
from finagent.routes.artifacts import router as artifacts_router
from finagent.routes.ask import router as ask_router
from finagent.routes.backtest import router as backtest_router
from finagent.routes.compute import router as compute_router
from finagent.routes.data import router as data_router
from finagent.routes.export import router as export_router
from finagent.routes.runs import router as runs_router
from finagent.routes.market import router as market_router
from finagent.routes.journal import router as journal_router
from finagent.routes.search import router as search_router
from finagent.routes.notify import router as notify_router
from finagent.routes.settings import load_non_secret_settings
from finagent.routes.settings import router as settings_router
from finagent.run_store import RunStore
from finagent.secret_store import SecretStore, create_secret_store
from finagent.web import web_router

logger = logging.getLogger(__name__)


# Fix 4.4: Pipeline factories moved to registry module to break
# circular import (server → web → tasks → server).
from finagent.engine.pipelines.registry import get_pipeline_factories


def _get_pipeline_factories() -> dict[str, Callable[..., Any]]:
    """Thin wrapper kept for backwards compatibility."""
    return get_pipeline_factories()


async def hydrate_settings_from_secrets(settings: Any, secret_store: SecretStore) -> Any:
    """Return settings with API keys loaded from SecretStore."""
    update: dict[str, str] = {}
    for key in (
        "anthropic_api_key",
        "deepseek_api_key",
        "openai_api_key",
        "fmp_api_key",
        "finnhub_api_key",
        "alpha_vantage_api_key",
    ):
        value = await secret_store.get(key)
        if value:
            update[key] = value
    return settings.model_copy(update=update)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings_path = Path.home() / ".finagent" / "settings.json"
    settings = get_settings(**load_non_secret_settings(settings_path))
    secret_store = create_secret_store()
    settings = await hydrate_settings_from_secrets(settings, secret_store)

    # Load skills if available
    skills_path = Path(settings.skills_dir)
    registry = SkillRegistry(skills_path) if skills_path.exists() else None

    data_layer = build_data_layer(settings)

    # Artifact store: persists computational snapshots for audit trail
    artifact_store = ArtifactStore()

    # Create agent
    agent = create_lead_agent(settings, skill_registry=registry)
    deps = FinAgentDeps(
        data_layer=data_layer,
        settings=settings,
        skill_runtime=registry,
        artifact_store=artifact_store,
    )

    from finagent.engine.agents.factory import create_sub_agents

    app.state.agent = agent
    app.state.deps = deps
    app.state.secret_store = secret_store
    app.state.settings_path = settings_path
    app.state.run_store = RunStore()
    app.state.run_tasks = {}
    app.state.artifact_store = artifact_store
    # Transcript writers: session_id → TranscriptWriter (in-memory cache)
    app.state.transcript_writers: dict[str, TranscriptWriter] = {}
    app.state.sub_agents = create_sub_agents(
        deps.settings, skill_registry=deps.skill_runtime
    )

    # Background task: archive stale artifacts (unviewed for 24h)
    async def _archive_stale_background() -> None:
        try:
            count = await artifact_store.archive_stale(hours=24)
            if count:
                logger.info("Startup artifact archive: %d artifacts archived", count)
        except (OSError, ValueError, TypeError, RuntimeError):
            logger.exception("Startup artifact archive failed — non-fatal")

    asyncio.create_task(_archive_stale_background())

    yield
    for task in list(app.state.run_tasks.values()):
        if not task.done():
            task.cancel()
    # Await cancelled tasks so in-flight pipelines finish cleanup before
    # we tear down shared resources (data_layer, run_store).
    await asyncio.gather(*app.state.run_tasks.values(), return_exceptions=True)
    await data_layer.close()
    await app.state.run_store.close()
    # Flush all open transcript writers so session_end events are recorded.
    for writer in list(app.state.transcript_writers.values()):
        try:
            await writer.log_session_end()
            await writer.close()
        except (OSError, ValueError, RuntimeError):
            logger.exception("TranscriptWriter shutdown error (session=%s)", writer.session_id)


# WARNING: This server has no authentication. For local development only.
# Do not expose to public network without adding auth middleware.
app = FastAPI(title="FinAgent", lifespan=lifespan)

# CORS: allow Vite dev server origin (electron dev mode uses http://localhost:5173).
# Production Electron loads from file:// so this has no effect on packaged builds.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(web_router)
app.include_router(analyze_router)
app.include_router(ask_router)
app.include_router(backtest_router)
app.include_router(compute_router)
app.include_router(data_router)
app.include_router(export_router)
app.include_router(settings_router)
app.include_router(runs_router)
app.include_router(artifacts_router)
app.include_router(market_router)
app.include_router(journal_router)
app.include_router(search_router, prefix="/api/search", tags=["search"])
app.include_router(notify_router)


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


async def _get_or_create_writer(
    app_state: Any, session_id: str, model_hint: str
) -> TranscriptWriter:
    """Return an existing TranscriptWriter or create a new one with session_start.

    Defensively creates the ``transcript_writers`` dict on ``app_state`` if it
    is missing (e.g. tests that bypass lifespan and set state manually).
    """
    if not hasattr(app_state, "transcript_writers"):
        app_state.transcript_writers = {}
    writers: dict[str, TranscriptWriter] = app_state.transcript_writers
    if session_id not in writers:
        writer = TranscriptWriter(session_id)
        try:
            await writer.log_session_start(user_id="local", model=model_hint)
        except OSError:
            logger.exception("TranscriptWriter: failed to write session_start for %s", session_id)
        writers[session_id] = writer
    return writers[session_id]


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
                content = result_part.content if hasattr(result_part, "content") else str(result_part)
                await writer.log_tool_result(
                    result_part.tool_call_id,
                    result_part.tool_name,
                    content,
                    is_error=is_error,
                    artifact_id=artifact_id,
                )
            except OSError:
                logger.exception("TranscriptWriter: failed to log tool_result")

        yield event


@app.post("/chat")
async def chat(request: Request) -> Response:
    """Handle a Vercel AI SDK chat request with transcript side-logging.

    The transcript hook intercepts native pydantic_ai stream events to write
    user messages, assistant text, tool calls, and tool results to a per-session
    JSONL file at ``~/.finagent-desktop/sessions/<session_id>.jsonl``.

    Transcript write failures are logged and never surface to the client —
    the Vercel AI stream is unaffected by transcript I/O errors.
    """
    body = await request.body()
    try:
        body_json: dict[str, Any] = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        body_json = {}

    session_id: str = (
        body_json.get("id")
        or body_json.get("session_id")
        or "default"
    )
    model_hint: str = str(body_json.get("model") or "unknown")

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
                logger.exception("TranscriptWriter: failed to log user_msg for session %s", session_id)

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


@app.get("/api/pipeline/stream/{pipeline_type}/{ticker}")
async def pipeline_stream(pipeline_type: str, ticker: str, request: Request) -> Response:
    """Stream pipeline progress as Server-Sent Events.

    Events emitted (one JSON object per SSE `data:` frame):
      - step_start: {step, total, name}
      - step_end:   {step, total, name, duration}
      - step_retry: {step, name, attempt}
      - complete:   {ticker, report_url}
      - error:      {message}
    """
    import asyncio

    factories = _get_pipeline_factories()
    if pipeline_type not in factories:
        return JSONResponse(
            status_code=400,
            content={
                "error": (
                    f"Invalid pipeline: {pipeline_type}. "
                    f"Valid: {sorted(factories.keys())}"
                )
            },
        )

    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    class SseProgress:
        """ProgressCallback that pushes events into the SSE queue."""

        async def on_step_start(self, step_index: int, total: int, name: str) -> None:
            await queue.put(
                {"event": "step_start", "step": step_index, "total": total, "name": name}
            )

        async def on_step_end(
            self, step_index: int, total: int, name: str, duration: float
        ) -> None:
            await queue.put(
                {
                    "event": "step_end",
                    "step": step_index,
                    "total": total,
                    "name": name,
                    "duration": round(duration, 1),
                }
            )

        async def on_step_retry(
            self, step_index: int, name: str, attempt: int, error: str
        ) -> None:
            await queue.put(
                {
                    "event": "step_retry",
                    "step": step_index,
                    "name": name,
                    "attempt": attempt,
                }
            )

    async def run_pipeline() -> None:
        try:
            deps = request.app.state.deps
            sub_agents = request.app.state.sub_agents
            pipeline = factories[pipeline_type](sub_agents)
            result = await pipeline.execute(deps, ticker, progress=SseProgress())
            deps.report_cache[ticker.upper()] = build_report_context(ticker, result)
            await queue.put({
                "event": "complete",
                "ticker": ticker,
                "report_url": f"/api/report/html?ticker={ticker}",
            })
        except asyncio.CancelledError:
            # Client disconnected. Let event_stream's except-and-cancel path
            # observe the cancellation by re-raising through the task. The
            # finally block still runs so the sentinel is queued.
            raise
        except (ProviderError, ValidationError, ValueError, RuntimeError) as e:
            # Known failure modes: data provider exhausted, LLM output failed
            # validation, pipeline arithmetic/config error. Everything else
            # (KeyboardInterrupt, SystemExit, MemoryError, programming bugs)
            # is intentionally NOT caught here so it surfaces as a real crash
            # instead of being hidden inside an SSE "error" event.
            await queue.put({"event": "error", "message": str(e)[:500]})
        finally:
            await queue.put(None)  # sentinel — signals event_stream to exit

    async def event_stream() -> Any:
        task = asyncio.create_task(run_pipeline())
        try:
            while True:
                msg = await queue.get()
                if msg is None:
                    break
                yield f"data: {json.dumps(msg)}\n\n"
            # Propagate any exception that escaped run_pipeline's try/except
            # (shouldn't happen, but defensive).
            await task
        except (asyncio.CancelledError, GeneratorExit):
            # Client disconnected — cancel the pipeline task so it doesn't leak.
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            raise

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ready"}


@app.get("/api/report/html")
async def report_html(request: Request, ticker: str) -> HTMLResponse:
    """Generate and return HTML equity research report from cached pipeline results."""
    from finagent.engine.reports.html_renderer import render_equity_report

    context = request.app.state.deps.report_cache.get(ticker.upper())
    if context is None:
        return HTMLResponse("<h1>No report available. Run analysis first.</h1>", status_code=404)
    html = render_equity_report(context)
    return HTMLResponse(content=html)


@app.get("/api/export/excel/{analysis_type}/{ticker}")
async def export_excel(analysis_type: str, ticker: str, request: Request) -> Response:
    """Download .xlsx model for analysis_type in {'dcf', 'lbo', 'comps'}.

    Requires the corresponding pipeline to have been run first (results cached).
    """
    from finagent.engine.compute.spreadsheet_gen import (
        generate_comps_excel,
        generate_dcf_excel,
    )
    from finagent.engine.models.financial import DCFResult, PeerComps

    _VALID_TYPES = {"dcf", "lbo", "comps"}
    if analysis_type not in _VALID_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"analysis_type must be one of {sorted(_VALID_TYPES)}",
        )

    cache = request.app.state.deps.report_cache.get(ticker.upper())
    if cache is None:
        raise HTTPException(
            status_code=404,
            detail=f"No cached results for {ticker.upper()}. Run analysis first.",
        )

    if analysis_type == "lbo":
        from finagent.engine.compute.spreadsheet_gen import generate_lbo_excel
        from finagent.engine.models.financial import LBOInputs, LBOResult

        lbo_result: LBOResult | None = cache.get("lbo_result")
        lbo_inputs: LBOInputs | None = cache.get("lbo_inputs")
        if lbo_result is None or lbo_inputs is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "LBO inputs/result not in cache. Re-run the LBO pipeline "
                    "to populate them."
                ),
            )
        xlsx_bytes = generate_lbo_excel(lbo_result, lbo_inputs)

    elif analysis_type == "dcf":
        dcf_result: DCFResult | None = cache.get("dcf_result")
        if dcf_result is None:
            raise HTTPException(status_code=404, detail="No DCF result cached for this ticker.")
        xlsx_bytes = generate_dcf_excel(dcf_result, dcf_result.inputs)

    else:  # comps
        peer_comps: PeerComps | None = cache.get("peer_comps")
        if peer_comps is None:
            raise HTTPException(status_code=404, detail="No comps result cached for this ticker.")
        all_companies = [peer_comps.target] + list(peer_comps.peers)
        xlsx_bytes = generate_comps_excel(all_companies)

    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f"attachment; filename={ticker.upper()}_{analysis_type}.xlsx"
            )
        },
    )


@app.get("/api/report/pdf")
async def report_pdf(request: Request, ticker: str) -> Response:
    """Generate and return PDF equity research report from cached pipeline results."""
    from finagent.engine.reports.html_renderer import render_equity_report
    from finagent.engine.reports.pdf_renderer import render_pdf

    context = request.app.state.deps.report_cache.get(ticker.upper())
    if context is None:
        return HTMLResponse("<h1>No report available. Run analysis first.</h1>", status_code=404)
    html = render_equity_report(context)
    try:
        pdf_bytes = render_pdf(html)
    except RuntimeError as e:
        return Response(content=str(e), status_code=501)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={ticker}_report.pdf"},
    )
