"""FinAgent web UI — FastAPI router serving Jinja2 templates + task API.

What this code does that raw LLM cannot: provides an HTTP interface for
launching, monitoring, and reviewing financial analysis pipelines through
a browser. Manages task lifecycle, serves templated HTML pages, and
bridges the web layer to the existing pipeline infrastructure.
"""

from __future__ import annotations

import asyncio
import functools
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from finagent.web.tasks import (
    _MAX_RUNNING,
    create_task,
    get_task,
    list_tasks,
    register_async_task,
    run_task,
    running_count,
)

_TEMPLATE_DIR = Path(__file__).parent / "templates"

VALID_PIPELINES = frozenset(
    {"research", "comps", "dcf", "lbo", "earnings", "ic-memo"}
)

web_router = APIRouter()


@functools.lru_cache(maxsize=1)
def _get_web_env() -> Any:
    """Lazily create and cache the Jinja2 environment for web templates."""
    from jinja2 import Environment, FileSystemLoader

    return Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True)


def _render_template(name: str, **context: Any) -> str:
    """Render a Jinja2 template from the web templates directory."""
    result: str = _get_web_env().get_template(name).render(**context)
    return result


# ── HTML Pages ──────────────────────────────────────────────────────────


@web_router.get("/web/", response_class=HTMLResponse)
async def index_page() -> HTMLResponse:
    html = _render_template("index.html")
    return HTMLResponse(content=html)


@web_router.get("/web/reports", response_class=HTMLResponse)
async def reports_page() -> HTMLResponse:
    html = _render_template("reports.html")
    return HTMLResponse(content=html)


@web_router.get("/web/report/{task_id}", response_class=HTMLResponse)
async def report_view_page(task_id: str) -> HTMLResponse:
    task = get_task(task_id)
    if task is None:
        return HTMLResponse("<h1>Task not found</h1>", status_code=404)
    report_url = task.report_url or f"/api/report/html?ticker={task.ticker}"
    if not report_url.startswith("/"):
        report_url = "#"  # Reject non-relative paths
    html = _render_template(
        "report_view.html",
        ticker=task.ticker,
        pipeline_type=task.pipeline_type,
        report_url=report_url,
    )
    return HTMLResponse(content=html)


# ── Task API ────────────────────────────────────────────────────────────


class RunRequest(BaseModel):
    ticker: str
    pipeline_type: str


@web_router.post("/api/web/run")
async def run_pipeline(body: RunRequest, request: Request) -> JSONResponse:
    ticker = body.ticker.strip().upper()
    if not ticker:
        return JSONResponse(
            status_code=422, content={"detail": "ticker is required"}
        )
    if body.pipeline_type not in VALID_PIPELINES:
        return JSONResponse(
            status_code=400,
            content={
                "detail": (
                    f"Invalid pipeline_type: {body.pipeline_type}. "
                    f"Valid: {sorted(VALID_PIPELINES)}"
                )
            },
        )

    if running_count() >= _MAX_RUNNING:
        return JSONResponse(
            {"error": f"Too many running tasks (max {_MAX_RUNNING}). Try again later."},
            status_code=429,
        )

    task = create_task(ticker, body.pipeline_type)
    # Fire-and-forget: run the pipeline in the background.
    # Fix 4.3: store the asyncio.Task so eviction can cancel it.
    bg = asyncio.create_task(run_task(task, request.app.state))
    register_async_task(task.task_id, bg)
    return JSONResponse(
        status_code=201,
        content={"task_id": task.task_id, "status": task.status},
    )


@web_router.get("/api/web/status/{task_id}")
async def task_status(task_id: str) -> JSONResponse:
    task = get_task(task_id)
    if task is None:
        return JSONResponse(
            status_code=404, content={"detail": "Task not found"}
        )
    return JSONResponse(content=task.model_dump())


@web_router.get("/api/web/history")
async def task_history() -> JSONResponse:
    tasks = list_tasks()
    return JSONResponse(content=[t.model_dump() for t in tasks])


__all__ = ["web_router"]
