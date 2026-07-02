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

from finrobot.llm_probe import LlmProbeGate
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
    # spawn_run reads deps.settings.is_model_configured for the first-run guard.
    # Default to a usable model; tests that exercise the no-model 503 override it.
    deps = MagicMock()
    deps.settings.is_model_configured = True
    # The key-validity gate (ensure_llm_reachable) parses model_name and skips
    # the live probe for kind="test" providers — give it a passing default;
    # the gate-specific tests below override these.
    deps.settings.model_name = "test:stub"
    deps.settings.provider_by_id.return_value.kind = "test"
    app.state.deps = deps
    app.state.llm_probe_gate = LlmProbeGate()
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


def test_result_to_json_warnings_match_artifact_haul() -> None:
    """Regression: /runs detail warnings must include run-level degrades AND
    failed-validation lines — not just structured-object warnings. Previously a
    half-degraded run read 'clean' in the run view while the artifact view
    surfaced the degrade (the two rendering surfaces disagreed). Both now route
    through PipelineResult.collect_warnings — the single authoritative haul."""
    from types import SimpleNamespace

    from finrobot.engine.pipelines.base import PipelineResult
    from finrobot.routes.runs import _result_to_json

    result = PipelineResult(
        steps={"financial_modeling": "DCF FAIR VALUE —"},
        structured_data={
            "data_collection": SimpleNamespace(warnings=["provider X stale cache"]),
        },
        failed_validations=[
            {"step": "financial_modeling", "error": "WACC 0.0280 below minimum 0.03"},
        ],
        warnings=["DCF not applicable: WACC ≤ terminal growth"],
    )
    out_warnings = _result_to_json(result)["warnings"]
    blob = "\n".join(out_warnings)
    assert "WACC 0.0280 below minimum 0.03" in blob  # failed_validations surfaced
    assert "DCF not applicable" in blob  # run-level warning surfaced
    assert "provider X stale cache" in blob  # structured-object warning surfaced
    # Identical to the artifact's authoritative haul — single source of truth.
    assert out_warnings == result.collect_warnings()


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
async def test_create_run_503_when_model_not_configured() -> None:
    """First-run guard: an unconfigured model carries NO startup_error (it's
    onboarding, not an error) yet must still 503 — agents were never built. The
    detail routes the desktop preflight to Settings → AI Model."""
    app = _make_app(startup_error=None)
    app.state.deps.settings.is_model_configured = False
    store = app.state.run_store
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/runs", json={"pipeline_type": "full_analysis", "ticker": "AAPL"})

    assert resp.status_code == 503, resp.text
    assert "No AI model configured" in resp.json()["detail"]
    store.create_run.assert_not_awaited()
    assert app.state.run_tasks == {}


def _configure_live_provider(app: FastAPI) -> None:
    """Point the mock settings at a NON-test provider so the live probe runs."""
    settings = app.state.deps.settings
    settings.model_name = "openai:gpt-4o"
    settings.provider_by_id.return_value.kind = "openai-compatible"
    settings.provider_key.return_value = "aa"


@pytest.mark.asyncio
async def test_create_run_503_when_key_fails_live_probe(monkeypatch: Any) -> None:
    """A key that EXISTS but cannot authenticate must reject the run at submit
    time (classified reason in the detail), not minutes later inside the first
    agent LLM step — and must not persist an orphan run row."""
    from finrobot import llm_probe

    app = _make_app()
    _configure_live_provider(app)

    async def fake_probe(*_args: Any) -> tuple[bool, str, str]:
        return False, "auth", "status_code: 401, body: invalid api key"

    monkeypatch.setattr(llm_probe, "probe_model", fake_probe)
    store = app.state.run_store
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/runs", json={"pipeline_type": "full_analysis", "ticker": "AAPL"})

    assert resp.status_code == 503, resp.text
    assert "auth" in resp.json()["detail"]
    assert "Settings" in resp.json()["detail"]
    store.create_run.assert_not_awaited()
    assert app.state.run_tasks == {}


@pytest.mark.asyncio
async def test_llm_probe_success_cached_per_fingerprint(monkeypatch: Any) -> None:
    """One green probe per (model, key) fingerprint: the second submit makes no
    extra LLM call; a key change invalidates the cache (new fingerprint)."""
    from finrobot import llm_probe

    app = _make_app()
    _configure_live_provider(app)

    calls = 0

    async def fake_probe(*_args: Any) -> tuple[bool, str, str]:
        nonlocal calls
        calls += 1
        return True, "ok", ""

    monkeypatch.setattr(llm_probe, "probe_model", fake_probe)
    monkeypatch.setattr(
        "finrobot.routes.runs.get_pipeline_factories",
        lambda: {"full_analysis": lambda agents: MagicMock()},
    )
    app.state.run_store.create_run = AsyncMock(return_value=_make_run_record(status="created"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        first = await c.post("/api/runs", json={"pipeline_type": "full_analysis", "ticker": "AAPL"})
        second = await c.post(
            "/api/runs", json={"pipeline_type": "full_analysis", "ticker": "MSFT"}
        )
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert calls == 1

        app.state.deps.settings.provider_key.return_value = "rotated-key"
        third = await c.post("/api/runs", json={"pipeline_type": "full_analysis", "ticker": "KO"})
        assert third.status_code == 200, third.text
        assert calls == 2


def test_mark_verified_only_seeds_the_selected_model() -> None:
    """A green Settings test seeds the gate ONLY for the configured model_name —
    testing a provider being edited but not selected must not green-light runs."""
    gate = LlmProbeGate()
    settings = MagicMock()
    settings.model_name = "openai:gpt-4o"
    settings.provider_key.return_value = "k"

    gate.mark_verified(settings, "anthropic", "claude-sonnet-4-6")
    assert gate._verified == set()

    gate.mark_verified(settings, "openai", "gpt-4o")
    assert ("openai:gpt-4o", "k") in gate._verified


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

    async def _finish(run_id: str, terminal_event: dict[str, Any], **kwargs: Any) -> None:
        # Mirror RunStore.finish_run's observable side: the terminal event
        # lands in run_events (captured here) before the status flip.
        appended.append(terminal_event)

    store.finish_run = AsyncMock(side_effect=_finish)

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
    deps = MagicMock()
    # Key-validity gate: kind="test" skips the live probe (mirrors _make_app).
    deps.settings.model_name = "test:stub"
    deps.settings.provider_by_id.return_value.kind = "test"
    app.state.deps = deps
    app.state.llm_probe_gate = LlmProbeGate()
    app.state.artifact_store = None
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


@pytest.mark.asyncio
async def test_aggregated_stream_400_when_too_many_ids() -> None:
    """An unbounded ?ids= list (script-built, not the UI) must 400 before it
    fans N get_run/get_events polls onto the shared store connection."""
    from finrobot.routes import runs as runs_mod

    app = _make_app(_make_run_record())
    ids = ",".join(f"run-{i}" for i in range(runs_mod._MAX_MULTIPLEX_IDS + 1))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(f"/api/runs/events?ids={ids}")
    assert resp.status_code == 400
    assert "Too many run ids" in resp.json()["detail"]
    # Duplicates collapse before the cap — 60 copies of one id are 1 id.
    dup_ids = ",".join("run-dup" for _ in range(60))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(f"/api/runs/events?ids={dup_ids}")
    assert resp.status_code == 200


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
        if ev in {"run.completed", "run.failed", "run.cancelled"}:
            self.order.append(f"event:{ev}")
        return await self._inner.append_event(run_id, event)

    async def update_run(self, run_id: str, **kwargs: Any) -> Any:
        status = kwargs.get("status")
        if status in {"completed", "failed", "cancelled"}:
            self.order.append(f"status:{status}")
        return await self._inner.update_run(run_id, **kwargs)

    async def finish_run(self, run_id: str, terminal_event: Any, **kwargs: Any) -> Any:
        # Run the REAL production ordering logic with this wrapper as self, so
        # its append_event/update_run calls flow through the recording methods
        # above — re-implementing the sequence here would test a copy of the
        # invariant instead of the invariant.
        from finrobot.run_store import RunStore

        return await RunStore.finish_run(self, run_id, terminal_event, **kwargs)  # type: ignore[arg-type]

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
    pipeline.execute = AsyncMock(
        side_effect=ValueError(
            "boom for url https://financialmodelingprep.com/api/v3/quote/AAPL?apikey=secret"
        )
    )
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
    assert final.error is not None
    assert "apikey" not in final.error
    assert "for url" not in final.error
    assert "financialmodelingprep.com" not in final.error
    events = await inner.get_events_after(record.run_id, 0)
    failed = [e.event for e in events if e.event.get("event") == "run.failed"]
    assert failed
    failed_error = str(failed[0].get("error") or "")
    assert "apikey" not in failed_error
    assert "for url" not in failed_error
    assert "financialmodelingprep.com" not in failed_error
    await inner.close()


# ---------------------------------------------------------------------------
# P1-30 — GET /api/runs: the run registry list. The desktop's restart-reattach
# asks ?status=created,running on startup to find pipelines still executing
# after a webview reload (the in-memory run map is gone, the backend keeps
# burning) and re-subscribe their SSE streams.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_runs_returns_all_newest_first(tmp_path: Any) -> None:
    from finrobot.run_store import RunStore

    store = RunStore(tmp_path / "runs.db")
    rid_done = await _seed_completed_run(store, "AAPL")
    rec_created = await store.create_run("research", "MSFT")
    app = _make_app_with_store(store)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/runs")
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert {row["run_id"] for row in body} == {rid_done, rec_created.run_id}
    # Registry view only — no result payload fields leak into the list.
    assert "result" not in body[0] and "result_text" not in body[0]
    await store.close()


@pytest.mark.asyncio
async def test_list_runs_status_filter_returns_only_active(tmp_path: Any) -> None:
    """?status=created,running excludes terminal rows — the reattach query."""
    from finrobot.run_store import RunStore

    store = RunStore(tmp_path / "runs.db")
    await _seed_completed_run(store, "AAPL")
    rec_created = await store.create_run("research", "MSFT")
    rec_running = await store.create_run("dcf", "NVDA")
    await store.update_run(rec_running.run_id, status="running")
    app = _make_app_with_store(store)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/runs?status=created,running")
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert {row["run_id"] for row in body} == {rec_created.run_id, rec_running.run_id}
    assert {row["status"] for row in body} == {"created", "running"}
    await store.close()


@pytest.mark.asyncio
async def test_list_runs_filter_in_sql_not_on_limited_page(tmp_path: Any) -> None:
    """An active run older than `limit` newer terminal rows must still be
    returned: the status filter runs in SQL, not post-hoc on a LIMITed page."""
    from finrobot.run_store import RunStore

    store = RunStore(tmp_path / "runs.db")
    rec_running = await store.create_run("research", "NVDA")
    await store.update_run(rec_running.run_id, status="running")
    for i in range(3):
        await _seed_completed_run(store, f"T{i}")
    app = _make_app_with_store(store)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/runs?status=created,running&limit=2")
    assert resp.status_code == 200, resp.text
    assert [row["run_id"] for row in resp.json()] == [rec_running.run_id]
    await store.close()


@pytest.mark.asyncio
async def test_list_runs_unknown_status_is_400() -> None:
    app = _make_app(None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/runs?status=bogus")
    assert resp.status_code == 400
    assert "bogus" in resp.json()["detail"]


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


# ---------------------------------------------------------------------------
# POST /api/runs/{run_id}/cancel — the stop button for money-burning pipelines.
# A live task is cancelled (CancelledError handler persists the `cancelled`
# terminal state, event-before-status), an orphaned record is finalised
# directly, and a run that already finished is an idempotent no-op.
# ---------------------------------------------------------------------------


def _sleeping_pipeline() -> MagicMock:
    """A pipeline whose execute blocks until cancelled — a stand-in for a
    long LLM call that the user wants to stop paying for."""
    import asyncio as _asyncio

    pipeline = MagicMock()
    pipeline.steps = [MagicMock()]

    async def _block(*args: Any, **kwargs: Any) -> Any:
        await _asyncio.sleep(60)
        raise AssertionError("pipeline was not cancelled")

    pipeline.execute = AsyncMock(side_effect=_block)
    return pipeline


@pytest.mark.asyncio
async def test_cancel_running_run_persists_cancelled_state(tmp_path: Any, monkeypatch: Any) -> None:
    """End-to-end: create a run on a blocking pipeline, cancel it, and the run
    lands on status='cancelled' with a run.cancelled terminal event."""
    import asyncio as _asyncio

    from finrobot.routes import runs as runs_mod
    from finrobot.run_store import RunStore

    monkeypatch.setattr(
        runs_mod,
        "get_pipeline_factories",
        lambda: {"research": lambda agents: _sleeping_pipeline()},
    )
    store = RunStore(tmp_path / "runs.db")
    app = _make_app_with_store(store)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        created = await c.post("/api/runs", json={"pipeline_type": "research", "ticker": "AAPL"})
        assert created.status_code == 200, created.text
        run_id = created.json()["run_id"]

        # Give the task a tick to reach the blocking await.
        for _ in range(50):
            await _asyncio.sleep(0.01)
            record = await store.get_run(run_id)
            assert record is not None
            if record.status == "running":
                break
        task = app.state.run_tasks[run_id]

        resp = await c.post(f"/api/runs/{run_id}/cancel")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"run_id": run_id, "status": "cancelling"}

        # Wait for the task to unwind through its CancelledError handler.
        with pytest.raises(_asyncio.CancelledError):
            await task

        final = await store.get_run(run_id)
        assert final is not None and final.status == "cancelled"
        # A cancel is not an error — no error text on the record.
        assert final.error is None
        assert final.completed_at is not None
        events = await store.get_events_after(run_id, 0)
        cancelled = [e for e in events if e.event.get("event") == "run.cancelled"]
        assert len(cancelled) == 1
        assert cancelled[0].event.get("ticker") == "AAPL"
        # Bookkeeping: task map and cancel-intent set are both cleaned up.
        assert run_id not in app.state.run_tasks
        assert run_id not in app.state.cancel_requested
    await store.close()


@pytest.mark.asyncio
async def test_cancelled_event_appended_before_status_flip(tmp_path: Any) -> None:
    """The cancelled terminal path honours the BUG-034 ordering invariant:
    run.cancelled is committed BEFORE the status flips to 'cancelled'."""
    import asyncio as _asyncio

    from finrobot.routes import runs as runs_mod
    from finrobot.run_store import RunStore

    inner = RunStore(tmp_path / "runs.db")
    record = await inner.create_run("research", "AAPL")
    store = _OrderRecordingStore(inner)

    request = _make_request_for_impl(store)
    request.app.state.cancel_requested = {record.run_id}

    pipeline = _sleeping_pipeline()
    factories = {"research": lambda agents: pipeline}

    async def _impl() -> None:
        import unittest.mock as _mock

        with _mock.patch.object(runs_mod, "get_pipeline_factories", lambda: factories):
            await runs_mod._run_pipeline_impl(record.run_id, request)

    task = _asyncio.create_task(_impl())
    for _ in range(50):
        await _asyncio.sleep(0.01)
        current = await inner.get_run(record.run_id)
        assert current is not None
        if current.status == "running":
            break
    task.cancel()
    with pytest.raises(_asyncio.CancelledError):
        await task

    assert store.order == ["event:run.cancelled", "status:cancelled"]
    final = await inner.get_run(record.run_id)
    assert final is not None and final.status == "cancelled"
    await inner.close()


@pytest.mark.asyncio
async def test_shutdown_cancel_does_not_mark_cancelled(tmp_path: Any) -> None:
    """A cancel WITHOUT user intent (server shutdown) must NOT write the
    `cancelled` terminal state — the row stays non-terminal for the next
    startup's reconciler to mark failed('interrupted by server restart')."""
    import asyncio as _asyncio

    from finrobot.routes import runs as runs_mod
    from finrobot.run_store import RunStore

    store = RunStore(tmp_path / "runs.db")
    record = await store.create_run("research", "AAPL")

    request = _make_request_for_impl(store)
    request.app.state.cancel_requested = set()  # no user intent recorded

    pipeline = _sleeping_pipeline()
    factories = {"research": lambda agents: pipeline}

    async def _impl() -> None:
        import unittest.mock as _mock

        with _mock.patch.object(runs_mod, "get_pipeline_factories", lambda: factories):
            await runs_mod._run_pipeline_impl(record.run_id, request)

    task = _asyncio.create_task(_impl())
    for _ in range(50):
        await _asyncio.sleep(0.01)
        current = await store.get_run(record.run_id)
        assert current is not None
        if current.status == "running":
            break
    task.cancel()
    with pytest.raises(_asyncio.CancelledError):
        await task

    final = await store.get_run(record.run_id)
    assert final is not None and final.status == "running"  # reconciler's job
    events = await store.get_events_after(record.run_id, 0)
    assert not any(e.event.get("event") == "run.cancelled" for e in events)
    await store.close()


@pytest.mark.asyncio
async def test_cancel_terminal_run_is_idempotent_noop(tmp_path: Any) -> None:
    """Cancelling an already-finished run reports its real status and appends
    nothing — history is not rewritten."""
    from finrobot.run_store import RunStore

    store = RunStore(tmp_path / "runs.db")
    run_id = await _seed_completed_run(store, "AAPL")
    app = _make_app_with_store(store)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(f"/api/runs/{run_id}/cancel")
    assert resp.status_code == 200
    assert resp.json() == {"run_id": run_id, "status": "completed"}
    events = await store.get_events_after(run_id, 0)
    assert not any(e.event.get("event") == "run.cancelled" for e in events)
    await store.close()


@pytest.mark.asyncio
async def test_cancel_unknown_run_404() -> None:
    app = _make_app(None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/runs/does-not-exist/cancel")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cancel_orphaned_record_finalises_directly(tmp_path: Any) -> None:
    """A non-terminal row with no live task (crash orphan) is finalised to
    'cancelled' by the endpoint itself instead of staying wedged."""
    from finrobot.run_store import RunStore

    store = RunStore(tmp_path / "runs.db")
    record = await store.create_run("research", "AAPL")
    await store.update_run(record.run_id, status="running")
    app = _make_app_with_store(store)  # run_tasks empty — no live task

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(f"/api/runs/{record.run_id}/cancel")
    assert resp.status_code == 200
    assert resp.json() == {"run_id": record.run_id, "status": "cancelled"}

    final = await store.get_run(record.run_id)
    assert final is not None and final.status == "cancelled"
    events = await store.get_events_after(record.run_id, 0)
    assert any(e.event.get("event") == "run.cancelled" for e in events)
    await store.close()


@pytest.mark.asyncio
async def test_sse_stream_closes_on_cancelled_run(tmp_path: Any) -> None:
    """`cancelled` is terminal for the SSE poll loop: the single-run stream
    emits the run.cancelled frame and then closes instead of polling forever
    (the wedge that {completed,failed} literals would reintroduce)."""
    from finrobot.events import RunCancelled, RunStarted
    from finrobot.run_store import RunStore

    store = RunStore(tmp_path / "runs.db")
    record = await store.create_run("research", "AAPL")
    run_id = record.run_id
    await store.append_event(
        run_id,
        RunStarted(
            event="run.started",
            run_id=run_id,
            pipeline_type="research",
            ticker="AAPL",
            total_steps=1,
        ),
    )
    await store.finish_run(
        run_id,
        RunCancelled(event="run.cancelled", run_id=run_id, ticker="AAPL"),
        status="cancelled",
        completed_at="2026-06-10T00:00:00+00:00",
    )
    app = _make_app_with_store(store)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(f"/api/runs/{run_id}/events")
    assert resp.status_code == 200  # the GET returning at all proves the close
    frames = _parse_sse(resp.text)
    assert [f["event"] for f in frames] == ["run.started", "run.cancelled"]
    await store.close()


@pytest.mark.asyncio
async def test_list_runs_accepts_cancelled_status_filter(tmp_path: Any) -> None:
    """?status=cancelled is a valid filter (T8: backend enum chain extended)."""
    from finrobot.events import RunCancelled
    from finrobot.run_store import RunStore

    store = RunStore(tmp_path / "runs.db")
    record = await store.create_run("research", "AAPL")
    await store.finish_run(
        record.run_id,
        RunCancelled(event="run.cancelled", run_id=record.run_id, ticker="AAPL"),
        status="cancelled",
        completed_at="2026-06-10T00:00:00+00:00",
    )
    app = _make_app_with_store(store)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/runs?status=cancelled")
    assert resp.status_code == 200, resp.text
    assert [row["run_id"] for row in resp.json()] == [record.run_id]
    await store.close()
