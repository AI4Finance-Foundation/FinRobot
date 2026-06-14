"""End-to-end smoke test for the IC debate pipeline (Plan 1, Task 9).

Scope
-----
POST /api/debate  →  background task runs to completion  →  assert events
stored in a real RunStore (SQLite, tmp_path).

What is stubbed
---------------
- ArtifactStore.get   — AsyncMock returning a seeded Artifact with
                        valuation_synthesis (confidence=high) so
                        build_evidence_set() extracts real evidence items.
- build_debate_agents — monkeypatched to _e2e_stub_agents():
    * bull:  2 Arguments:
        - Arg 1 cites "synthesis.upside_downside" (real id in evidence set)
          → verifier produces verified=True
        - Arg 2 cites no evidence (evidence_ids=[])
          → verifier produces verified=False  ← key assertion
    * bear:  1 Argument citing "synthesis.weighted_price" (real id)
          → verifier produces verified=True
    * judge: returns Verdict(call="HOLD", conviction=0.5, ...)

What is NOT stubbed
-------------------
- RunStore: a real SQLite-backed RunStore under tmp_path so that
  get_events_after() returns actual persisted data.
- build_evidence_set: real implementation — validates the seeded artifact
  actually produces the expected evidence_ids.
- run_debate / verify_arguments: real implementations — the stub only
  replaces the LLM agent I/O boundary, not the orchestration logic.

asyncio_mode = "auto" (pyproject.toml) — no @pytest.mark.asyncio needed.
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
from finrobot.engine.debate.models import (
    Argument,
    SideCase,
    Verdict,
)
from finrobot.llm_probe import LlmProbeGate
from finrobot.routes.debate import router
from finrobot.run_store import RunStore

_UTC = timezone.utc
_NOW = datetime(2026, 6, 1, tzinfo=_UTC)

# ── Evidence IDs that the seeded artifact will produce ────────────────────────
# Source: build_evidence_set() in finrobot/engine/debate/evidence.py —
# synthesis.upside_downside and synthesis.weighted_price are extracted when
# the corresponding keys exist in valuation_synthesis.
_EV_UPSIDE = "synthesis.upside_downside"
_EV_WEIGHTED = "synthesis.weighted_price"


# ── Stub agent ─────────────────────────────────────────────────────────────────
# Reuses the same _StubAgent pattern from tests/routes/test_debate.py.
# The agent's run() returns a fixed output without touching any LLM.


class _StubAgent:
    """Returns a fixed output without any LLM call."""

    def __init__(self, output: SideCase | Verdict) -> None:
        self._output = output

    async def run(self, prompt: str, deps: object = None) -> object:
        class _Result:
            pass

        r = _Result()
        r.output = self._output  # type: ignore[attr-defined]
        return r


def _e2e_stub_agents() -> dict[str, Any]:
    """Stub agents designed to exercise both verified=True and verified=False paths.

    bull — 2 arguments:
      Arg 1: cites _EV_UPSIDE  → evidence_id exists in set → verified=True
      Arg 2: evidence_ids=[]   → no evidence citation    → verified=False
    bear — 1 argument:
      Arg 1: cites _EV_WEIGHTED → evidence_id exists in set → verified=True
    judge — returns HOLD/0.5
    """
    return {
        "bull": _StubAgent(
            SideCase(
                side="bull",
                arguments=[
                    # Arg 1: grounded — cites real evidence id
                    Argument(claim="上行空间充足，加权目标价高于现价", evidence_ids=[_EV_UPSIDE]),
                    # Arg 2: ungrounded — no evidence citation → verified=False
                    Argument(claim="管理层执行力强劲（无证据支撑）", evidence_ids=[]),
                ],
            )
        ),
        "bear": _StubAgent(
            SideCase(
                side="bear",
                arguments=[
                    # Arg 1: grounded — cites real evidence id
                    Argument(claim="加权目标价存在下行风险", evidence_ids=[_EV_WEIGHTED]),
                ],
            )
        ),
        "judge": _StubAgent(
            Verdict(
                call="HOLD", conviction=0.5, swing_factor="估值分歧", change_my_mind="超预期营收"
            )
        ),
    }


# ── Artifact factory ───────────────────────────────────────────────────────────
# Produces a valuation_synthesis with confidence=high containing upside_downside,
# weighted_price, and one DCF method — so build_evidence_set() extracts:
#   synthesis.upside_downside, synthesis.weighted_price, method.DCF.mid


def _seeded_artifact(artifact_id: str = "e2e-art-01", ticker: str = "NVDA") -> Artifact:
    """Equity research artifact whose evidence set contains both stub evidence ids.

    structured_data layout mirrors the real pipeline output shape expected by
    build_evidence_set() (finrobot/engine/debate/evidence.py).
    """
    structured: dict[str, Any] = {
        "valuation_synthesis": {
            "ticker": ticker,
            "current_price": 900.0,
            "confidence": "high",
            "upside_downside": 15.5,  # → evidence_id "synthesis.upside_downside"
            "weighted_price": 1035.0,  # → evidence_id "synthesis.weighted_price"
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


# ── App factory — real RunStore, mock ArtifactStore ───────────────────────────


def _make_e2e_app(run_store: RunStore, artifact: Artifact) -> FastAPI:
    """Build a minimal FastAPI app wired with a *real* RunStore.

    The real RunStore lets the test call get_events_after() after the
    background task completes to inspect the actual persisted events —
    unlike test_debate.py which uses AsyncMock and can only inspect
    call_args_list.
    """
    app = FastAPI()
    app.include_router(router)

    # Real RunStore — backed by tmp_path SQLite
    app.state.run_store = run_store

    # ArtifactStore mock: only .get() is called by the route
    artifact_store = AsyncMock()
    artifact_store.get = AsyncMock(return_value=artifact)
    app.state.artifact_store = artifact_store

    # Background task registry
    app.state.run_tasks = {}

    # Deps stub — only settings.create_model / get_model_for_role are accessed
    # by build_debate_agents (which we monkeypatch away, but the route still
    # reads deps.settings before the patch intercepts it in build_debate_agents)
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


# ── End-to-end test ────────────────────────────────────────────────────────────


async def test_debate_e2e_full_flow(tmp_path: Any) -> None:
    """E2E smoke: POST /api/debate → background task → assert event stream.

    Asserts (in order):
    1. POST returns HTTP 200 + a run_id.
    2. After the background task completes, RunStore holds ≥1 debate.point.
    3. RunStore holds exactly 1 debate.verdict with call="HOLD".
    4. The ungrounded bull argument (evidence_ids=[]) has verified=False.
    5. The grounded bull argument (cites _EV_UPSIDE) has verified=True.
    6. The grounded bear argument (cites _EV_WEIGHTED) has verified=True.
    7. The run's final status == "completed".
    """
    # Instantiate a real RunStore backed by an isolated per-test SQLite file.
    # This is the critical difference from test_debate.py: events are actually
    # persisted and can be queried with get_events_after().
    db_path = tmp_path / "e2e_runs.db"
    run_store = RunStore(db_path=str(db_path))

    try:
        artifact = _seeded_artifact("e2e-art-01", ticker="NVDA")
        app = _make_e2e_app(run_store, artifact)

        # ── Step 1: POST /api/debate ─────────────────────────────────────────────
        with patch(
            "finrobot.routes.debate.build_debate_agents",
            return_value=_e2e_stub_agents(),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/debate",
                    json={"ticker": "NVDA", "artifact_id": "e2e-art-01"},
                )

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert "run_id" in body, f"Response missing run_id: {body}"
        run_id: str = body["run_id"]

        # ── Step 2: wait for background task ────────────────────────────────────
        # The route registers the task in app.state.run_tasks[run_id] before
        # returning.  Awaiting it directly avoids any timing-based sleep.
        bg_task = app.state.run_tasks.get(run_id)
        if bg_task is not None:
            await asyncio.gather(bg_task, return_exceptions=True)
        else:
            # Task already completed and was popped from run_tasks by the finally
            # block.  A brief yield lets any residual coroutine scheduling finish.
            await asyncio.sleep(0.05)

        # ── Step 3: read events from real RunStore ───────────────────────────────
        stored = await run_store.get_events_after(run_id, last_seq=0)
        events: list[dict[str, Any]] = [se.event for se in stored]  # type: ignore[assignment]

        # ── Assertion 1: at least 1 debate.point ────────────────────────────────
        point_events = [e for e in events if e.get("event") == "debate.point"]
        assert len(point_events) >= 1, (
            f"Expected ≥1 debate.point events, got 0. All events: "
            f"{[e.get('event') for e in events]}"
        )

        # ── Assertion 2: exactly 1 debate.verdict with call="HOLD" ──────────────
        verdict_events = [e for e in events if e.get("event") == "debate.verdict"]
        assert len(verdict_events) == 1, (
            f"Expected exactly 1 debate.verdict, got {len(verdict_events)}. "
            f"All events: {[e.get('event') for e in events]}"
        )
        assert (
            verdict_events[0]["call"] == "HOLD"
        ), f"Expected verdict call=HOLD, got {verdict_events[0]['call']!r}"

        # ── Assertion 3: ungrounded bull argument → verified=False ──────────────
        # The bull stub has one Argument with evidence_ids=[] → verifier must mark
        # it verified=False.  This is the core correctness invariant for Task 9.
        bull_points = [e for e in point_events if e.get("side") == "bull"]
        ungrounded = [e for e in bull_points if e.get("evidence_ids") == []]
        assert len(ungrounded) == 1, (
            f"Expected exactly 1 ungrounded bull argument, found {len(ungrounded)}. "
            f"Bull points: {bull_points}"
        )
        assert (
            ungrounded[0]["verified"] is False
        ), f"Ungrounded bull argument must have verified=False, got {ungrounded[0]['verified']!r}"

        # ── Assertion 4: grounded bull argument → verified=True ─────────────────
        grounded_bull = [e for e in bull_points if _EV_UPSIDE in (e.get("evidence_ids") or [])]
        assert len(grounded_bull) == 1, (
            f"Expected 1 grounded bull argument citing {_EV_UPSIDE!r}, "
            f"found {len(grounded_bull)}. Bull points: {bull_points}"
        )
        assert (
            grounded_bull[0]["verified"] is True
        ), f"Grounded bull argument must have verified=True, got {grounded_bull[0]['verified']!r}"

        # ── Assertion 5: grounded bear argument → verified=True ─────────────────
        bear_points = [e for e in point_events if e.get("side") == "bear"]
        grounded_bear = [e for e in bear_points if _EV_WEIGHTED in (e.get("evidence_ids") or [])]
        assert len(grounded_bear) == 1, (
            f"Expected 1 grounded bear argument citing {_EV_WEIGHTED!r}, "
            f"found {len(grounded_bear)}. Bear points: {bear_points}"
        )
        assert (
            grounded_bear[0]["verified"] is True
        ), f"Grounded bear argument must have verified=True, got {grounded_bear[0]['verified']!r}"

        # ── Assertion 6: run status == "completed" ───────────────────────────────
        run_record = await run_store.get_run(run_id)
        assert run_record is not None, f"Run {run_id!r} not found in RunStore"
        assert run_record.status == "completed", (
            f"Expected run status 'completed', got {run_record.status!r}. "
            f"Error field: {run_record.error!r}"
        )

        # ── Assertion 7: run_tasks cleaned up ───────────────────────────────────
        # The finally block in _run_debate_task pops run_id from run_tasks.
        assert (
            run_id not in app.state.run_tasks
        ), f"run_id {run_id!r} still in run_tasks after task completion"

    finally:
        # Close the aiosqlite connection inside the still-live event loop so
        # the worker thread exits cleanly.  Without this, aiosqlite's thread
        # tries to signal the loop after teardown and emits
        # PytestUnhandledThreadExceptionWarning (same pattern as conftest.py's
        # _close_quote_cache_singleton_between_tests fixture).
        await run_store.close()
