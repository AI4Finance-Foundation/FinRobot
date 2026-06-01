"""Tests for debate orchestration service (Task 6).

asyncio_mode = "auto" (pyproject.toml) — no @pytest.mark.asyncio needed.
Stub agents replace real pydantic-ai Agents; no LLM call is made.
"""

from __future__ import annotations

from finrobot.engine.debate.models import (
    Argument,
    DebateResult,
    Evidence,
    EvidenceSet,
    SideCase,
    Verdict,
)
from finrobot.engine.debate.service import run_debate


class _StubAgent:
    """Minimal agent stub: returns a fixed output without any LLM call."""

    def __init__(self, output: SideCase | Verdict) -> None:
        self._output = output

    async def run(self, prompt: str, deps: object = None) -> object:
        class _Result:
            pass

        r = _Result()
        r.output = self._output  # type: ignore[attr-defined]  # dynamic stub attribute
        return r


# ── Fixtures ────────────────────────────────────────────────────────────────


def _agents_for(
    bull_output: SideCase,
    bear_output: SideCase,
    judge_output: Verdict,
) -> dict[str, _StubAgent]:
    return {
        "bull": _StubAgent(bull_output),
        "bear": _StubAgent(bear_output),
        "judge": _StubAgent(judge_output),
    }


# ── Test: reliable gate forces REVIEW ───────────────────────────────────────


async def test_unreliable_evidence_forces_review() -> None:
    """When reliable=False the gate must override judge output to REVIEW/None."""
    es = EvidenceSet(
        ticker="X",
        artifact_id="r",
        current_price=10,
        reliable=False,
        items=[],
    )
    agents = _agents_for(
        bull_output=SideCase(side="bull", arguments=[]),
        bear_output=SideCase(side="bear", arguments=[]),
        judge_output=Verdict(call="BUY", conviction=0.9, swing_factor="x", change_my_mind="y"),
    )
    emitted: list[dict] = []

    async def _emit(ev: dict) -> None:
        emitted.append(ev)

    result: DebateResult = await run_debate(es, agents, emit=_emit)

    assert result.verdict.call == "REVIEW"
    assert result.verdict.conviction is None


# ── Test: unsupported bull arg is unverified; valid bear arg is verified ─────


async def test_unsupported_bull_arg_marked_unverified_and_emitted() -> None:
    """Bull arg with no evidence_ids → verified=False; bear arg citing a known
    evidence_id → verified=True.  Both appear in emitted debate.point events.
    """
    es = EvidenceSet(
        ticker="X",
        artifact_id="r",
        current_price=10,
        reliable=True,
        items=[
            Evidence(
                evidence_id="synthesis.upside_downside",
                label="u",
                value=0.1,
                unit="%",
            )
        ],
    )
    agents = _agents_for(
        bull_output=SideCase(
            side="bull",
            arguments=[Argument(claim="护城河无敌", evidence_ids=[])],
        ),
        bear_output=SideCase(
            side="bear",
            arguments=[
                Argument(
                    claim="上行有限",
                    evidence_ids=["synthesis.upside_downside"],
                )
            ],
        ),
        judge_output=Verdict(call="HOLD", conviction=0.5, swing_factor="x", change_my_mind="y"),
    )
    emitted: list[dict] = []

    async def _emit(ev: dict) -> None:
        emitted.append(ev)

    result: DebateResult = await run_debate(es, agents, emit=_emit)

    assert result.bull[0].verified is False
    assert result.bear[0].verified is True
    assert result.verdict.call == "HOLD"
    assert any(e["event"] == "debate.point" for e in emitted)
    assert any(e["event"] == "debate.verdict" for e in emitted)


# ── Test: v1 divergences always empty ───────────────────────────────────────


async def test_divergences_empty_in_v1() -> None:
    """v1 contract: divergences list is always [] — no recompute_divergence call."""
    es = EvidenceSet(
        ticker="NVDA",
        artifact_id="r2",
        current_price=900,
        reliable=True,
        items=[],
    )
    agents = _agents_for(
        bull_output=SideCase(side="bull", arguments=[]),
        bear_output=SideCase(side="bear", arguments=[]),
        judge_output=Verdict(
            call="HOLD", conviction=0.6, swing_factor="growth", change_my_mind="macro"
        ),
    )
    async def _noop_emit(ev: dict) -> None:
        pass

    result: DebateResult = await run_debate(es, agents, emit=_noop_emit)
    assert result.divergences == []


# ── Test: verdict event always emitted ──────────────────────────────────────


async def test_verdict_event_always_emitted() -> None:
    """debate.verdict must appear in emitted events for both reliable=True/False."""
    for reliable in (True, False):
        es = EvidenceSet(
            ticker="T",
            artifact_id="a",
            current_price=5,
            reliable=reliable,
            items=[],
        )
        agents = _agents_for(
            bull_output=SideCase(side="bull", arguments=[]),
            bear_output=SideCase(side="bear", arguments=[]),
            judge_output=Verdict(
                call="SELL",
                conviction=0.3,
                swing_factor="s",
                change_my_mind="c",
            ),
        )
        emitted: list[dict] = []

        async def _emit(ev: dict) -> None:
            emitted.append(ev)

        await run_debate(es, agents, emit=_emit)
        verdict_events = [e for e in emitted if e["event"] == "debate.verdict"]
        assert len(verdict_events) == 1, f"reliable={reliable}: expected 1 verdict event"


# ── Test: result fields wired correctly ─────────────────────────────────────


async def test_result_fields_wired_from_evidence_set() -> None:
    """DebateResult ticker/artifact_id/reliable come from EvidenceSet, not judge."""
    es = EvidenceSet(
        ticker="AAPL",
        artifact_id="artifact-42",
        current_price=195.0,
        reliable=True,
        items=[],
    )
    agents = _agents_for(
        bull_output=SideCase(side="bull", arguments=[]),
        bear_output=SideCase(side="bear", arguments=[]),
        judge_output=Verdict(call="BUY", conviction=0.8, swing_factor="f", change_my_mind="m"),
    )
    async def _noop_emit(ev: dict) -> None:
        pass

    result: DebateResult = await run_debate(es, agents, emit=_noop_emit)
    assert result.ticker == "AAPL"
    assert result.artifact_id == "artifact-42"
    assert result.reliable is True
