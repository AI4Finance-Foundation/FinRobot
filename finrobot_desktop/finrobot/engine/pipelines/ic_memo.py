"""Investment Committee (IC) Memo pipeline.

5 steps:
  1. situation_overview  — company overview + transaction rationale (LLM)
  2. financial_analysis  — runs DCF + LBO inline via deterministic seed
                            functions (CLAUDE.md red-line #5; no LLM picks
                            DCF or LBO numbers), returns ICFinancials
  3. investment_thesis   — LLM articulates 3-5 key investment considerations
  4. risk_factors        — LLM generates risks, code enforces 3-item structure
  5. recommendation      — LLM verdict, code gate: IRR < 15% forces PASS

What code does that LLM cannot:
  - Deterministic DCF + LBO execution from typed parameter models seeded
    from 3y historical medians and Damodaran industry fallback
  - IRR hurdle gate: overrides LLM recommendation to PASS if IRR < 15%
  - Risk ranking by impact (code ranks by order, not LLM discretion)
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import Agent

from finrobot.engine.compute.operators.dcf import calculate_dcf, calculate_sensitivity
from finrobot.engine.compute.operators.dcf_seed import seed_dcf_inputs
from finrobot.engine.compute.coordinators.extractor import (
    extract_financial_data,
    normalize_financials_to_usd,
)
from finrobot.engine.compute.coordinators.dcf_seed import fetch_forward_growth
from finrobot.engine.compute.coordinators.historical_extractor import fetch_historical_metrics
from finrobot.engine.compute.operators.lbo import calculate_lbo
from finrobot.engine.compute.operators.lbo_seed import seed_lbo_inputs
from finrobot.engine.data.types import DataType
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.models.financial import (
    HistoricalMetrics,
    ICFinancials,
    StepOutput,
)
from finrobot.engine.models.valuation_thresholds import SPONSOR_IRR_HURDLE
from finrobot.engine.pipelines.base import (
    Pipeline,
    PipelineStep,
    StructuredValidator,
    TextValidator,
)
from finrobot.engine.pipelines._helpers import build_sensitivity_ranges
from finrobot.engine.pipelines.validators import (
    ValidationResult,
    validate_is_non_empty,
    validate_has_fields,
)

logger = logging.getLogger(__name__)

# Single authority for the sponsor bar (engine/models/valuation_thresholds) —
# shared with the valuation aggregator's LBO ability-to-pay discounting so the
# IC gate and the football field speak the same hurdle.
_IRR_HURDLE = SPONSOR_IRR_HURDLE


async def _execute_ic_financials(
    agent: Agent[Any, Any],  # noqa: ARG001 — kept for executor signature; unused
    deps: FinRobotDeps,
    prompt: str,  # noqa: ARG001 — kept for executor signature; unused
    structured_context: dict[str, object],  # noqa: ARG001 — unused after refactor
    ticker: str,
    **_kwargs: object,
) -> StepOutput:
    """Run DCF + LBO deterministically; return combined ICFinancials.

    Both DCFInputs and LBOInputs are built exclusively via their respective
    seed functions (``seed_dcf_inputs`` / ``seed_lbo_inputs``) — CLAUDE.md
    architecture red-line #5 forbids LLM-selected DCF or LBO numbers.
    Every assumption traces to a 3y historical median, the Damodaran
    industry median, or — for LBO deal-structure quantities — standard PE
    convention recorded in ``assumption_provenance``.
    """
    _fin = await deps.data_layer.fetch_canonical(DataType.FINANCIALS, ticker)
    _price = await deps.data_layer.fetch_canonical(DataType.PRICE, ticker)
    financial_data = extract_financial_data(_fin, _price)

    # Multi-year history powers the 3y-median assumption derivation. Fall
    # back to an empty HistoricalMetrics on extraction failure so the seed
    # functions degrade gracefully to Damodaran industry medians.
    try:
        historical = await fetch_historical_metrics(deps.data_layer, ticker)
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as exc:
        logger.warning(
            "Historical extraction failed for %s: %s — falling back to industry medians.",
            ticker,
            exc,
        )
        historical = HistoricalMetrics(
            years=[],
            revenue=[],
            revenue_growth_yoy=[],
            cogs=[],
            gross_profit=[],
            gross_margin=[],
            sga=[],
            sga_ratio=[],
            ebitda=[],
            ebitda_margin=[],
            operating_income=[],
            operating_margin=[],
            net_income=[],
            eps=[],
            pe_ratio=[],
            cagr_revenue=None,
            ticker=ticker,
        )

    # FX-normalize a foreign issuer's financials to canonical USD before seeding
    # both models so a TWD revenue/EBITDA/debt never mixes with the USD
    # market_cap (BUG-073). No-op for US issuers. Feeding the USD snapshot to the
    # LBO seed keeps that model internally single-currency-consistent (now USD),
    # not "forced FX" — it never mixed currencies internally to begin with.
    financial_data = await normalize_financials_to_usd(
        financial_data, fmp_api_key=getattr(deps.settings, "fmp_api_key", None)
    )

    # --- DCF ---
    # Stage-1 growth seed: analyst consensus over a backward-looking trailing CAGR,
    # the same authoritative path equity_research / standalone DCF use — so the IC
    # memo's DCF can't print a different fair value than the report for the same
    # ticker. Best-effort: a forward miss → [] → seed falls back to trailing CAGR.
    forward_growth = await fetch_forward_growth(deps.data_layer, ticker)
    dcf_inputs = seed_dcf_inputs(financial_data, historical, forward_growth=forward_growth)
    dcf_result = calculate_dcf(dcf_inputs)
    wacc_range, tg_range = build_sensitivity_ranges(
        dcf_result.wacc, dcf_result.inputs.terminal_growth_rate
    )
    sensitivity = calculate_sensitivity(dcf_inputs, wacc_range=wacc_range, tg_range=tg_range)
    dcf_result = dcf_result.model_copy(update={"sensitivity_table": sensitivity})

    # --- LBO ---
    lbo_inputs = seed_lbo_inputs(financial_data, historical)
    lbo_result = calculate_lbo(lbo_inputs)

    combined = ICFinancials(
        financial_data=financial_data,
        dcf_result=dcf_result,
        lbo_result=lbo_result,
    )
    # moic/irr are None for an impossible structure (entry equity ≤ 0); show N/A
    # rather than crash the f-string (the financials validator rejects that case
    # downstream, but this summary text is built first).
    moic_str = f"{lbo_result.moic:.1f}×" if lbo_result.moic is not None else "N/A"
    irr_str = f"{lbo_result.irr:.1%}" if lbo_result.irr is not None else "N/A"
    text = (
        f"DCF: ${dcf_result.implied_price:.2f}/share "
        f"(WACC {dcf_result.wacc:.1%}). "
        f"LBO: {moic_str} MOIC, {irr_str} IRR "
        f"({lbo_inputs.holding_period_years}yr hold)."
    )
    return StepOutput(text=text, structured=combined)


async def _execute_recommendation(
    agent: Agent[Any, Any],
    deps: FinRobotDeps,
    prompt: str,
    structured_context: dict[str, object],
    ticker: str,
    **_kwargs: object,
) -> StepOutput:
    """LLM writes IC recommendation; code enforces IRR hurdle gate.

    Gate: if LBO IRR < 15%, recommendation is overridden to PASS regardless of LLM output.
    """
    step_result = await agent.run(prompt, deps=deps)
    ic_financials = structured_context.get("financial_analysis")

    if isinstance(ic_financials, ICFinancials):
        irr = ic_financials.lbo_result.irr
        # An undefined IRR (None — impossible capital structure, entry equity ≤ 0)
        # cannot clear the hurdle, so it falls through the same PASS gate.
        if irr is None or irr < _IRR_HURDLE:
            irr_label = f"{irr:.1%}" if irr is not None else "undefined (entry equity ≤ 0)"
            gate_text = (
                f"[CODE GATE: LBO IRR {irr_label} is below the {_IRR_HURDLE:.0%} minimum hurdle. "
                f"Recommendation overridden to: PASS]\n\n"
            )
            return StepOutput(text=gate_text + step_result.output, structured=None)

    return StepOutput(text=step_result.output, structured=None)


def _validate_ic_financials(data: ICFinancials) -> ValidationResult:
    if data.dcf_result.implied_price <= 0:
        return ValidationResult(passed=False, error="DCF implied price must be positive")
    if data.lbo_result.entry_equity <= 0:
        return ValidationResult(passed=False, error="LBO entry equity must be positive")
    return ValidationResult(passed=True)


def create_ic_memo_pipeline(agents: dict[str, Agent]) -> Pipeline:
    """5-step IC Memo pipeline factory."""
    from finrobot.artifact.builders import build_ic_memo_artifact

    return Pipeline(
        artifact_builder=build_ic_memo_artifact,
        steps=[
            PipelineStep(
                name="situation_overview",
                skill_section=None,
                agent=agents["analysis"],
                required_data=[DataType.FINANCIALS, DataType.NEWS],
                validator=TextValidator(
                    lambda out: validate_has_fields(out, ["revenue", "ebitda"])
                ),
            ),
            PipelineStep(
                name="financial_analysis",
                skill_section="dcf-model",
                agent=agents["modeling"],
                required_data=[],
                validator=StructuredValidator(_validate_ic_financials, validate_is_non_empty),
                executor=_execute_ic_financials,
                # The deterministic financial core of the memo. Without
                # ICFinancials the recommendation step's IRR hurdle gate can't
                # run — the LLM's INVEST/PASS would ship UNGATED, which is the
                # exact failure the gate exists to prevent. Abort instead of
                # degrading (same precedent as equity_research's
                # data_collection).
                critical=True,
                # Pure DCF+LBO compute, zero LLM calls — a validation failure
                # re-produces byte-identical output, so retrying burns three
                # full provider re-fetch rounds for no chance of a different
                # result (BUG-059). With critical=True this aborts immediately
                # instead of after the wasted budget.
                deterministic=True,
            ),
            PipelineStep(
                name="investment_thesis",
                skill_section="initiating-coverage",
                agent=agents["synthesis"],
                required_data=[],
                validator=TextValidator(validate_is_non_empty),
            ),
            PipelineStep(
                name="risk_factors",
                skill_section=None,
                agent=agents["analysis"],
                required_data=[],
                validator=TextValidator(lambda out: validate_has_fields(out, ["risk"])),
            ),
            PipelineStep(
                name="recommendation",
                skill_section=None,
                agent=agents["synthesis"],
                required_data=[],
                validator=TextValidator(validate_is_non_empty),
                executor=_execute_recommendation,
            ),
        ],
    )
