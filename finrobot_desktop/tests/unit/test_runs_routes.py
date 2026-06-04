"""Unit tests for finrobot/routes/runs.py bug fixes.

B3 — get_run non-dict result_json defence
B3 — create_run task-registration ordering
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from finrobot.routes.runs import router as runs_router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(run_record: Any | None = None, *, startup_error: str | None = None) -> FastAPI:
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
    app.state.startup_error = startup_error
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
# BUG-20260602-056 — POST /api/runs must 503 (not create an orphan run) when
# app.state.startup_error is set (broken runtime config / missing LLM key).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_run_503_when_startup_error_set() -> None:
    """A misconfigured server (startup_error set) returns 503 from POST /api/runs."""
    app = _make_app(startup_error="ANTHROPIC_API_KEY is required but not set")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/runs", json={"pipeline_type": "full_analysis", "ticker": "AAPL"})

    assert resp.status_code == 503, resp.text
    assert "ANTHROPIC_API_KEY" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_create_run_with_startup_error_creates_no_run_record() -> None:
    """The 503 gate fires BEFORE create_run, so no orphan run row is persisted
    and no pipeline task is spawned."""
    app = _make_app(startup_error="bad config")
    store = app.state.run_store
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/runs", json={"pipeline_type": "full_analysis", "ticker": "AAPL"})

    assert resp.status_code == 503
    store.create_run.assert_not_awaited()
    assert app.state.run_tasks == {}


@pytest.mark.asyncio
async def test_create_run_succeeds_when_no_startup_error(monkeypatch: Any) -> None:
    """Sanity counter-test: with startup_error=None the run is created (no 503)."""
    from finrobot.routes import runs as runs_mod

    monkeypatch.setattr(
        runs_mod, "get_pipeline_factories", lambda: {"full_analysis": lambda agents: MagicMock()}
    )

    # Stop the spawned task from actually running the pipeline impl.
    def _fake_create_task(coro: Any) -> Any:
        coro.close()  # avoid "coroutine was never awaited" warning
        return MagicMock()

    monkeypatch.setattr(runs_mod.asyncio, "create_task", _fake_create_task)

    record = _make_run_record(status="created")
    app = _make_app(startup_error=None)
    app.state.run_store.create_run = AsyncMock(return_value=record)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/runs", json={"pipeline_type": "full_analysis", "ticker": "AAPL"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "created"


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

    monkeypatch.setattr(
        runs_mod, "get_pipeline_factories", lambda: {"lbo": lambda agents: pipeline}
    )

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


# ---------------------------------------------------------------------------
# BUG-031 — aggregated SSE: one /api/runs/events?ids=… stream multiplexes many
# runs (instead of one EventSource per run saturating the HTTP/1.1 pool).
# ---------------------------------------------------------------------------


def _parse_sse(raw: str) -> list[dict[str, str]]:
    """Split an SSE response body into {id, event, data} frame dicts."""
    frames: list[dict[str, str]] = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        frame: dict[str, str] = {}
        for line in block.splitlines():
            field, _, value = line.partition(": ")
            frame[field] = value
        frames.append(frame)
    return frames


async def _seed_completed_run(store: Any, ticker: str) -> str:
    """Create a run, append a run.started + run.completed, mark it completed."""
    from finrobot.events import RunCompleted, RunStarted

    record = await store.create_run("research", ticker)
    run_id = record.run_id
    await store.append_event(
        run_id,
        RunStarted(
            event="run.started",
            run_id=run_id,
            pipeline_type="research",
            ticker=ticker,
            total_steps=1,
        ),
    )
    await store.append_event(
        run_id,
        RunCompleted(
            event="run.completed",
            run_id=run_id,
            ticker=ticker,
            duration_s=1.0,
            result_url=f"/api/runs/{run_id}",
        ),
    )
    await store.update_run(run_id, status="completed", completed_at="2026-06-04T00:00:00+00:00")
    return run_id


def _make_app_with_store(store: Any) -> FastAPI:
    app = FastAPI()
    app.include_router(runs_router)
    app.state.run_store = store
    app.state.run_tasks = {}
    app.state.sub_agents = {}
    app.state.startup_error = None
    return app


@pytest.mark.asyncio
async def test_aggregated_stream_multiplexes_and_tags_runs(tmp_path: Any) -> None:
    """Two terminal runs over ONE stream: every frame is tagged with its
    run_id + ticker, and the stream closes once both are terminal."""
    from finrobot.run_store import RunStore

    store = RunStore(tmp_path / "runs.db")
    rid_a = await _seed_completed_run(store, "AAPL")
    rid_b = await _seed_completed_run(store, "MSFT")
    app = _make_app_with_store(store)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(f"/api/runs/events?ids={rid_a},{rid_b}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    frames = _parse_sse(resp.text)
    # Each run emits run.started + run.completed = 4 frames total.
    completed = [f for f in frames if f["event"] == "run.completed"]
    assert len(completed) == 2
    # Every frame carries its routing keys, and id: is a per-id cursor snapshot.
    tickers_seen = set()
    for f in frames:
        payload = json.loads(f["data"])
        assert payload["run_id"] in {rid_a, rid_b}
        assert ":" in f["id"]  # multiplex cursor, e.g. "run_x:1,run_y:2"
        tickers_seen.add(payload["ticker"])
    assert tickers_seen == {"AAPL", "MSFT"}


@pytest.mark.asyncio
async def test_aggregated_stream_resumes_from_last_event_id(tmp_path: Any) -> None:
    """Last-Event-ID with a per-id cursor at the final seq skips already-seen
    events for that run (resume parity with the single-run stream)."""
    from finrobot.run_store import RunStore

    store = RunStore(tmp_path / "runs.db")
    rid_a = await _seed_completed_run(store, "AAPL")
    rid_b = await _seed_completed_run(store, "MSFT")
    app = _make_app_with_store(store)

    # rid_a has 2 events (seq 1,2). Resume past both → only rid_b's events stream.
    header = {"Last-Event-ID": f"{rid_a}:2,{rid_b}:0"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(f"/api/runs/events?ids={rid_a},{rid_b}", headers=header)
    assert resp.status_code == 200

    run_ids = {json.loads(f["data"])["run_id"] for f in _parse_sse(resp.text)}
    assert run_ids == {rid_b}  # rid_a fully resumed-past, only rid_b streams


@pytest.mark.asyncio
async def test_aggregated_stream_400_when_no_ids() -> None:
    app = _make_app(_make_run_record())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/runs/events?ids=")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_aggregated_stream_404_when_all_ids_unknown() -> None:
    app = _make_app(None)  # store.get_run returns None for any id
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/runs/events?ids=nope-1,nope-2")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# BUG-034 — the terminal status flip must NOT become visible to readers before
# the terminal event (run.completed / run.failed) is in run_events. Otherwise
# the SSE poll loop can observe a terminal status, fetch trailing events that
# don't yet contain the terminal event, and break without ever emitting it.
# The fix appends the terminal event BEFORE update_run(status=terminal), so the
# invariant "status terminal ⇒ terminal event already exists" always holds.
# ---------------------------------------------------------------------------


class _OrderRecordingStore:
    """Wraps a real RunStore and records the order in which the terminal status
    flip and the terminal event append happen, so a test can assert the event
    was committed BEFORE the status became terminal (the BUG-034 invariant)."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.order: list[str] = []

    async def append_event(self, run_id: str, event: Any) -> int:
        ev = event.get("event") if isinstance(event, dict) else getattr(event, "event", None)
        if ev in {"run.completed", "run.failed"}:
            self.order.append(f"event:{ev}")
        return await self._inner.append_event(run_id, event)

    async def update_run(self, run_id: str, **kwargs: Any) -> Any:
        status = kwargs.get("status")
        if status in {"completed", "failed"}:
            self.order.append(f"status:{status}")
        return await self._inner.update_run(run_id, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _make_request_for_impl(store: Any) -> MagicMock:
    request = MagicMock()
    request.app.state.run_store = store
    request.app.state.run_semaphore = None
    request.app.state.artifact_store = None
    request.app.state.run_tasks = {}
    request.app.state.sub_agents = {}
    request.app.state.deps = MagicMock()
    return request


@pytest.mark.asyncio
async def test_completed_event_appended_before_status_flip(tmp_path: Any, monkeypatch: Any) -> None:
    """Success path: run.completed must be in run_events BEFORE the run row
    flips to status='completed', and the event must exist whenever the status
    is terminal."""
    from finrobot.engine.pipelines.base import PipelineResult
    from finrobot.routes import runs as runs_mod
    from finrobot.run_store import RunStore

    inner = RunStore(tmp_path / "runs.db")
    record = await inner.create_run("research", "AAPL")

    pipeline = MagicMock()
    pipeline.steps = [MagicMock()]
    result = PipelineResult(steps={"report": "done"}, structured_data={})
    result.artifact_id = None  # no artifact → no artifact.ready, isolates the swap
    pipeline.execute = AsyncMock(return_value=result)
    pipeline.format_summary = MagicMock(return_value="summary")
    monkeypatch.setattr(
        runs_mod, "get_pipeline_factories", lambda: {"research": lambda agents: pipeline}
    )

    store = _OrderRecordingStore(inner)
    await runs_mod._run_pipeline_impl(record.run_id, _make_request_for_impl(store))

    # The terminal event was committed BEFORE the terminal status flip.
    assert store.order == ["event:run.completed", "status:completed"]

    # Invariant: status is terminal AND the terminal event exists in run_events.
    final = await inner.get_run(record.run_id)
    assert final is not None and final.status == "completed"
    events = await inner.get_events_after(record.run_id, 0)
    assert any(e.event.get("event") == "run.completed" for e in events)
    await inner.close()


@pytest.mark.asyncio
async def test_failed_event_appended_before_status_flip(tmp_path: Any, monkeypatch: Any) -> None:
    """Failure path: run.failed must be in run_events BEFORE the run row flips
    to status='failed', and the event must exist whenever the status is
    terminal."""
    from finrobot.routes import runs as runs_mod
    from finrobot.run_store import RunStore

    inner = RunStore(tmp_path / "runs.db")
    record = await inner.create_run("research", "AAPL")

    pipeline = MagicMock()
    pipeline.steps = [MagicMock()]
    pipeline.execute = AsyncMock(side_effect=ValueError("boom"))
    monkeypatch.setattr(
        runs_mod, "get_pipeline_factories", lambda: {"research": lambda agents: pipeline}
    )

    store = _OrderRecordingStore(inner)
    await runs_mod._run_pipeline_impl(record.run_id, _make_request_for_impl(store))

    # The terminal event was committed BEFORE the terminal status flip.
    assert store.order == ["event:run.failed", "status:failed"]

    # Invariant: status is terminal AND the terminal event exists in run_events.
    final = await inner.get_run(record.run_id)
    assert final is not None and final.status == "failed"
    events = await inner.get_events_after(record.run_id, 0)
    assert any(e.event.get("event") == "run.failed" for e in events)
    await inner.close()


# --- BUG-050: SSE idle-poll backoff -----------------------------------------


def test_next_poll_interval_floors_when_events_arrive() -> None:
    """Any event in a round snaps the interval back to the responsive floor."""
    from finrobot.routes import runs as runs_mod

    # Even from a backed-off interval, fresh events reset to the minimum.
    assert (
        runs_mod._next_poll_interval(runs_mod._SSE_POLL_MAX_INTERVAL, had_events=True)
        == runs_mod._SSE_POLL_MIN_INTERVAL
    )


def test_next_poll_interval_backs_off_exponentially_to_ceiling() -> None:
    """Empty rounds grow the interval geometrically, capped at the ceiling."""
    from finrobot.routes import runs as runs_mod

    interval = runs_mod._SSE_POLL_MIN_INTERVAL
    seen = [interval]
    for _ in range(10):
        interval = runs_mod._next_poll_interval(interval, had_events=False)
        seen.append(interval)

    # Strictly increasing until it pins at the ceiling, never exceeding it.
    assert seen[1] > seen[0]
    assert max(seen) == runs_mod._SSE_POLL_MAX_INTERVAL
    assert all(v <= runs_mod._SSE_POLL_MAX_INTERVAL for v in seen)
    # Once at the ceiling, idle rounds keep it pinned (no overshoot).
    assert (
        runs_mod._next_poll_interval(runs_mod._SSE_POLL_MAX_INTERVAL, had_events=False)
        == runs_mod._SSE_POLL_MAX_INTERVAL
    )
