import asyncio
import json
import logging
import sqlite3
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from finrobot.auth import CapabilityAuthMiddleware
from finrobot.config import DATA_PROVIDER_SECRET_FIELDS, get_capability_token, get_settings
from finrobot.llm_probe import LlmProbeGate
from finrobot.obs import bind_session, setup_logging
from finrobot.obs.middleware import RequestTraceMiddleware
from finrobot.engine.data.cache import DataCache
from finrobot.engine.data.factory import build_provider_chain
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.skills.registry import SkillRegistry
from finrobot.artifact.migrate import migrate_filesystem_to_sqlite
from finrobot.artifact.store import ArtifactStore
from finrobot.paths import SETTINGS_JSON, ensure_home
from finrobot.audit.transcript import TranscriptWriter, is_valid_session_id
from finrobot.routes.artifacts import router as artifacts_router
from finrobot.routes.chat_sessions import router as chat_sessions_router
from finrobot.routes.compute import router as compute_router
from finrobot.routes.coverage import router as coverage_router
from finrobot.routes.dashboard import router as dashboard_router
from finrobot.routes.data import router as data_router
from finrobot.routes.health import router as health_router
from finrobot.routes.runs import router as runs_router
from finrobot.routes.search import router as search_router
from finrobot.routes.sec_holdings import router as sec_holdings_router
from finrobot.routes.settings import load_non_secret_settings_with_error
from finrobot.routes.settings import router as settings_router
from finrobot.routes.sentiment import router as sentiment_router
from finrobot.routes.valuation import router as valuation_router
from finrobot.coverage.prompt import format_coverage_snapshot
from finrobot.coverage.service import build_overview
from finrobot.coverage.sqlite_store import CoverageStore
from finrobot.ratelimit import RunRateLimiter
from finrobot.run_store import RunStore
from finrobot.secret_store import SecretStore, create_secret_store

logger = logging.getLogger(__name__)

# Max pipelines executing at once across the whole app (Coverage Phase 2/M4c).
# 4 balances batch throughput against provider/LLM rate limits on a desktop box.
_MAX_CONCURRENT_RUNS = 4

# Concrete failure modes the per-turn watchlist snapshot degrades on (it is a
# pure prompt augmentation — never let it break a chat turn). Mirrors the
# project convention of enumerating modes instead of bare `except Exception:`
# (dashboard._QUOTE_BATCH_DEGRADABLE). build_overview already degrades per-row,
# so these cover the store/db/loop-level faults that escape it:
# get_system_group's aiosqlite read, a wedged worker, loop teardown, OS errors.
_COVERAGE_SNAPSHOT_DEGRADABLE = (
    sqlite3.Error,
    RuntimeError,
    OSError,
    ValueError,
    TypeError,
    AttributeError,
)


async def hydrate_settings_from_secrets(settings: Any, secret_store: SecretStore) -> Any:
    """Return settings with API keys loaded from the keychain.

    Secrets live in the keychain (never settings.json) and must be hydrated back
    into FinRobotSettings on every boot so the data layer and LLM providers see
    them. Two key families:

    - DataProvider keys (FMP / Finnhub / …) → fixed fields, via model_copy.
    - LLM provider keys → the dynamic ``provider_key:<id>`` scheme (one per
      registered provider), injected into the private ``_provider_keys`` map so
      they never enter model_dump() / settings.json. See ADR-0013.
    """
    update: dict[str, str] = {}
    for key in DATA_PROVIDER_SECRET_FIELDS:
        value = await secret_store.get(key)
        if value:
            update[key] = value
    settings = settings.model_copy(update=update)

    provider_keys: dict[str, str] = {}
    for provider in settings.providers:
        value = await secret_store.get(f"provider_key:{provider.id}")
        if value:
            provider_keys[provider.id] = value
    if provider_keys:
        settings = settings.with_provider_keys(provider_keys)
    return settings


# Hard cap for the startup quote-cache warmup: if yfinance is rate-limited or
# otherwise slow, warmup must not delay the rest of boot. After the cap we
# surrender and mark warmed=True so the UI stops polling; the first dashboard
# request lazy-fetches any tickers we didn't get. Module-level so the H3
# timeout branch is unit-testable (tests pass a tiny budget_seconds).
_WARMUP_BUDGET_SECONDS = 8.0


async def warm_quote_cache(
    app: Any,
    artifact_store: Any,
    data_layer: Any,
    *,
    budget_seconds: float = _WARMUP_BUDGET_SECONDS,
) -> None:
    """Warm the QuoteCache for every studied ticker (startup background step).

    The first landing-page load otherwise pays the cold yfinance penalty
    (4-5s pre-fix). Cache TTL is 60s; touching the dashboard before warmup
    completes falls through to the same fetch it would have made anyway, so
    this is a strict latency improvement — never a correctness dependency.

    The ``quotes_warmed`` flag flips True in ``finally`` so a provider outage,
    a budget timeout or a store failure can never leave the frontend's
    /api/health/quotes-warmed poll spinning forever.

    ``app``/``artifact_store``/``data_layer`` are duck-typed (``app.state``
    attributes, ``list_by_ticker``, the DataLayer passed through to
    ``fetch_quotes_batch_cached``) so the unit tests can drive the timeout
    branch without booting a real lifespan.
    """
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
                timeout=budget_seconds,
            )
            logger.info("Quote cache warmed for %d studied tickers", len(tickers))
        except asyncio.TimeoutError:
            logger.warning(
                "Quote cache warmup exceeded %.1fs budget for %d tickers — "
                "lazy fetch will fill the gap",
                budget_seconds,
                len(tickers),
            )
    except (OSError, ValueError, TypeError, RuntimeError):
        logger.exception("Quote cache warmup failed — non-fatal")
    finally:
        app.state.quotes_warmed = True
        app.state.quotes_warmed_ticker_count = ticker_count


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Ensure ~/.finrobot/ exists before any storage class tries to open a
    # file under it. Cheap + idempotent.
    ensure_home()

    settings_path = SETTINGS_JSON
    # Corruption-tolerant read: the Tauri shell SIGKILLs the sidecar at exit, so
    # a torn settings.json was reachable (pre-atomic-write files especially). A
    # corrupt file must NEVER prevent boot — the desktop app needs HTTP up so
    # the user can repair the config in SettingsView. We degrade to defaults and
    # surface the corruption via the startup_error banner below.
    non_secret_overrides, settings_file_error = load_non_secret_settings_with_error(settings_path)
    settings = get_settings(**non_secret_overrides)
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
    # runtime_config_error (NOT validate_runtime_config directly): an empty
    # model_name is the expected first-run state, not an error — it returns None
    # so no banner shows and the user gets onboarding instead. Only a model that
    # IS chosen but broken (missing key / unknown provider) becomes a banner.
    startup_error: str | None = settings.runtime_config_error()
    if startup_error:
        logger.error("Runtime config validation failed: %s", startup_error)
    if settings_file_error:
        # A corrupt settings.json silently reset every non-secret setting to its
        # default — that fact must reach the user (banner via GET /api/settings),
        # not just a log line. Root cause first, then any validation error. The
        # banner clears itself on the next Settings save: PUT re-validates and
        # _merge_non_secret_settings rewrites the file clean.
        logger.error("Settings file corrupt at boot: %s", settings_file_error)
        startup_error = (
            f"{settings_file_error}; {startup_error}" if startup_error else settings_file_error
        )
    app.state.startup_error = startup_error

    # Load skills if available
    skills_path = Path(settings.skills_dir)
    registry = SkillRegistry(skills_path) if skills_path.exists() else None

    # Data layer: SEEDED EMPTY here, WIRED in a post-yield background task
    # (_build_data_layer_background). build_provider_chain imports the provider
    # modules (yfinance_provider ~0.27s + edgar_provider ~0.23s) — that import cost
    # would otherwise run during lifespan *startup* and block the port, since uvicorn
    # serves /health only after startup returns. The placeholder is a REAL DataLayer
    # over a REAL DataCache (so the cache, run reconcile, and every local-SQLite
    # route work immediately); add_providers fills the chain on the SAME object and
    # app.state.engine_ready flips once it's live. Routes needing live provider data
    # gate on engine_ready (require_ready_data_layer); local-SQLite routes never
    # touch the chain and serve at once — the whole point of the split.
    data_layer = DataLayer(providers=[], cache=DataCache(settings.cache_db_path))

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
    # LLM agents are built in a POST-YIELD background task (_build_agents_background
    # below), NOT inline here. create_sub_agents / create_lead_agent pull the whole
    # pydantic_ai stack (~0.45s of *import*, which slice A pushed off module load),
    # plus the provider constructor. Doing that during lifespan *startup* would
    # block the port: uvicorn only begins serving — /health included — after
    # startup returns. So leave them empty now; AI routes 503 "engine starting"
    # until app.state.agents_ready flips (chat/runs guards). The same deferral that
    # _replace_runtime_settings (Settings PUT) does NOT need — that path is already
    # off the boot critical path.
    agent: Any = None
    sub_agents: dict[str, Any] = {}

    # Cap concurrent pipelines app-wide (Coverage Phase 2/M4c): batch coverage
    # runs spawn one task per ticker, but only this many execute at once — the
    # rest stay "created" until a slot frees, so a 20-ticker batch can't blow
    # the provider / LLM rate limits. Single runs share the same pool.
    #
    # Built BEFORE deps so the same Semaphore is carried on FinRobotDeps. That
    # closes BUG-017: chat-triggered pipelines (orchestrator → pipeline.execute
    # with ctx.deps) and Coverage-batch runs both reach the cap through
    # deps.run_semaphore inside Pipeline.execute — there is no longer an
    # un-gated path that bypasses the shared pool.
    run_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_RUNS)

    # Coverage Desk store — the user's research coverage universe (groups +
    # members). Own aiosqlite db at ~/.finrobot/coverage.db; the overview
    # orchestration above it reuses artifact_store + data_layer (ADR-0012).
    # Built BEFORE deps and carried on FinRobotDeps so the chat orchestrator's
    # query_coverage_universe tool reaches the SAME instance the REST coverage
    # routes use (app.state.coverage_store below is this exact object — never a
    # second connection to the same db file).
    coverage_store = CoverageStore()

    deps = FinRobotDeps(
        data_layer=data_layer,
        settings=settings,
        skill_runtime=registry,
        artifact_store=artifact_store,
        coverage_store=coverage_store,
        run_semaphore=run_semaphore,
    )

    app.state.agent = agent
    # Flips True once _build_agents_background finishes (whether or not a usable
    # model was configured). AI routes use it to tell "engine still starting"
    # (False → 503 retry) from "started" (True → either serve or 503 "configure a
    # model"). See chat() and routes/runs.py.
    app.state.agents_ready = False
    # Flips True once _build_data_layer_background wires the provider chain onto the
    # placeholder DataLayer. Live-data routes 503 "starting" until then
    # (require_ready_data_layer); /health + local-SQLite routes never wait on it.
    app.state.engine_ready = False
    app.state.deps = deps
    app.state.secret_store = secret_store
    app.state.secret_storage_mode = secret_storage_mode
    app.state.settings_path = settings_path
    app.state.run_store = RunStore()
    app.state.run_tasks = {}
    # run_ids whose cancellation was requested via POST /api/runs/{id}/cancel.
    # The run task's CancelledError handler consults this to tell a user cancel
    # (persist terminal status `cancelled`) from a shutdown cancel (re-raise;
    # the next startup's reconciler marks the orphan failed). Entries are
    # removed in the task's `finally`.
    app.state.cancel_requested = set()
    # Same Semaphore instance that deps carries (built above). The REST path
    # (routes/runs.py) no longer wraps the pipeline in its own `async with`;
    # instead every run acquires the cap exactly once inside Pipeline.execute
    # via deps.run_semaphore, so chat / REST / coverage-batch all share this
    # single pool and a run can never double-acquire.
    app.state.run_semaphore = run_semaphore
    # Inbound token-bucket rate limiter for the cost-bearing endpoints (chat,
    # POST /api/runs, coverage batch). DEFENSE-IN-DEPTH separate from the
    # concurrency cap above: run_semaphore bounds how many runs execute AT ONCE,
    # this bounds how many can be STARTED per minute, so a runaway loop / retry
    # storm can't drain LLM credits + the EDGAR budget by just keeping the queue
    # full (BUG-043). 429 only fires under abnormal volume — buckets are sized
    # well above the largest legitimate coverage batch.
    app.state.run_rate_limiter = RunRateLimiter()
    # Submit-time LLM key-validity gate for the run-spawning endpoints (runs):
    # is_model_configured proves a key exists, this proves it can
    # authenticate. Success cached per (model, key) fingerprint; a green
    # Settings auto-test pre-seeds it. See finrobot/llm_probe.py.
    app.state.llm_probe_gate = LlmProbeGate()
    # Fail runs abandoned by a previous process (run_tasks is in-memory, so a
    # restart orphans every running row → wedged SSE + phantom in-progress in
    # the Coverage overview). M4b.
    try:
        reconciled = await app.state.run_store.reconcile_orphaned_runs()
        if reconciled:
            logger.info("Startup: reconciled %d orphaned run(s) to failed", reconciled)
    except (OSError, RuntimeError):
        logger.exception("Run reconcile on startup failed")
    # Bound run_events growth: drop the SSE event log of runs that finished more
    # than RUN_EVENT_RETENTION_DAYS ago (the runs rows stay as history). Without
    # this the table grew unbounded and every SSE poll paid the larger scan on
    # the single shared connection under batch fan-out (BUG-050).
    try:
        pruned = await app.state.run_store.prune_run_events()
        if pruned:
            logger.info("Startup: pruned %d stale run_events row(s)", pruned)
    except (OSError, RuntimeError):
        logger.exception("run_events prune on startup failed")
    app.state.artifact_store = artifact_store
    # Reuse the SAME CoverageStore built above (carried on deps) — a second
    # CoverageStore() here would open a duplicate connection to coverage.db and
    # leave the chat tool reading a different handle than the REST routes.
    app.state.coverage_store = coverage_store
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

    # Re-project the mirror columns (verdict/entry/target/tagline/headline) when
    # the summary_extractor rules changed since the db was last projected. The
    # columns are written only at save() time but read as source-of-truth by the
    # dashboard/coverage aggregations, so without this old rows keep the value
    # the OLD extractor produced forever (BUG-065). Gated on
    # SUMMARY_PROJECTION_VERSION so it's a no-op unless the version was bumped.
    async def _rebuild_summaries_background() -> None:
        try:
            count = await artifact_store.rebuild_summaries_if_outdated()
            if count:
                logger.info("Startup mirror-column backfill: %d artifacts re-projected", count)
        except (OSError, ValueError, TypeError, RuntimeError):
            logger.exception("Startup mirror-column backfill failed — non-fatal")

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

    # Set by _build_data_layer_background once the provider chain is wired onto the
    # placeholder DataLayer; the quote warmup waits on it because the placeholder
    # has no providers to fetch from until then (cold-start split).
    engine_ready_event = asyncio.Event()

    async def _migrate_then_warm_background() -> None:
        await _migrate_legacy_artifacts_background()
        # Sequenced AFTER the migration so freshly-migrated legacy rows are
        # included in the projection version gate (BUG-065) and the quote
        # warmup (module-level warm_quote_cache, H3) sees the migrated
        # tickers instead of an empty SQLite on first post-upgrade boot.
        await _rebuild_summaries_background()
        # AND after the provider chain is live — data_layer is the same object the
        # warmup task fills, but it holds no providers until then.
        await engine_ready_event.wait()
        await warm_quote_cache(app, artifact_store, data_layer)

    # Background task: evict long-stale rows from the data cache (BUG-049).
    # The TTL only marks rows stale at read time and never deletes, so
    # data_cache.db grows monotonically with every (ticker × data_type ×
    # raw/canonical × period) slot ever fetched. This coarse 30-day absolute
    # eviction — far above the largest per-type TTL (7d) so it never reaps a
    # row a read would still consider fresh — caps that growth and VACUUMs the
    # freed space back to the filesystem. Runs at startup; non-fatal.
    async def _evict_data_cache_background() -> None:
        try:
            deleted = await data_layer.cache.evict_expired()
            if deleted:
                logger.info("Startup data-cache eviction: %d stale rows removed", deleted)
        except (OSError, ValueError, TypeError, RuntimeError):
            logger.exception("Startup data-cache eviction failed — non-fatal")

    async def _warm_symbol_index_background() -> None:
        # Load the SEC ticker-autocomplete index once at startup (cached daily to
        # ~/.finrobot/) so the homepage typeahead serves from memory. Non-fatal:
        # warm_symbol_index never raises (a fetch failure degrades to an empty /
        # stale index), but guard the gather anyway.
        from finrobot.engine.data.symbol_index import warm_symbol_index

        try:
            index = await warm_symbol_index(settings.sec_user_agent)
            logger.info("Symbol autocomplete index warmed: %d symbols", len(index.entries))
        except (
            OSError,
            RuntimeError,
            ValueError,
            TypeError,
            KeyError,
            ImportError,
            AttributeError,
        ):
            # warm_symbol_index degrades internally and is contracted never to raise;
            # this enumerates the concrete modes a regression could still leak (disk,
            # async/loop, malformed SEC payload, lazy import) so a warmup blip never
            # crashes startup — honouring the project's no-bare-`except Exception` rule.
            logger.exception("Symbol index warmup failed — non-fatal (typeahead degrades)")

    async def _refresh_sec_holdings_background() -> None:
        # Auto-refresh is OFF by default (heavy whole-quarter download). When
        # on, delegate to the shared trigger so startup auto-refresh and the
        # Settings → 立即同步 button run the EXACT same guarded code path.
        if not settings.sec_holdings_auto_refresh:
            return
        from finrobot.engine.data.sec_holdings_sync import start_refresh

        await start_refresh(app, settings, force=False)

    async def _build_data_layer_background() -> None:
        # Wire the provider chain (the ~0.5s of yfinance_provider + edgar_provider
        # imports) onto the placeholder DataLayer, off the boot critical path. It is
        # the SAME object deps already carries — add_providers extends it in place,
        # so there is no swap and shutdown/eviction keep their one handle. Routes
        # flip from 503-warming to live the instant engine_ready is set, which
        # happens right after the synchronous extend (no await between, so no caller
        # observes a half-populated chain). engine_ready flips True in ``finally``
        # REGARDLESS: a provider-build failure must not strand live-data routes on a
        # "still starting" 503 forever — with an empty chain they degrade to the
        # tested "data unavailable" path instead (never fabricated numbers).
        try:
            data_layer.add_providers(build_provider_chain(settings))
            logger.info("Data layer provider chain wired (background warmup)")
        except (OSError, ValueError, TypeError, RuntimeError, ImportError, KeyError):
            logger.exception("Data layer warmup failed — live-data routes will degrade")
        finally:
            app.state.engine_ready = True
            engine_ready_event.set()

    async def _build_agents_background() -> None:
        # Construct the LLM agents off the boot critical path (the ~0.45s
        # pydantic_ai import + the provider client). is_model_configured (not just
        # `startup_error is None`): a first-run install has no startup_error (an
        # empty model is the expected onboarding state, not an error) yet has no
        # usable model, so constructing would crash in create_model(""). Build only
        # when a model is genuinely usable; AI routes 503 with an onboarding message
        # until. ``agents_ready`` flips True in ``finally`` REGARDLESS — so a
        # provider-key failure (or no model) can never leave AI routes stuck on a
        # "still starting" 503 forever; they then fall through to the precise 503
        # (config error / no model) the request guards already emit.
        try:
            if startup_error is None and settings.is_model_configured:
                from finrobot.engine.agents.factory import create_sub_agents
                from finrobot.engine.orchestrator import create_lead_agent

                sub = create_sub_agents(settings, skill_registry=registry)
                app.state.sub_agents = sub
                app.state.agent = create_lead_agent(
                    settings, skill_registry=registry, sub_agents=sub
                )
                logger.info("LLM agents constructed (background warmup)")
            else:
                logger.warning(
                    "Skipping LLM agent construction — no usable model. The server "
                    "stays up so Settings can collect a valid API key."
                )
        except (ValueError, TypeError, RuntimeError, OSError, ImportError, KeyError):
            # A configured-but-broken model (bad key / unknown provider) raises in
            # the provider constructor. Swallow + log: the box stays up, AI routes
            # 503 (agent is still None), and a later valid Settings PUT rebuilds via
            # _replace_runtime_settings. Enumerated (no bare except) per project rule.
            logger.exception("Background agent construction failed — AI routes will 503")
        finally:
            app.state.agents_ready = True

    app.state.background_tasks = [
        asyncio.create_task(_archive_stale_background()),
        asyncio.create_task(_evict_data_cache_background()),
        asyncio.create_task(_migrate_then_warm_background()),
        asyncio.create_task(_refresh_sec_holdings_background()),
        asyncio.create_task(_warm_symbol_index_background()),
        asyncio.create_task(_build_data_layer_background()),
        asyncio.create_task(_build_agents_background()),
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
    try:
        await app.state.coverage_store.close()
    except (OSError, RuntimeError):
        logger.exception("CoverageStore shutdown error")
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


# Request-level auth: a per-launch capability token (CapabilityAuthMiddleware,
# wired below). Enforced only when the Tauri shell sets FINROBOT_CAPABILITY_TOKEN
# on the sidecar; unset in the browser dev loop and tests, where the middleware
# is a no-op. The server still binds loopback only — the token closes the
# residual local-process vector that TrustedHost + CORS cannot (see auth.py).
app = FastAPI(title="FinRobot", lifespan=lifespan)

# Host-header allowlist for TrustedHostMiddleware (BUG-004, DNS-rebinding guard).
# The desktop server only ever binds loopback (cli `serve --host` defaults to
# 127.0.0.1), so every legitimate request to the backend carries a loopback
# Host header. Rejecting anything else 400s a DNS-rebinding attack, where a
# malicious page resolves an attacker-controlled domain to 127.0.0.1 and then
# talks to this server with that domain in the Host header.
#
# NOTE: this validates the *Host* header of requests TO the backend, not the
# CORS Origin. The Vite dev server proxies UI calls to http://127.0.0.1:<port>,
# so the Host the backend sees is still a loopback name — dev is unaffected.
#
# `testserver` / `test` are the ASGI sentinels Starlette's TestClient and the
# httpx ASGITransport set as Host in-process; they are not registrable names a
# DNS-rebinding attacker could point at us, so allowing them keeps the test
# harness green without weakening the real-world guarantee (arbitrary attacker
# domains are still rejected).
_ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver", "test"]

# CORS: allow Vite dev server origin (electron dev mode uses http://localhost:5173).
# Production Electron loads from file:// so this has no effect on packaged builds.
app.add_middleware(RequestTraceMiddleware)
# Capability-token gate. Added after Trace / before CORS so the execution order
# is TrustedHost → CORS → Auth → Trace → route: CORS handles the preflight and
# decorates the 401 with CORS headers, and a rejected request never reaches
# tracing or any route. No-op unless FINROBOT_CAPABILITY_TOKEN is set (auth.py).
app.add_middleware(CapabilityAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        # Vite dev server (browser-driven development).
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        # Tauri production webview origins. Without these the shipped app
        # worked only because Tauri's webview doesn't enforce CORS at runtime —
        # a runtime coincidence, not a contract. macOS WKWebView serves the
        # bundle from tauri://localhost; Windows WebView2 uses
        # http(s)://tauri.localhost.
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)
# DNS-rebinding / Host-header validation. Added last so it runs FIRST on the
# inbound path (Starlette applies middleware in reverse add order) — a request
# with a forged Host is 400'd before it touches CORS, tracing, or any route.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=_ALLOWED_HOSTS)

app.include_router(compute_router)
app.include_router(data_router)
app.include_router(health_router)
app.include_router(settings_router)
app.include_router(runs_router)
app.include_router(artifacts_router)
app.include_router(chat_sessions_router)
app.include_router(coverage_router)
app.include_router(dashboard_router)
app.include_router(valuation_router)
app.include_router(sentiment_router)
app.include_router(sec_holdings_router)
app.include_router(search_router)


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


_LOCALE_NAMES = {"zh": "Chinese (简体中文)", "en": "English"}


def _build_runtime_instructions(
    locale: str | None,
    context_bundle: dict[str, Any] | None,
    *,
    coverage_block: str | None = None,
) -> str | None:
    """Compose per-request instructions from the UI locale + ContextBar bundle.

    Returned as a single string layered on top of the agent's static
    ``instructions.md`` via ``run_stream_native(instructions=...)``. All inputs
    are optional — back-compat clients that send none get ``None`` and the
    agent behaves exactly as before (BUG-20260602-038/048).

    ``coverage_block`` is the per-turn watchlist snapshot (the user's Studied
    Tickers projected by ``coverage.prompt.format_coverage_snapshot``). It is injected every
    turn so the assistant can answer portfolio-level questions and surface
    pre-computed movers without a tool call; absent (None) when there is no
    watchlist or its assembly failed.
    """
    lines: list[str] = []

    if locale:
        lang = _LOCALE_NAMES.get(locale, locale)
        lines.append(
            f"The user's UI locale is '{locale}'. Respond in {lang}. "
            "Financial term abbreviations and ticker symbols may stay in English."
        )

    if context_bundle:
        ctx_lines = _format_context_bundle(context_bundle)
        if ctx_lines:
            lines.append(
                "Active UI context the user is looking at (use it to ground your "
                "answer; do not invent details that are not present):\n" + ctx_lines
            )

    if coverage_block:
        lines.append(coverage_block)

    return "\n\n".join(lines) if lines else None


def _format_context_bundle(bundle: dict[str, Any]) -> str:
    """Render the ContextBar bundle into a compact, human-readable block.

    Only well-known keys are surfaced so a malformed/oversized bundle from the
    client can never blow up the prompt. Unknown keys are ignored.
    """
    parts: list[str] = []
    route = bundle.get("route")
    if isinstance(route, str) and route:
        parts.append(f"- Current view: {route}")
    ticker = bundle.get("ticker")
    if isinstance(ticker, str) and ticker:
        parts.append(f"- Focused ticker: {ticker.upper()}")
    artifact_id = bundle.get("artifact_id")
    if isinstance(artifact_id, str) and artifact_id:
        parts.append(
            f"- Open report/artifact id: {artifact_id} "
            "(the user is viewing this report; reference it when relevant)"
        )
    pinned = bundle.get("pinned")
    if isinstance(pinned, list) and pinned:
        labels: list[str] = []
        for item in pinned[:10]:
            if isinstance(item, dict):
                label = item.get("label") or item.get("id")
                kind = item.get("kind")
                if label:
                    labels.append(f"{label} ({kind})" if kind else str(label))
        if labels:
            parts.append("- Pinned context: " + "; ".join(labels))
    selected = bundle.get("selected_text")
    if isinstance(selected, str) and selected.strip():
        snippet = selected.strip()[:1000]
        parts.append(f"- User-selected text:\n  > {snippet}")
    return "\n".join(parts)


_TRANSCRIPT_WRITERS_MAX = 256


async def _get_or_create_writer(
    app_state: Any,
    session_id: str,
    model: str,
    ticker: str | None = None,
    locale: str | None = None,
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
        await writer.log_session_start(user_id="local", model=model, ticker=ticker, locale=locale)
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
    tool_state: dict[str, bool] | None = None,
) -> AsyncIterator[Any]:
    """Pass-through wrapper that mirrors pydantic_ai native events to the transcript.

    Handles:
      - ``PartEndEvent`` with ``TextPart``        → ``assistant_text``
      - ``FunctionToolCallEvent``                  → ``tool_call``
      - ``FunctionToolResultEvent``               → ``tool_result``

    Uses ``PartEndEvent`` (not ``PartStartEvent``) for text so we log the
    complete text of each part in one write instead of streaming deltas.

    ``tool_state`` (when provided) gets ``tool_executed=True`` set the moment a
    ``FunctionToolCallEvent`` is seen, so the non-streaming fallback in
    :func:`_stream_with_fallback` can refuse to re-run a turn that already
    executed a tool (matching Claude Code's no-double-exec guard).
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
            if tool_state is not None:
                tool_state["tool_executed"] = True
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


# Vercel AI data-stream frames that carry no model output of their own — the
# turn-control envelope plus the error frame. ``transform_stream`` is resilient:
# a mid-stream model/proxy failure is caught inside it and surfaces as an
# ``error`` frame wrapped in this envelope (verified empirically), never as a
# raised exception out of the chunk stream. So an "empty / failed stream" looks,
# at this layer, like a chunk stream whose frames are ALL in this set. We hold
# them back until the first frame *outside* this set (real content:
# text-* / reasoning-* / tool-input-* / tool-output-* / file) appears; if none
# ever does, we discard the envelope and emit the non-streaming fallback instead
# — so the desktop never sees a bare ``error``/empty turn when a one-shot retry
# can produce the answer. Holding the preamble keeps the happy path
# byte-for-byte (frames are replayed in order the instant content arrives).
_VERCEL_NON_CONTENT_TYPES = frozenset(
    {"start", "start-step", "finish-step", "finish", "done", "error"}
)


async def _emit_nonstreaming_fallback(
    agent: Any,
    *,
    message_history: list[Any],
    deferred_tool_results: Any,
    instructions: Any,
    deps: Any,
    encoder: Any,
    writer: TranscriptWriter,
) -> AsyncIterator[str]:
    """Run a single non-streaming ``agent.run`` and emit it as one Vercel AI message.

    Mirrors how Claude Code recovers from an empty/failed stream: re-issue the
    *same* request once in non-streaming mode and surface the whole result as a
    single assistant text message. Emits exactly the frame sequence a one-text
    streaming turn would have produced::

        start → start-step → text-start → text-delta(full text) → text-end
              → finish-step → finish → [DONE]

    so the desktop ``@ai-sdk/react`` client renders it identically. The
    transcript side-log is preserved by logging the assistant text here (the
    streaming interceptor never ran for this turn).
    """
    from pydantic_ai.ui.vercel_ai._event_stream import _FINISH_REASON_MAP
    from pydantic_ai.ui.vercel_ai.response_types import (
        DoneChunk,
        FinishChunk,
        FinishReason,
        FinishStepChunk,
        StartChunk,
        StartStepChunk,
        TextDeltaChunk,
        TextEndChunk,
        TextStartChunk,
    )

    result = await agent.run(
        message_history=message_history,
        deferred_tool_results=deferred_tool_results,
        deps=deps,
        instructions=instructions,
    )
    text = str(result.output)

    # Side-log the assistant text so the fallback path keeps an audit trail —
    # the native-event interceptor (_intercept_native_events) never saw output.
    try:
        await writer.log_assistant_text(text)
    except OSError:
        logger.exception("TranscriptWriter: failed to log assistant_text (fallback)")

    # Map the pydantic_ai finish reason to the Vercel AI vocabulary, reusing the
    # adapter's own map (mirrors VercelAIEventStream.handle_run_result). Unknown
    # → 'other'; absent → 'stop' (a clean non-streaming turn that finished).
    pydantic_reason = result.response.finish_reason
    finish_reason: FinishReason = (
        _FINISH_REASON_MAP.get(pydantic_reason, "other") if pydantic_reason else "stop"
    )

    message_id = uuid.uuid4().hex
    chunks: list[Any] = [
        StartChunk(),
        StartStepChunk(),
        TextStartChunk(id=message_id),
    ]
    if text:
        chunks.append(TextDeltaChunk(id=message_id, delta=text))
    chunks.extend(
        [
            TextEndChunk(id=message_id),
            FinishStepChunk(),
            FinishChunk(finish_reason=finish_reason),
            DoneChunk(),
        ]
    )
    for chunk in chunks:
        yield encoder.encode_event(chunk)


async def _stream_with_fallback(
    *,
    event_stream: AsyncIterator[Any],
    encoder: Any,
    agent: Any,
    message_history: list[Any],
    deferred_tool_results: Any,
    instructions: Any,
    deps: Any,
    writer: TranscriptWriter,
    tool_state: dict[str, bool],
) -> AsyncIterator[str]:
    """Encode the streaming turn, with a one-shot non-streaming fallback.

    Faithful to Claude Code's single fallback: try streaming first; if the
    stream fails mid-flight OR ends without producing any usable content, and
    no tool has executed yet this turn, re-issue the same request once in
    non-streaming mode and emit the whole result as one message.

    Implementation: hold back every non-content envelope frame
    (``_VERCEL_NON_CONTENT_TYPES`` — start/start-step/finish*/done/error) until
    the first *content* frame appears. While only envelope frames have arrived
    nothing meaningful has reached the client, so an empty/failed turn (whose
    chunk stream is entirely envelope, ending in ``error`` or just ``finish``)
    can be cleanly discarded and replaced by the fallback. The instant a content
    frame arrives we commit — replay the held envelope in order, then stream the
    rest live (happy path byte-for-byte). Once committed (or once a tool ran) we
    never fall back, matching CC's guard against double-rendering / re-executing
    tools.
    """
    held: list[Any] = []
    committed = False

    def _tool_ran() -> bool:
        return tool_state.get("tool_executed", False)

    async def _fallback() -> AsyncIterator[str]:
        async for encoded in _emit_nonstreaming_fallback(
            agent,
            message_history=message_history,
            deferred_tool_results=deferred_tool_results,
            instructions=instructions,
            deps=deps,
            encoder=encoder,
            writer=writer,
        ):
            yield encoded

    # No try/except around the loop: VercelAIEventStream.transform_stream is
    # contractually resilient — it catches the model/proxy failure internally
    # and surfaces it as an ``error`` frame inside the control envelope (verified
    # empirically), so the chunk stream never raises out here. A failed turn is
    # therefore detected exactly like an empty one: the envelope ends without any
    # content frame. (A bare ``except Exception`` is also banned in finrobot/.)
    async for chunk in event_stream:
        if committed:
            yield encoder.encode_event(chunk)
            continue

        if getattr(chunk, "type", None) in _VERCEL_NON_CONTENT_TYPES:
            # Buffer the envelope; replayed in order the instant content arrives,
            # so the happy path stays byte-for-byte. An error frame lands here
            # too — held, not forwarded — so a failed turn can be swapped for the
            # fallback rather than shown to the user as an error.
            held.append(chunk)
            continue

        # First content frame. Commit to the streaming turn: flush the held
        # envelope, then this frame, then stream the remainder live.
        committed = True
        for held_chunk in held:
            yield encoder.encode_event(held_chunk)
        held.clear()
        yield encoder.encode_event(chunk)

    if committed:
        # Stream produced usable content and ended cleanly — nothing to do.
        return

    # No content frame ever arrived: the turn is empty or errored. Fall back
    # unless a tool executed this turn (CC guard against re-running tools).
    if _tool_ran():
        # A tool ran but the model emitted no text — replay the held envelope so
        # the client still sees a well-formed, terminated stream. No fallback.
        for held_chunk in held:
            yield encoder.encode_event(held_chunk)
        return

    logger.warning("Chat stream produced no output; using non-streaming fallback")
    async for encoded in _fallback():
        yield encoded


async def _build_coverage_snapshot_block(request: Request) -> str | None:
    """Assemble the per-turn watchlist snapshot for the chat system context.

    Reads the user's system ``Studied Tickers`` group and projects it through
    ``build_overview(cache_only=True)`` — the instant, network-free first paint
    (local SQLite, ~ms at any N), so injecting it never adds chat latency or
    fires a provider call. The block carries deterministically pre-computed
    movers (see :func:`finrobot.coverage.prompt.format_coverage_snapshot`).

    Best-effort by contract: the entire path is guarded so a missing store /
    absent group / empty membership / assembly error yields ``None`` and the
    conversation proceeds with no watchlist context (back-compat). It never
    raises into the chat handler.
    """
    state = request.app.state
    coverage_store: CoverageStore | None = getattr(state, "coverage_store", None)
    deps: FinRobotDeps | None = getattr(state, "deps", None)
    run_store = getattr(state, "run_store", None)
    # deps carries the only typed handles we need (data_layer, settings); guarding
    # on it (not a getattr-derived Any) is what lets the settings read below stay
    # type-safe. artifact_store comes off deps too, falling back to app.state for
    # the test harnesses that set it there without a full deps.
    if coverage_store is None or deps is None:
        return None
    artifact_store = deps.artifact_store or getattr(state, "artifact_store", None)
    if artifact_store is None:
        return None
    try:
        group = await coverage_store.get_system_group()
        if group is None or not group.members:
            return None
        overview = await build_overview(
            group,
            artifact_store=artifact_store,
            data_layer=deps.data_layer,
            run_store=run_store,
            cache_only=True,
        )
        threshold = deps.settings.coverage_anomaly_change_threshold
        return format_coverage_snapshot(overview, change_threshold=threshold)
    except _COVERAGE_SNAPSHOT_DEGRADABLE:
        # Watchlist context is a pure augmentation — never let its assembly
        # break a chat turn. Logged at INFO (not exception) because a cold /
        # absent Coverage Desk is an ordinary state, not an error to page on.
        # We enumerate the concrete failure modes rather than bare-excepting
        # (project convention, mirroring dashboard._QUOTE_BATCH_DEGRADABLE):
        # build_overview already degrades per-row, so what reaches here is a
        # store/db/loop-level fault, not a per-ticker fetch miss.
        logger.info("Coverage snapshot for chat context unavailable", exc_info=True)
        return None


async def _chat_impl(
    request: Request,
    body_json: dict[str, Any],
    session_id: str,
    model: str,
    ticker: str | None = None,
    locale: str | None = None,
    context_bundle: dict[str, Any] | None = None,
) -> Response:
    # Log the user's latest message before streaming begins.
    writer = await _get_or_create_writer(
        request.app.state, session_id, model, ticker=ticker, locale=locale
    )

    # Record the ContextBar bundle for this turn so the audit trail shows the
    # exact extra context the model received (BUG-20260602-038).
    if context_bundle:
        try:
            await writer.log_context(context_bundle)
        except OSError:
            logger.exception("TranscriptWriter: failed to log context for session %s", session_id)

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
    # Lazy import: VercelAIAdapter drags in the pydantic_ai stack (~0.45s); kept
    # off the sidecar cold-start import path (tests/unit/test_cold_import.py).
    from pydantic_ai.ui.vercel_ai import VercelAIAdapter

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

    # Per-turn watchlist snapshot: the user's Studied Tickers + deterministically
    # pre-computed movers, injected into the system context so the assistant is
    # watchlist-aware without a tool call. Fully best-effort — any failure (no
    # coverage store, no system group, assembly error) leaves coverage_block None
    # and the conversation proceeds exactly as before (back-compat).
    coverage_block = await _build_coverage_snapshot_block(request)
    # Per-request instructions layered on top of instructions.md: UI locale +
    # ContextBar bundle + watchlist snapshot. None when none apply (back-compat).
    runtime_instructions = _build_runtime_instructions(
        locale, context_bundle, coverage_block=coverage_block
    )
    # Per-request deps copy carrying the UI locale so the orchestrator's pipeline
    # tool generates the report body in the user's language (shallow replace —
    # shares data_layer / semaphore / settings, mutates nothing). None locale →
    # request_locale stays None → pipeline falls back to settings.language.
    request_deps = replace(request.app.state.deps, request_locale=locale)
    native_stream = adapter.run_stream_native(
        deps=request_deps,
        instructions=runtime_instructions,
    )
    # tool_state lets the interceptor flag mid-stream tool execution; the
    # fallback consults it to honour CC's no-double-exec guard.
    tool_state: dict[str, bool] = {}
    instrumented_stream = _intercept_native_events(native_stream, writer, tool_state)
    event_stream = adapter.transform_stream(instrumented_stream)

    # Non-streaming fallback (matches Claude Code): if the stream above fails
    # before any output or yields nothing usable — and no tool ran — re-issue
    # the SAME request once via agent.run and emit it as a single message.
    # run_stream_native prepends adapter.messages and adds deferred results /
    # the frontend toolset; we mirror that here so the fallback run is identical
    # to the streamed one. Vercel's adapter exposes no frontend toolset and
    # FinRobotDeps is not a StateHandler, so messages + deferred results are the
    # only adapter-derived inputs. If that ever changes upstream, the fallback
    # re-issue would silently drop the toolset — so we degrade to streaming
    # WITHOUT the one-shot fallback instead. (This was an `assert`, which 500'd
    # the whole chat turn in production and vanished entirely under `python
    # -O`; a missing fallback is a far smaller loss than a dead chat.)
    if adapter.toolset is not None:
        logger.warning(
            "Frontend toolset present on adapter — streaming without the "
            "non-streaming fallback (fallback cannot re-run a toolset turn)"
        )
        plain_encoder = adapter.build_event_stream()

        async def _encode_plain() -> AsyncIterator[str]:
            async for chunk in event_stream:
                yield plain_encoder.encode_event(chunk)

        return StreamingResponse(
            _encode_plain(),
            headers=plain_encoder.response_headers,
            media_type=plain_encoder.content_type,
        )
    fallback_history = list(adapter.messages)
    fallback_deferred = adapter.deferred_tool_results
    # One encoder instance for both held happy-path frames and fallback frames;
    # it is stateless w.r.t. the transform_stream encoder (just chunk.encode).
    encoder = adapter.build_event_stream()
    encoded_stream = _stream_with_fallback(
        event_stream=event_stream,
        encoder=encoder,
        agent=request.app.state.agent,
        message_history=fallback_history,
        deferred_tool_results=fallback_deferred,
        instructions=runtime_instructions,
        deps=request_deps,
        writer=writer,
        tool_state=tool_state,
    )
    return StreamingResponse(
        encoded_stream,
        headers=encoder.response_headers,
        media_type=encoder.content_type,
    )


@app.post("/chat")
async def chat(request: Request) -> Response:
    """Handle a Vercel AI SDK chat request with transcript side-logging.

    The transcript hook intercepts native pydantic_ai stream events to write
    user messages, assistant text, tool calls, and tool results to a per-session
    JSONL file at ``~/.finrobot-desktop/sessions/<session_id>.jsonl``.

    Transcript write failures are logged and never surface to the client —
    the Vercel AI stream is unaffected by transcript I/O errors.
    """
    # Fail-fast on broken runtime config. lifespan stashes the validation
    # error on app.state.startup_error (missing API key / bad provider) and
    # the SettingsView promises "LLM 路由将在配置修复前返回 503". Honour that
    # contract HERE — before opening a session/stream — so a misconfigured
    # box gets a clean 503 instead of entering the SSE stream and erroring
    # deep in the pipeline with a buried OpenAIError (BUG-20260602-056).
    startup_error = getattr(request.app.state, "startup_error", None)
    if startup_error:
        return JSONResponse(
            content={"detail": f"Server not ready: {startup_error}"},
            status_code=503,
        )
    # First-run guard: empty model_name is onboarding, not a startup_error, so
    # it slips past the check above — but app.state.agent is None. Honour the
    # same 503 contract with an actionable message instead of a buried crash.
    if not request.app.state.deps.settings.is_model_configured:
        return JSONResponse(
            content={"detail": "No AI model configured. Choose one in Settings → AI Model."},
            status_code=503,
        )
    # Cold-start warming guard: agents are built in a post-yield background task
    # (lifespan _build_agents_background), so a configured model can still have
    # app.state.agent is None for a beat after boot. Distinguish "still starting"
    # (retry) from "started but construction failed" (actionable) — either way we
    # must NOT let _chat_impl dereference a None agent. agents_ready defaults True
    # for test harnesses that set app.state.agent directly without a lifespan.
    if request.app.state.agent is None:
        if not getattr(request.app.state, "agents_ready", True):
            return JSONResponse(
                content={"detail": "AI engine is still starting — retry in a moment."},
                status_code=503,
            )
        return JSONResponse(
            content={
                "detail": "AI engine unavailable — re-check your model / API key in Settings."
            },
            status_code=503,
        )

    # Inbound rate-limit guard (BUG-043): each chat opens a metered LLM stream.
    # Defense-in-depth against runaway loops / retry storms hammering /chat — a
    # 429 here only fires under abnormal volume, never a normal human session.
    limiter = getattr(request.app.state, "run_rate_limiter", None)
    if limiter is not None and not limiter.allow_chat():
        return JSONResponse(
            content={"detail": "Rate limit exceeded — too many chat requests. Retry shortly."},
            status_code=429,
        )

    body = await request.body()
    try:
        body_json: dict[str, Any] = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        body_json = {}

    session_id: str = body_json.get("id") or body_json.get("session_id") or "default"
    # session_id becomes the stem of <sessions>/<session_id>.jsonl, so a
    # body-supplied "../.." would write attacker-controlled JSONL outside the
    # sessions dir (path traversal, BUG-089). Close the identifier off at the
    # edge: an illegal one falls back to the shared 'default' session rather
    # than 500-ing the chat. Defense-in-depth resolve() containment in the
    # writer/reader is the second line.
    if not is_valid_session_id(session_id):
        logger.warning("Rejected unsafe chat session_id %r — falling back to 'default'", session_id)
        session_id = "default"
    # Record the model the user actually selected in Settings — the same value
    # app.state.agent runs and the read-only chat badge shows — read from the
    # authoritative runtime settings, NOT the client's `model` field. The client
    # echo raced the /api/settings fetch and stamped a bogus "unknown" into the
    # audit trail before settings loaded. Traceability must reflect the real
    # model, never a client guess; _replace_runtime_settings keeps deps.settings
    # and the agent in lockstep, so this never drifts from what actually ran.
    model = request.app.state.deps.settings.model_name

    # Optional context fields — older clients omit these and the chat behaves
    # exactly as before (BUG-20260602-038/048).
    raw_ticker = body_json.get("ticker")
    ticker: str | None = str(raw_ticker) if raw_ticker else None
    raw_locale = body_json.get("locale")
    locale: str | None = str(raw_locale) if raw_locale else None
    raw_bundle = body_json.get("context_bundle")
    context_bundle: dict[str, Any] | None = raw_bundle if isinstance(raw_bundle, dict) else None
    # The context bundle is the authoritative ticker if present.
    if context_bundle and isinstance(context_bundle.get("ticker"), str):
        ticker = context_bundle["ticker"] or ticker

    with bind_session(session_id):
        return await _chat_impl(
            request,
            body_json,
            session_id,
            model,
            ticker=ticker,
            locale=locale,
            context_bundle=context_bundle,
        )


@app.get("/health")
async def health(request: Request) -> dict[str, Any]:
    """Readiness probe for the Tauri shell's sidecar poll.

    Stays auth-exempt (see ``finrobot.auth._EXEMPT_PATHS``) because the shell
    polls it before the WebView — and hence the token — exists. It echoes the
    per-launch capability token back so the readiness loop can prove the
    backend answering on :8321 is *its own* spawned child, not a stale or
    foreign process squatting the port. The probe does not require the caller
    to present the token; this is an identity stamp, not an auth gate.

    When no token is configured (browser dev loop, live-backend posture,
    tests) the ``token`` field is omitted, keeping the response backward
    compatible with callers that only read ``status``.

    ``status`` is ``starting`` until the post-yield warmup wires the data layer
    (``engine_ready``) — but the response is ALWAYS HTTP 200, so sidecar.rs (which
    checks 200 + token, never the status string) shows the WebView immediately and
    the frontend polls ``engine_ready`` / ``agents_ready`` to gate live-data and AI
    UI. Both default True when unset (test harnesses without a lifespan), matching
    routes/_ready.py, so the legacy ``status: ready`` contract holds for them.
    """
    state = request.app.state
    engine_ready = bool(getattr(state, "engine_ready", True))
    agents_ready = bool(getattr(state, "agents_ready", True))
    body: dict[str, Any] = {
        "status": "ready" if engine_ready else "starting",
        "engine_ready": engine_ready,
        "agents_ready": agents_ready,
    }
    token = get_capability_token()
    if token:
        body["token"] = token
    return body
