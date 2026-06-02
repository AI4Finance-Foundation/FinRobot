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


# ---------------------------------------------------------------------------
# BUG-034/043 — completion events must carry the artifact's real id + type so
# the UI opens THIS run's product, not the ticker's latest equity_research.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_completion_emits_artifact_id_and_type(monkeypatch: Any) -> None:
    """_run_pipeline_impl emits artifact.ready + run.completed carrying the
    persisted artifact's id AND its real type (resolved from artifact_store),
    not the opaque "artifact" placeholder."""
    from finrobot.engine.pipelines.base import PipelineResult
    from finrobot.routes import runs as runs_mod

    # Fake pipeline: 1 step, execute() returns a result with an artifact_id.
    pipeline = MagicMock()
    pipeline.steps = [MagicMock()]
    result = PipelineResult(steps={"report": "done"}, structured_data={})
    result.artifact_id = "art_2026-06-02_AAPL_lbo"
    pipeline.execute = AsyncMock(return_value=result)
    pipeline.format_summary = MagicMock(return_value="summary")

    monkeypatch.setattr(runs_mod, "get_pipeline_factories", lambda: {"lbo": lambda agents: pipeline})

    record = _make_run_record(status="created")
    record.pipeline_type = "lbo"
    record.language = None
    record.source_artifact_id = None

    store = AsyncMock()
    store.get_run = AsyncMock(return_value=record)
    appended: list[dict[str, Any]] = []

    async def _capture(run_id: str, event: dict[str, Any]) -> int:
        appended.append(event)
        return len(appended)

    store.append_event = AsyncMock(side_effect=_capture)

    # Artifact store resolves the real type for the persisted id.
    artifact = MagicMock()
    artifact.type = "lbo"
    artifact_store = AsyncMock()
    artifact_store.get = AsyncMock(return_value=artifact)

    request = MagicMock()
    request.app.state.run_store = store
    request.app.state.run_semaphore = None
    request.app.state.artifact_store = artifact_store
    request.app.state.run_tasks = {}
    request.app.state.sub_agents = {}
    request.app.state.deps = MagicMock()

    await runs_mod._run_pipeline(record.run_id, request)

    ready = next(e for e in appended if e["event"] == "artifact.ready")
    assert ready["artifact_id"] == "art_2026-06-02_AAPL_lbo"
    assert ready["artifact_type"] == "lbo"

    completed = next(e for e in appended if e["event"] == "run.completed")
    assert completed["artifact_id"] == "art_2026-06-02_AAPL_lbo"
    assert completed["artifact_type"] == "lbo"
    assert completed["result_url"] == "/api/artifacts/art_2026-06-02_AAPL_lbo"

    # The persisted run-store artifact row also records the real type.
    add_call = store.add_artifact.await_args
    assert add_call.kwargs["artifact_type"] == "lbo"
