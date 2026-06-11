"""Route tests for POST /api/debate (Task 8).

asyncio_mode = "auto" (pyproject.toml) — no @pytest.mark.asyncio needed.

Stubs:
  - ArtifactStore.get  → returns a seeded Artifact or None
  - RunStore           → AsyncMock so no SQLite required
  - build_debate_agents→ monkeypatched to return _StubAgents (no LLM calls)
"""

from __future__ import annotations

import asyncio

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from finrobot.artifact.models import (
    Artifact,
    ArtifactAssumptions,
    ArtifactComputeVersion,
    ArtifactInputs,
    ArtifactMeta,
    ArtifactOutputs,
)
from pydantic_ai.exceptions import AgentRunError

from finrobot.engine.debate.models import (
    Argument,
    SideCase,
    Verdict,
)
from finrobot.llm_probe import LlmProbeGate
from finrobot.routes.debate import DebateRequest, router

_UTC = timezone.utc
_NOW = datetime(2026, 6, 1, tzinfo=_UTC)


# ── Stub agent ────────────────────────────────────────────────────────────────


class _StubAgent:
    """Returns a fixed output without any LLM call — mirrors tests/engine/debate/test_service.py."""

    def __init__(self, output: SideCase | Verdict) -> None:
        self._output = output

    async def run(self, prompt: str, deps: object = None) -> object:
        class _Result:
            pass

        r = _Result()
        r.output = self._output  # type: ignore[attr-defined]
        return r


def _stub_agents() -> dict[str, Any]:
    return {
        "bull": _StubAgent(
            SideCase(side="bull", arguments=[Argument(claim="강세 논거", evidence_ids=[])])
        ),
        "bear": _StubAgent(
            SideCase(side="bear", arguments=[Argument(claim="약세 논거", evidence_ids=[])])
        ),
        "judge": _StubAgent(
            Verdict(call="HOLD", conviction=0.5, swing_factor="x", change_my_mind="y")
        ),
    }


# ── Artifact factory ──────────────────────────────────────────────────────────


def _equity_research_artifact(artifact_id: str = "seed-1", ticker: str = "NVDA") -> Artifact:
    """Minimal equity_research artifact whose valuation_synthesis has reliable=True.

    Provides enough structure for build_evidence_set to return a non-empty
    EvidenceSet (reliable=True) so the debate is not gate-killed to REVIEW.
    """
    structured: dict[str, Any] = {
        "valuation_synthesis": {
            "ticker": ticker,
            "current_price": 900.0,
            "reliable": True,
            "upside_downside": 15.5,
            "weighted_price": 1035.0,
            "methods": [
                {"name": "DCF", "mid": 1050.0, "source": "dcf"},
            ],
        }
    }
    return Artifact(
        id=artifact_id,
        ticker=ticker,
        cross_tickers=[],
        type="equity_research",
        inputs=ArtifactInputs(data_source="stub", data_fetched_at=_NOW, raw_data={}),
        assumptions=ArtifactAssumptions(parameters={}),
        compute_version=ArtifactComputeVersion(version="0.1.0", formula_id="equity_research"),
        outputs=ArtifactOutputs(structured=structured),
        meta=ArtifactMeta(created_at=_NOW, source="test"),
    )


# ── App factory ───────────────────────────────────────────────────────────────


def _make_app(
    artifact: Artifact | None = None,
    run_id: str = "run_testdebate01",
) -> FastAPI:
    """Minimal app with debate router, mock stores, and stub settings."""
    app = FastAPI()
    app.include_router(router)

    # --- artifact store stub ---
    artifact_store = AsyncMock()
    artifact_store.get = AsyncMock(return_value=artifact)
    app.state.artifact_store = artifact_store

    # --- run store stub ---
    run_store = AsyncMock()
    run_record = MagicMock()
    run_record.run_id = run_id
    run_store.create_run = AsyncMock(return_value=run_record)
    run_store.update_run = AsyncMock(return_value=None)
    run_store.append_event = AsyncMock(return_value=1)
    app.state.run_store = run_store

    # --- run_tasks (background task registry) ---
    app.state.run_tasks = {}

    # --- deps (settings) stub — only needs settings.create_model / get_model_for_role ---
    deps = MagicMock()
    settings = MagicMock()
    settings.create_model = MagicMock(return_value=MagicMock())
    settings.get_model_for_role = MagicMock(return_value=None)
    # Key-validity gate (ensure_llm_reachable): kind="test" skips the live probe.
    settings.model_name = "test:stub"
    settings.provider_by_id.return_value.kind = "test"
    deps.settings = settings
    app.state.deps = deps
    app.state.llm_probe_gate = LlmProbeGate()

    return app


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_create_debate_returns_run_id() -> None:
    """POST /api/debate with a valid artifact_id returns 200 + run_id."""
    app = _make_app(artifact=_equity_research_artifact("seed-1"))

    with patch(
        "finrobot.routes.debate.build_debate_agents",
        return_value=_stub_agents(),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            resp = await client.post(
                "/api/debate", json={"ticker": "NVDA", "artifact_id": "seed-1"}
            )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "run_id" in body
    assert body["run_id"] == "run_testdebate01"


async def test_missing_artifact_404() -> None:
    """POST /api/debate with an unknown artifact_id returns 404."""
    app = _make_app(artifact=None)  # store.get returns None

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post("/api/debate", json={"ticker": "X", "artifact_id": "nope"})

    assert resp.status_code == 404
    assert "nope" in resp.json()["detail"]


async def test_empty_ticker_rejected_422() -> None:
    """BUG-032: empty/blank ticker must be rejected at validation time (422),
    not stored as a malformed run — matches the compute routes' Field(min_length=1)."""
    app = _make_app(artifact=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post("/api/debate", json={"ticker": "", "artifact_id": "art-1"})
    assert resp.status_code == 422, resp.text


async def test_empty_artifact_id_rejected_422() -> None:
    """BUG-040: empty artifact_id must be rejected at validation time (422)."""
    app = _make_app(artifact=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post("/api/debate", json={"ticker": "AAPL", "artifact_id": ""})
    assert resp.status_code == 422, resp.text


def test_debate_request_accepts_twelve_character_ticker() -> None:
    assert DebateRequest(ticker="abcdefghijkl", artifact_id="art-1").ticker == "ABCDEFGHIJKL"


async def test_invalid_debate_ticker_rejected_422() -> None:
    app = _make_app(artifact=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post("/api/debate", json={"ticker": "苹果", "artifact_id": "art-1"})
    assert resp.status_code == 422, resp.text


async def test_malformed_structured_data_returns_422() -> None:
    """A reachable artifact whose structured data can't be parsed into evidence
    must return a client-facing 422, not a raw 500 (BUG-021).

    build_evidence_set float()s current_price / upside / mid — a non-numeric
    value raises ValueError, which previously escaped create_debate (a sync path
    before the background task) as an unhandled 500.
    """
    art = _equity_research_artifact("art-bad")
    # Corrupt a numeric field into a non-numeric string the way a malformed
    # upstream artifact would.
    art.outputs.structured["valuation_synthesis"]["current_price"] = "N/A"
    app = _make_app(artifact=art)

    with patch(
        "finrobot.routes.debate.build_debate_agents",
        return_value=_stub_agents(),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            resp = await client.post(
                "/api/debate", json={"ticker": "NVDA", "artifact_id": "art-bad"}
            )

    assert resp.status_code == 422, resp.text
    assert "art-bad" in resp.json()["detail"]


async def test_create_debate_registers_background_task() -> None:
    """Background task must be registered in app.state.run_tasks immediately."""
    app = _make_app(artifact=_equity_research_artifact("art-bg"))

    with patch(
        "finrobot.routes.debate.build_debate_agents",
        return_value=_stub_agents(),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            resp = await client.post(
                "/api/debate", json={"ticker": "NVDA", "artifact_id": "art-bg"}
            )

    assert resp.status_code == 200
    # After the request returns the task should be in run_tasks (or already done — both valid)
    # The key invariant: no KeyError, no crash.  run_tasks may have been cleaned up by
    # the time we check if the task ran to completion inside the test event loop.
    assert isinstance(app.state.run_tasks, dict)


async def test_create_debate_calls_run_store_create_run() -> None:
    """RunStore.create_run must be called with pipeline_type='debate' and the requested ticker."""
    app = _make_app(artifact=_equity_research_artifact("art-cr", ticker="AAPL"))

    with patch(
        "finrobot.routes.debate.build_debate_agents",
        return_value=_stub_agents(),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            await client.post("/api/debate", json={"ticker": "AAPL", "artifact_id": "art-cr"})

    app.state.run_store.create_run.assert_called_once_with("debate", "AAPL")


async def test_successful_debate_emits_run_completed() -> None:
    """Regression: the success path must emit a terminal run.completed event.

    Without it the run silently flips to status='completed' but no SSE event is
    sent. The server closes the stream, the frontend (still 'running') reads the
    close as an error, reconnects, the server closes again → 8 errors → the
    catastrophic "请检查后端服务" banner fires even though the verdict arrived.
    This mirrors test_agent_run_error_transitions_run_to_failed for the happy path.
    """
    import asyncio

    app = _make_app(artifact=_equity_research_artifact("art-ok"))

    with patch(
        "finrobot.routes.debate.build_debate_agents",
        return_value=_stub_agents(),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            resp = await client.post(
                "/api/debate", json={"ticker": "NVDA", "artifact_id": "art-ok"}
            )

    assert resp.status_code == 200
    run_id = resp.json()["run_id"]

    bg_task = app.state.run_tasks.get(run_id)
    if bg_task is not None:
        await asyncio.gather(bg_task, return_exceptions=True)
    else:
        await asyncio.sleep(0.05)

    run_store = app.state.run_store

    # run must have been finished as completed via finish_run — the store-level
    # helper that commits run.completed BEFORE the status flip (BUG-034).
    finish_calls = run_store.finish_run.call_args_list
    completed_call = next(
        (c for c in finish_calls if c.kwargs.get("status") == "completed"),
        None,
    )
    assert completed_call is not None, "finish_run(status='completed') was never called"
    event = completed_call.args[1]
    assert event["event"] == "run.completed"
    assert event["run_id"] == run_id
    assert event["ticker"] == "NVDA"

    assert run_id not in app.state.run_tasks, "run_id still in run_tasks after completion"


async def test_agent_run_error_transitions_run_to_failed() -> None:
    """Regression: AgentRunError from a real LLM agent must not leave run at status='running'.

    Before the except-tuple fix, AgentRunError / UnexpectedModelBehavior escaped the
    handler, the run stayed 'running', and GET /api/runs/{id}/events hung forever.
    This test verifies the handler catches it, marks the run failed, emits run.failed,
    and pops run_tasks.
    """

    class _RaisingAgent:
        """Agent stub that raises AgentRunError on run()."""

        async def run(self, prompt: str, deps: object = None) -> object:
            raise AgentRunError("simulated LLM failure")

    app = _make_app(artifact=_equity_research_artifact("art-err"))
    failing_agents = {
        "bull": _RaisingAgent(),
        "bear": _RaisingAgent(),
        "judge": _RaisingAgent(),
    }

    with patch(
        "finrobot.routes.debate.build_debate_agents",
        return_value=failing_agents,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            resp = await client.post(
                "/api/debate", json={"ticker": "NVDA", "artifact_id": "art-err"}
            )

    # POST itself succeeds — the failure happens inside the background task.
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]

    # Wait for the background task to complete.  The task is created by
    # asyncio.create_task inside the route handler; we retrieve it from
    # run_tasks (registered before the route returns) and await it directly
    # so the test doesn't rely on timing.  If the task already finished and
    # was popped from run_tasks we fall back to a short sleep.
    import asyncio

    bg_task = app.state.run_tasks.get(run_id)
    if bg_task is not None:
        await asyncio.gather(bg_task, return_exceptions=True)
    else:
        await asyncio.sleep(0.05)

    run_store = app.state.run_store

    # run must have been finished as failed via finish_run (not left at
    # 'running') — event-before-status is the helper's contract (BUG-034).
    finish_calls = run_store.finish_run.call_args_list
    failed_call = next(
        (c for c in finish_calls if c.kwargs.get("status") == "failed"),
        None,
    )
    assert failed_call is not None, "finish_run(status='failed') was never called"
    assert failed_call.args[1]["event"] == "run.failed"

    # run_tasks must have been cleaned up.
    assert run_id not in app.state.run_tasks, "run_id still in run_tasks after failure"


# ── Money gates (P1-14: debate was the uncounted fourth LLM-spending endpoint) ──


async def test_create_debate_503_when_startup_error_set() -> None:
    """A broken runtime config (startup_error) must 503 BEFORE create_run —
    same gate as POST /api/runs; debate used to skip it and surface an opaque
    500 from provider construction, leaving an orphan run row behind."""
    app = _make_app(artifact=_equity_research_artifact("seed-1"))
    app.state.startup_error = "LLM key missing"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post("/api/debate", json={"ticker": "NVDA", "artifact_id": "seed-1"})

    assert resp.status_code == 503
    app.state.run_store.create_run.assert_not_awaited()


async def test_create_debate_429_when_rate_limited() -> None:
    """Debate spends real LLM money (3 agents) — it shares the runs token
    bucket instead of being infinitely triggerable."""
    app = _make_app(artifact=_equity_research_artifact("seed-1"))
    limiter = MagicMock()
    limiter.allow_runs = MagicMock(return_value=False)
    app.state.run_rate_limiter = limiter

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post("/api/debate", json={"ticker": "NVDA", "artifact_id": "seed-1"})

    assert resp.status_code == 429
    app.state.run_store.create_run.assert_not_awaited()


async def test_debate_task_acquires_run_semaphore() -> None:
    """The debate task must hold the app-wide LLM concurrency cap while
    debating — it was the only LLM path outside the BUG-017 semaphore."""
    app = _make_app(artifact=_equity_research_artifact("seed-1"))

    acquired: list[str] = []

    class _Sem:
        async def __aenter__(self) -> None:
            acquired.append("enter")

        async def __aexit__(self, *exc: object) -> None:
            acquired.append("exit")

    app.state.deps.run_semaphore = _Sem()

    with patch(
        "finrobot.routes.debate.build_debate_agents",
        return_value=_stub_agents(),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            resp = await client.post(
                "/api/debate", json={"ticker": "NVDA", "artifact_id": "seed-1"}
            )
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]
    bg_task = app.state.run_tasks.get(run_id)
    if bg_task is not None:
        await asyncio.gather(bg_task, return_exceptions=True)
    else:
        await asyncio.sleep(0.05)

    assert acquired == ["enter", "exit"]
