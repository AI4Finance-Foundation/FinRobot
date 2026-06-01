"""IC debate orchestration service (ADR-0007, Task 6).

Execution order:
  1. Format evidence context text from EvidenceSet.
  2. bull / bear agents run in parallel via asyncio.gather.
  3. verify_arguments for both sides.
  4. emit debate.point events for each verified argument.
  5. Judge agent receives consolidated prompt and returns Verdict.
  6. Reliable gate: if evidence_set.reliable is False, force call="REVIEW"
     and conviction=None regardless of what the judge produced.
  7. emit debate.verdict event.
  8. Return DebateResult.

v1 scope note: divergences is always an empty list in this service.
The DivergencePoint model and recompute_divergence() are implemented and
ready (Task 4), but the tension is this — divergence assumption values
like "WACC bull=8.5% / bear=11%" are numeric, and the agent red-line
forbids LLMs from producing numbers.  The deterministic source for those
values (e.g. reusing the DCF sensitivity grid's optimistic/pessimistic
corners) requires a separate design decision before wiring in.
That design belongs to v1.1; this service emits an empty divergences list
until that decision is made.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from finrobot.engine.debate.models import (
    DebateResult,
    EvidenceSet,
    Verdict,
    VerifiedArgument,
)
from finrobot.engine.debate.verifier import verify_arguments

logger = logging.getLogger(__name__)


def _format_evidence_context(evidence_set: EvidenceSet) -> str:
    """Render EvidenceSet as a numbered list for LLM consumption.

    Format per line:  <evidence_id>: <label> = <value><unit>
    If the set is empty the function returns a notice string so agents
    still receive a defined context block.
    """
    if not evidence_set.items:
        return "（本次无确定性证据可引用）"

    lines: list[str] = ["确定性证据列表（仅可通过 evidence_id 引用，禁止编造数字）："]
    for ev in evidence_set.items:
        lines.append(f"  {ev.evidence_id}: {ev.label} = {ev.value}{ev.unit}")
    return "\n".join(lines)


async def run_debate(
    evidence_set: EvidenceSet,
    agents: dict[str, Any],
    emit: Callable[[dict[str, Any]], None],
    deps: Any = None,
) -> DebateResult:
    """Orchestrate one full IC debate session.

    Parameters
    ----------
    evidence_set:
        Deterministic evidence produced by engine/compute for this artifact.
        ``evidence_set.reliable`` controls the data-health gate.
    agents:
        Dict with keys "bull", "bear", "judge" — each a pydantic-ai Agent
        (or a compatible stub).  Produced by build_debate_agents().
    emit:
        SSE sink.  Called with a plain dict for every debate.point and the
        final debate.verdict.  Exceptions from emit propagate to the caller
        (route layer handles run.failed).
    deps:
        Optional FinRobotDeps passed through to each agent.run() call.

    Returns
    -------
    DebateResult
        Complete typed result for this debate.  divergences is always []
        in v1 (see module-level docstring for the design rationale).
    """
    evidence_ctx = _format_evidence_context(evidence_set)

    # ── Step 2: bull / bear run in parallel ─────────────────────────────────
    side_prompt = (
        f"Ticker: {evidence_set.ticker}\n当前价格: {evidence_set.current_price}\n\n{evidence_ctx}"
    )

    bull_result, bear_result = await asyncio.gather(
        agents["bull"].run(side_prompt, deps=deps),
        agents["bear"].run(side_prompt, deps=deps),
    )

    bull_case = bull_result.output
    bear_case = bear_result.output

    # ── Step 3: verify arguments ─────────────────────────────────────────────
    verified_bull: list[VerifiedArgument] = verify_arguments(
        "bull", bull_case.arguments, evidence_set
    )
    verified_bear: list[VerifiedArgument] = verify_arguments(
        "bear", bear_case.arguments, evidence_set
    )

    # ── Step 4: emit debate.point for each verified argument ─────────────────
    for va in verified_bull + verified_bear:
        emit(
            {
                "event": "debate.point",
                "side": va.side,
                "claim": va.claim,
                "evidence_ids": va.evidence_ids,
                "verified": va.verified,
                "reason": va.reason,
            }
        )

    # ── Step 5: judge ────────────────────────────────────────────────────────
    def _render_side(label: str, args: list[VerifiedArgument]) -> str:
        if not args:
            return f"[{label}] 无论点"
        lines = [f"[{label}]"]
        for i, va in enumerate(args, 1):
            status = "已核验" if va.verified else "未核验"
            lines.append(f"  {i}. {va.claim} [{status}] 证据: {va.evidence_ids or '无'}")
        return "\n".join(lines)

    judge_prompt = (
        f"Ticker: {evidence_set.ticker}  当前价格: {evidence_set.current_price}\n\n"
        f"{evidence_ctx}\n\n"
        "以下是多空双方已经过核验的论点，请综合判断并给出 Verdict：\n\n"
        f"{_render_side('多方', verified_bull)}\n\n"
        f"{_render_side('空方', verified_bear)}"
    )

    judge_result = await agents["judge"].run(judge_prompt, deps=deps)
    verdict: Verdict = judge_result.output

    # ── Step 6: reliable gate ────────────────────────────────────────────────
    # Mirror the gate_failed pattern in equity_research.py:814.
    # If the evidence is unreliable, the judge's call is meaningless — force
    # REVIEW and strip conviction so callers cannot act on an untrustworthy number.
    if not evidence_set.reliable:
        if verdict.call != "REVIEW" or verdict.conviction is not None:
            logger.warning(
                "Debate reliable-gate TRIPPED — forcing call=REVIEW, conviction=None "
                "(judge produced call=%s, conviction=%s)",
                verdict.call,
                verdict.conviction,
            )
        verdict = verdict.model_copy(update={"call": "REVIEW", "conviction": None})

    # ── Step 7: emit debate.verdict ──────────────────────────────────────────
    emit(
        {
            "event": "debate.verdict",
            "call": verdict.call,
            "conviction": verdict.conviction,
            "swing_factor": verdict.swing_factor,
            "change_my_mind": verdict.change_my_mind,
        }
    )

    # ── Step 8: return DebateResult ──────────────────────────────────────────
    return DebateResult(
        ticker=evidence_set.ticker,
        artifact_id=evidence_set.artifact_id,
        reliable=evidence_set.reliable,
        bull=verified_bull,
        bear=verified_bear,
        divergences=[],  # v1: empty — see module docstring for design rationale
        verdict=verdict,
    )
