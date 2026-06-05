"""IC debate orchestration service (ADR-0007, Task 6).

Execution order:
  1. Format evidence context text from EvidenceSet.
  1b. emit debate.evidence — push full EvidenceSet to frontend for id→value mapping.
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
from collections.abc import Awaitable, Callable
from typing import Any

from finrobot.engine.debate.models import (
    DebateResult,
    EvidenceSet,
    Verdict,
    VerifiedArgument,
)
from finrobot.engine.debate.verifier import verify_arguments

logger = logging.getLogger(__name__)

# Debate prose strings, keyed by language. The debate's language follows the
# artifact being debated (an English report must get an English debate), NOT the
# viewer's current UI locale — see ADR-0008 and routes/debate.py. The bull/bear/
# judge agent .md files are language-neutral; the language is enforced by the
# instruction appended to each prompt below, the single source of truth.
_DEBATE_STRINGS: dict[str, dict[str, str]] = {
    "zh": {
        "no_evidence": "（本次无确定性证据可引用）",
        "evidence_header": "确定性证据列表（仅可通过 evidence_id 引用，禁止编造数字）：",
        "current_price": "当前价格",
        "no_arguments": "无论点",
        "verified": "已核验",
        "unverified": "未核验",
        "evidence": "证据",
        "none": "无",
        "side_bull": "多方",
        "side_bear": "空方",
        "judge_intro": "以下是多空双方已经过核验的论点，请综合判断并给出 Verdict：",
        "lang_directive": (
            "请用简体中文作答；数字、股票代码与金融缩写（WACC、DCF、EV、EBITDA、FCF、P/E）保留英文/原样。"
        ),
    },
    "en": {
        "no_evidence": "(No deterministic evidence available to cite.)",
        "evidence_header": (
            "Deterministic evidence (cite only by evidence_id; never fabricate numbers):"
        ),
        "current_price": "Current price",
        "no_arguments": "no arguments",
        "verified": "verified",
        "unverified": "unverified",
        "evidence": "evidence",
        "none": "none",
        "side_bull": "BULL",
        "side_bear": "BEAR",
        "judge_intro": (
            "Below are the verified arguments from both sides. "
            "Synthesize them and produce a Verdict:"
        ),
        "lang_directive": (
            "Respond in English. Keep all numbers, ticker symbols, and financial "
            "acronyms (WACC, DCF, EV, EBITDA, FCF, P/E) as-is."
        ),
    },
}


def _strings(lang: str) -> dict[str, str]:
    return _DEBATE_STRINGS["zh"] if lang == "zh" else _DEBATE_STRINGS["en"]


def _format_evidence_context(evidence_set: EvidenceSet, s: dict[str, str]) -> str:
    """Render EvidenceSet as a numbered list for LLM consumption.

    Format per line:  <evidence_id>: <label> = <value><unit>
    If the set is empty the function returns a notice string so agents
    still receive a defined context block.
    """
    if not evidence_set.items:
        return s["no_evidence"]

    lines: list[str] = [s["evidence_header"]]
    for ev in evidence_set.items:
        line = f"  {ev.evidence_id}: {ev.label} = {ev.value}{ev.unit}"
        # Append the load-bearing assumptions so the agents never see a valuation
        # number naked — a $73 DCF mid arrives as "…= 73.44$（WACC 16.6% · 5年增长
        # 40%→2.5% · β2.24）", making the price visibly conditional on its inputs.
        assumptions = (ev.provenance or {}).get("assumptions")
        if assumptions:
            line += f"（{assumptions}）"
        lines.append(line)
    return "\n".join(lines)


async def run_debate(
    evidence_set: EvidenceSet,
    agents: dict[str, Any],
    emit: Callable[[dict[str, Any]], Awaitable[None]],
    deps: Any = None,
    lang: str = "en",
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
        Async SSE sink.  Awaited for every debate.point and the final
        debate.verdict, so events reach the RunStore (and the SSE stream)
        in real-time as the debate progresses rather than buffered to the end.
        Exceptions from emit propagate to the caller (route layer handles
        run.failed).
    deps:
        Optional FinRobotDeps passed through to each agent.run() call.
    lang:
        Output language ('zh'|'en'). Follows the debated artifact's
        meta.language, NOT the viewer's UI locale, so an English report yields
        an English debate (see routes/debate.py). Defaults to 'en'.

    Returns
    -------
    DebateResult
        Complete typed result for this debate.  divergences is always []
        in v1 (see module-level docstring for the design rationale).
    """
    s = _strings(lang)
    evidence_ctx = _format_evidence_context(evidence_set, s)

    # ── Step 1b: emit debate.evidence — id→value map for the frontend ────────
    # Emitted before bull/bear so the frontend can resolve evidence_id→value
    # when rendering debate.point events (which only carry evidence_ids).
    # run_id is injected by the route's emit closure, not here.
    await emit(
        {
            "event": "debate.evidence",
            "ticker": evidence_set.ticker,
            "current_price": evidence_set.current_price,
            "reliable": evidence_set.reliable,
            "items": [e.model_dump() for e in evidence_set.items],
        }
    )

    # ── Step 2: bull / bear run in parallel ─────────────────────────────────
    side_prompt = (
        f"Ticker: {evidence_set.ticker}\n{s['current_price']}: {evidence_set.current_price}\n\n"
        f"{evidence_ctx}\n\n{s['lang_directive']}"
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
        await emit(
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
            return f"[{label}] {s['no_arguments']}"
        lines = [f"[{label}]"]
        for i, va in enumerate(args, 1):
            status = s["verified"] if va.verified else s["unverified"]
            ev_ids = va.evidence_ids or s["none"]
            lines.append(f"  {i}. {va.claim} [{status}] {s['evidence']}: {ev_ids}")
        return "\n".join(lines)

    judge_prompt = (
        f"Ticker: {evidence_set.ticker}  {s['current_price']}: {evidence_set.current_price}\n\n"
        f"{evidence_ctx}\n\n"
        f"{s['judge_intro']}\n\n"
        f"{_render_side(s['side_bull'], verified_bull)}\n\n"
        f"{_render_side(s['side_bear'], verified_bear)}\n\n"
        f"{s['lang_directive']}"
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
    await emit(
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
