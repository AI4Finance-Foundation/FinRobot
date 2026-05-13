import asyncio
import json
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
from finagent.routes.artifacts import router as artifacts_router
from finagent.routes.ask import router as ask_router
from finagent.routes.compute import router as compute_router
from finagent.routes.data import router as data_router
from finagent.routes.export import router as export_router
from finagent.routes.runs import router as runs_router
from finagent.routes.settings import load_non_secret_settings
from finagent.routes.settings import router as settings_router
from finagent.run_store import RunStore
from finagent.secret_store import SecretStore, create_secret_store
from finagent.web import web_router


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
app.include_router(ask_router)
app.include_router(compute_router)
app.include_router(data_router)
app.include_router(export_router)
app.include_router(settings_router)
app.include_router(runs_router)
app.include_router(artifacts_router)


@app.post("/chat")
async def chat(request: Request) -> Response:
    return await VercelAIAdapter.dispatch_request(
        request, agent=request.app.state.agent, deps=request.app.state.deps
    )


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
