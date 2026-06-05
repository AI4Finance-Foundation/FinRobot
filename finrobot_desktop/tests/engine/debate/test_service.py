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
from finrobot.engine.debate.service import (
    _format_evidence_context,
    _strings,
    run_debate,
)


def test_evidence_context_renders_assumption_prefix() -> None:
    """A valuation number must reach the agents with its load-bearing assumptions
    inline — a $73 DCF mid is never fed naked (the core $73-needs-its-prefix fix)."""
    es = EvidenceSet(
        ticker="NVDA",
        artifact_id="run-1",
        current_price=211.14,
        reliable=True,
        items=[
            Evidence(
                evidence_id="method.dcf.mid",
                label="dcf 中值估值",
                value=73.44,
                unit="$",
                provenance={"assumptions": "WACC 16.6% · 5年增长 40%→2.5% · β2.24"},
            ),
            Evidence(evidence_id="bare", label="无假设项", value=1.0, unit="x"),
        ],
    )
    ctx = _format_evidence_context(es, _strings("zh"))
    assert "73.44$（WACC 16.6% · 5年增长 40%→2.5% · β2.24）" in ctx
    # An evidence item without assumptions renders no parenthetical — no fabrication.
    assert "无假设项 = 1.0x\n" in ctx + "\n"


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
    # debate.evidence must be the first emitted event
    assert emitted[0]["event"] == "debate.evidence"


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


# ── Test: debate.evidence is first event with correct payload ────────────────


async def test_debate_evidence_emitted_first_with_correct_payload() -> None:
    """debate.evidence must be the first emitted event and carry full evidence
    payload: items list, current_price, reliable flag, and ticker."""
    evidence_items = [
        Evidence(
            evidence_id="dcf.fair_value",
            label="DCF Fair Value",
            value=210.5,
            unit="$",
            formula_id="dcf_v1",
        ),
        Evidence(
            evidence_id="comps.ev_ebitda",
            label="EV/EBITDA",
            value=41.0,
            unit="x",
        ),
    ]
    es = EvidenceSet(
        ticker="AAPL",
        artifact_id="artifact-99",
        current_price=195.0,
        reliable=True,
        items=evidence_items,
    )
    agents = _agents_for(
        bull_output=SideCase(side="bull", arguments=[]),
        bear_output=SideCase(side="bear", arguments=[]),
        judge_output=Verdict(call="BUY", conviction=0.8, swing_factor="f", change_my_mind="m"),
    )
    emitted: list[dict] = []

    async def _emit(ev: dict) -> None:
        emitted.append(ev)

    await run_debate(es, agents, emit=_emit)

    assert len(emitted) >= 1
    ev = emitted[0]
    assert ev["event"] == "debate.evidence"
    assert ev["ticker"] == "AAPL"
    assert ev["current_price"] == 195.0
    assert ev["reliable"] is True
    # items should be serialised dicts with evidence_id keys
    assert len(ev["items"]) == 2
    ids = {item["evidence_id"] for item in ev["items"]}
    assert ids == {"dcf.fair_value", "comps.ev_ebitda"}
    # downstream events still arrive (debate.point and debate.verdict)
    event_types = [e["event"] for e in emitted]
    assert "debate.verdict" in event_types


async def test_debate_evidence_reliable_false_propagated() -> None:
    """debate.evidence carries reliable=False when evidence_set.reliable=False."""
    es = EvidenceSet(
        ticker="X",
        artifact_id="r",
        current_price=10.0,
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

    await run_debate(es, agents, emit=_emit)

    evidence_event = emitted[0]
    assert evidence_event["event"] == "debate.evidence"
    assert evidence_event["reliable"] is False
    assert evidence_event["items"] == []


# ── Test: debate language follows the lang arg (artifact.meta.language) ──────


class _CapturingAgent:
    """Stub that records the prompt it was run with, so we can assert the
    debate prose language without an LLM call."""

    def __init__(self, output: SideCase | Verdict) -> None:
        self._output = output
        self.prompt: str | None = None

    async def run(self, prompt: str, deps: object = None) -> object:
        self.prompt = prompt

        class _Result:
            pass

        r = _Result()
        r.output = self._output  # type: ignore[attr-defined]
        return r


def _capturing_agents() -> dict[str, _CapturingAgent]:
    return {
        "bull": _CapturingAgent(
            SideCase(side="bull", arguments=[Argument(claim="up", evidence_ids=["e1"])])
        ),
        "bear": _CapturingAgent(
            SideCase(side="bear", arguments=[Argument(claim="down", evidence_ids=[])])
        ),
        "judge": _CapturingAgent(
            Verdict(call="HOLD", conviction=0.5, swing_factor="x", change_my_mind="y")
        ),
    }


async def test_debate_lang_en_renders_english_prompts() -> None:
    es = EvidenceSet(
        ticker="AAPL",
        artifact_id="r",
        current_price=150,
        reliable=True,
        items=[Evidence(evidence_id="e1", label="DCF target", value=185, unit="")],
    )
    agents = _capturing_agents()

    async def _noop_emit(ev: dict) -> None:
        pass

    await run_debate(es, agents, emit=_noop_emit, lang="en")

    judge_prompt = agents["judge"].prompt or ""
    assert "Current price" in judge_prompt
    assert "Respond in English" in judge_prompt
    assert "[BULL]" in judge_prompt and "[BEAR]" in judge_prompt
    # No Chinese debate chrome leaked through.
    assert "当前价格" not in judge_prompt and "多方" not in judge_prompt


async def test_debate_lang_zh_renders_chinese_prompts() -> None:
    es = EvidenceSet(
        ticker="AAPL",
        artifact_id="r",
        current_price=150,
        reliable=True,
        items=[Evidence(evidence_id="e1", label="DCF target", value=185, unit="")],
    )
    agents = _capturing_agents()

    async def _noop_emit(ev: dict) -> None:
        pass

    # zh is a retained i18n path (the app ships English-only, but the bilingual
    # debate-string table stays for future re-enablement) — pass it explicitly.
    await run_debate(es, agents, emit=_noop_emit, lang="zh")

    judge_prompt = agents["judge"].prompt or ""
    assert "当前价格" in judge_prompt
    assert "简体中文" in judge_prompt
    assert "[多方]" in judge_prompt and "[空方]" in judge_prompt
