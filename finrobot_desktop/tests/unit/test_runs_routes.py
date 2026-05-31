"""Unit tests for finrobot/routes/runs.py bug fixes.

B3 — get_run non-dict result_json defence
B3 — create_run task-registration ordering
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from finrobot.routes.runs import router as runs_router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(run_record: Any | None = None) -> FastAPI:
    """Minimal FastAPI app wired with the runs router and a mock RunStore."""
    app = FastAPI()
    app.include_router(runs_router)

    store = AsyncMock()
    if run_record is not None:
        store.get_run = AsyncMock(return_value=run_record)
    else:
        store.get_run = AsyncMock(return_value=None)
    store.list_artifacts = AsyncMock(return_value=[])

    app.state.run_store = store
    app.state.run_tasks = {}
    app.state.sub_agents = {}
    return app


def _make_run_record(
    *,
    result_json: Any = None,
    result_text: str | None = None,
    status: str = "completed",
) -> MagicMock:
    record = MagicMock()
    record.run_id = "run-abc"
    record.status = status
    record.pipeline_type = "full_analysis"
    record.ticker = "AAPL"
    record.created_at = "2026-01-01T00:00:00+00:00"
    record.completed_at = "2026-01-01T00:01:00+00:00"
    record.duration_s = 60.0
    record.result_json = result_json
    record.result_text = result_text
    record.error = None
    return record


# ---------------------------------------------------------------------------
# B3 — get_run: non-dict result_json must not raise AttributeError → 500
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_run_with_dict_result_json() -> None:
    """Normal path: result_json is a dict → fields extracted correctly."""
    record = _make_run_record(
        result_json={
            "structured_data": {"summary": "ok"},
            "steps": {"step1": "done"},
            "failed_validations": [],
            "warnings": ["minor"],
        },
        result_text="summary text",
    )
    app = _make_app(record)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/runs/run-abc")

    assert resp.status_code == 200
    body = resp.json()
    assert body["warnings"] == ["minor"]
    assert body["steps"] == {"step1": "done"}
    assert body["result"]["text"] == "summary text"


@pytest.mark.asyncio
async def test_get_run_with_list_result_json_does_not_crash() -> None:
    """result_json is a list (corrupt/legacy data) — must return 200 with empty fields."""
    record = _make_run_record(result_json=["stale", "data"])
    app = _make_app(record)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/runs/run-abc")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Non-dict result_json must be treated as absent.
    assert body["warnings"] == []
    assert body["failed_validations"] == []
    assert body["steps"] is None
    assert body["result"] is None


@pytest.mark.asyncio
async def test_get_run_with_string_result_json_does_not_crash() -> None:
    """result_json is a string (e.g. serialised from an old write path) — no 500."""
    record = _make_run_record(result_json="bad payload")
    app = _make_app(record)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/runs/run-abc")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["warnings"] == []
    assert body["steps"] is None


@pytest.mark.asyncio
async def test_get_run_with_none_result_json() -> None:
    """result_json is None (run still running) — works as before."""
    record = _make_run_record(result_json=None, status="running")
    app = _make_app(record)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/runs/run-abc")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    assert body["result"] is None


@pytest.mark.asyncio
async def test_get_run_404_when_not_found() -> None:
    """Non-existent run_id returns 404."""
    app = _make_app(run_record=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/runs/does-not-exist")
    assert resp.status_code == 404
