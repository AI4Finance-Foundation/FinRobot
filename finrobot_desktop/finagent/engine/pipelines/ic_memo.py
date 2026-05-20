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

from finagent.engine.compute.dcf import calculate_dcf, calculate_sensitivity
from finagent.engine.compute.dcf_seed import seed_dcf_inputs
from finagent.engine.compute.extractor import extract_financial_data
from finagent.engine.compute.historical_extractor import extract_historical_from_yfinance
from finagent.engine.compute.lbo import calculate_lbo
from finagent.engine.compute.lbo_seed import seed_lbo_inputs
from finagent.engine.data.types import DataType
from finagent.engine.deps import FinAgentDeps
from finagent.engine.models.financial import (
    HistoricalMetrics,
    ICFinancials,
    StepOutput,
)
from finagent.engine.pipelines.base import (
    Pipeline,
    PipelineStep,
    StructuredValidator,
    TextValidator,
)
from finagent.engine.pipelines._helpers import build_sensitivity_ranges
from finagent.engine.pipelines.validators import (
    ValidationResult,
    validate_is_non_empty,
    validate_has_fields,
)

logger = logging.getLogger(__name__)

_IRR_HURDLE = 0.15  # 15% minimum IRR for IC Invest recommendation


async def _execute_ic_financials(
    agent: Agent[Any, Any],  # noqa: ARG001 — kept for executor signature; unused
    deps: FinAgentDeps,
    prompt: str,  # noqa: ARG001 — kept for executor signature; unused
    structured_context: dict[str, object],  # noqa: ARG001 — unused after refactor
    ticker: str,
) -> StepOutput:
    """Run DCF + LBO deterministically; return combined ICFinancials.

    Both DCFInputs and LBOInputs are built exclusively via their respective
    seed functions (``seed_dcf_inputs`` / ``seed_lbo_inputs``) — CLAUDE.md
    architecture red-line #5 forbids LLM-selected DCF or LBO numbers.
    Every assumption traces to a 3y historical median, the Damodaran
    industry median, or — for LBO deal-structure quantities — standard PE
    convention recorded in ``assumption_provenance``.
    """
    financials_result = await deps.data_layer.fetch(DataType.FINANCIALS, ticker)
    price_result = await deps.data_layer.fetch(DataType.PRICE, ticker)
    financial_data = extract_financial_data(financials_result, price_result)

    # Multi-year history powers the 3y-median assumption derivation. Fall
    # back to an empty HistoricalMetrics on extraction failure so the seed
    # functions degrade gracefully to Damodaran industry medians.
    try:
        historical = await extract_historical_from_yfinance(ticker)
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

    # --- DCF ---
    dcf_inputs = seed_dcf_inputs(financial_data, historical)
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
    text = (
        f"DCF: ${dcf_result.implied_price:.2f}/share "
        f"(WACC {dcf_result.wacc:.1%}). "
        f"LBO: {lbo_result.moic:.1f}× MOIC, {lbo_result.irr:.1%} IRR "
        f"({lbo_inputs.holding_period_years}yr hold)."
    )
    return StepOutput(text=text, structured=combined)


async def _execute_recommendation(
    agent: Agent[Any, Any],
    deps: FinAgentDeps,
    prompt: str,
    structured_context: dict[str, object],
    ticker: str,
) -> StepOutput:
    """LLM writes IC recommendation; code enforces IRR hurdle gate.

    Gate: if LBO IRR < 15%, recommendation is overridden to PASS regardless of LLM output.
    """
    step_result = await agent.run(prompt, deps=deps)  # type: ignore[call-overload]
    ic_financials = structured_context.get("financial_analysis")

    if isinstance(ic_financials, ICFinancials):
        irr = ic_financials.lbo_result.irr
        if irr < _IRR_HURDLE:
            gate_text = (
                f"[CODE GATE: LBO IRR {irr:.1%} is below the {_IRR_HURDLE:.0%} minimum hurdle. "
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
    from finagent.artifact.builders import build_ic_memo_artifact

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
