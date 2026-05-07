import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from pydantic_ai.ui.vercel_ai import VercelAIAdapter

from finagent.config import get_settings
from finagent.engine.data.cache import DataCache
from finagent.engine.data.interface import ProviderError
from finagent.engine.data.layer import DataLayer
from finagent.engine.deps import FinAgentDeps
from finagent.engine.orchestrator import build_report_context, create_lead_agent
from finagent.engine.skills.registry import SkillRegistry
from finagent.web import web_router


# Fix 4.4: Pipeline factories moved to registry module to break
# circular import (server → web → tasks → server).
from finagent.engine.pipelines.registry import get_pipeline_factories


def _get_pipeline_factories() -> dict[str, Callable[..., Any]]:
    """Thin wrapper kept for backwards compatibility."""
    return get_pipeline_factories()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()

    # Load skills if available
    skills_path = Path(settings.skills_dir)
    registry = SkillRegistry(skills_path) if skills_path.exists() else None

    # Build provider chain: FMP (if key) → Finnhub (if key) → yfinance (always) + SEC EDGAR
    from finagent.engine.data.providers.yfinance_provider import YFinanceProvider
    from finagent.engine.data.providers.sec_provider import SECEdgarProvider

    providers: list[Any] = []
    if settings.fmp_api_key:
        from finagent.engine.data.providers.fmp_provider import FMPProvider

        providers.append(FMPProvider(api_key=settings.fmp_api_key))
    if settings.finnhub_api_key:
        from finagent.engine.data.providers.finnhub_provider import FinnhubProvider

        providers.append(FinnhubProvider(api_key=settings.finnhub_api_key))
    providers.append(YFinanceProvider())
    providers.append(SECEdgarProvider(user_agent=settings.sec_user_agent))

    cache = DataCache(settings.cache_db_path)
    data_layer = DataLayer(providers=providers, cache=cache)

    # Create agent
    agent = create_lead_agent(settings, skill_registry=registry)
    deps = FinAgentDeps(data_layer=data_layer, settings=settings, skill_runtime=registry)

    from finagent.engine.agents.factory import create_sub_agents

    app.state.agent = agent
    app.state.deps = deps
    app.state.sub_agents = create_sub_agents(
        deps.settings, skill_registry=deps.skill_runtime
    )
    yield
    await cache.close()


# WARNING: This server has no authentication. For local development only.
# Do not expose to public network without adding auth middleware.
app = FastAPI(title="FinAgent", lifespan=lifespan)
app.include_router(web_router)


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
    return {"status": "ready", "phase": "P3"}


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
