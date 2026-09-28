"""LBO analysis pipeline.

4 steps:
  1. data_collection  — fetch financials/price, produce FinancialData
  2. lbo_parameters   — deterministic seed_lbo_inputs() builds LBOInputs from
                        3y historical medians + Damodaran industry fallback
                        (CLAUDE.md red-line #5; no LLM picks numbers)
  3. lbo_calculation  — deterministic calculate_lbo() + sensitivity
  4. lbo_narrative    — LLM writes narrative / investment memo section
                        (narrate-only; never selects numbers)
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import Agent

from finrobot.engine.compute.coordinators.extractor import normalize_financials_to_usd
from finrobot.engine.compute.coordinators.historical_extractor import fetch_historical_metrics
from finrobot.engine.compute.operators.lbo import calculate_lbo
from finrobot.engine.compute.operators.lbo_seed import seed_lbo_inputs
from finrobot.engine.data.types import DataType
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.models.financial import (
    FinancialData,
    HistoricalMetrics,
    LBOInputs,
    LBOResult,
    StepOutput,
)
from finrobot.engine.pipelines.base import (
    Pipeline,
    PipelineStep,
    StructuredValidator,
    TextValidator,
)
from finrobot.engine.pipelines._helpers import execute_financial_data_step
from finrobot.engine.pipelines.validators import (
    validate_financial_data,
    validate_has_fields,
    validate_is_non_empty,
    validate_lbo_inputs,
    validate_lbo_result,
)

logger = logging.getLogger(__name__)


async def _execute_lbo_params(
    agent: Agent[Any, Any],  # noqa: ARG001 — kept for executor signature; unused
    deps: FinRobotDeps,
    prompt: str,  # noqa: ARG001 — kept for executor signature; unused
    structured_context: dict[str, object],
    ticker: str,
    **_kwargs: object,
) -> StepOutput:
    """Deterministic LBO seed: builds LBOInputs from real filings.

    Mirrors the DCF pipeline structure (see ``finrobot.engine.pipelines.dcf``).
    LLM does not pick any LBO assumptions — ``seed_lbo_inputs`` derives every
    numeric field from the ticker's 3y historical median, the Damodaran
    industry median, or — for deal-structure quantities (entry/exit multiples,
    leverage, holding period) that are not financial-statement values — from
    standard PE convention recorded in ``assumption_provenance``.

    Replacing this with an LLM ``param_agent`` would walk back CLAUDE.md
    architecture red-line #5 and is enforced against by
    ``tests/audit/test_lbo_red_lines.py``.
    """
    financial_data = structured_context.get("data_collection")
    if not isinstance(financial_data, FinancialData):
        raise ValueError(
            "lbo_parameters requires FinancialData from the data_collection "
            "step but received: " + type(financial_data).__name__
        )

    historical = structured_context.get("historical_metrics")
    if not isinstance(historical, HistoricalMetrics):
        try:
            historical = await fetch_historical_metrics(deps.data_layer, ticker)
        except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as exc:
            logger.warning(
                "Historical extraction failed for %s: %s — falling back to "
                "Damodaran industry medians via seed_lbo_inputs.",
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

    # FX-normalize a foreign issuer's financials to canonical USD BEFORE seeding
    # so revenue_base / ltm_ebitda (and thus LBOResult.exit_equity / ending_debt)
    # are USD — never the native reporting currency. Without it the football
    # field divides a TWD exit_equity by share count and plots it against a USD
    # current_price (BUG-073 family). ic_memo / equity_research already do this;
    # the standalone LBO pipeline did not. No-op for US issuers. Write back to
    # data_collection so build_lbo_artifact's raw_data (→ entry_price) is USD too.
    financial_data = await normalize_financials_to_usd(
        financial_data, fmp_api_key=getattr(deps.settings, "fmp_api_key", None)
    )
    structured_context["data_collection"] = financial_data

    inputs: LBOInputs = seed_lbo_inputs(financial_data, historical)
    return StepOutput(text=inputs.model_dump_json(), structured=inputs)


async def _execute_lbo_calc(
    agent: Agent[Any, Any],
    deps: FinRobotDeps,
    prompt: str,
    structured_context: dict[str, object],
    ticker: str,
    **_kwargs: object,
) -> StepOutput:
    """Deterministic LBO calculation from LBOInputs."""
    inputs = structured_context.get("lbo_parameters")
    if not isinstance(inputs, LBOInputs):
        raise ValueError("lbo_parameters step must produce LBOInputs structured output")

    result: LBOResult = calculate_lbo(inputs)

    warning_prefix = "".join(
        f"[WARNING: {w}]\n\n"
        for w in (result.irr_formula_warning, result.capital_structure_warning)
        if w
    )
    # moic/irr are None for an impossible structure (entry equity ≤ 0); the
    # capital_structure_warning (already in warning_prefix) explains why. Render
    # N/A instead of crashing the f-string.
    moic_str = f"{result.moic:.1f}×" if result.moic is not None else "N/A"
    irr_str = f"{result.irr:.1%}" if result.irr is not None else "N/A"
    # Equity value floors at 0 under limited liability — a negative exit_equity is a
    # debt shortfall (exit debt exceeds exit EV), NOT negative equity value, so never
    # print a negative dollar equity into the summary. moic=0×/irr=-100% already carry
    # the total-loss signal; add the plain-language wipeout note here.
    if result.exit_equity < 0:
        exit_equity_clause = (
            f"Exit equity: $0M (equity wiped at exit — exit debt exceeds exit enterprise "
            f"value by ${-result.exit_equity / 1e6:.0f}M; LBO not viable at this structure)."
        )
    else:
        exit_equity_clause = f"Exit equity: ${result.exit_equity / 1e6:.0f}M."
    # When the deal does not self-finance (levered FCF negative across the hold →
    # net debt rises on revolver draws instead of amortizing), the MOIC / IRR are
    # exit-multiple artifacts, not achievable returns. Lead the headline with the
    # feasibility verdict and demote the returns to a disclosed footnote rather than
    # reporting them as an unconditional headline. This is NOT a punt (contract ②):
    # the schedule, entry/exit breakdown, ability-to-pay and the returns themselves
    # all stay as traceable outputs — "not feasible as modeled, and why" IS the
    # conclusion.
    ending_debt = result.schedule[-1].ending_debt
    if result.self_financing is False:
        headline = (
            f"LBO not self-financing as modeled: the acquisition debt does not amortize — "
            f"projected levered free cash flow is negative across the hold, so net debt rises "
            f"from ${result.entry_debt / 1e6:.0f}M to ${ending_debt / 1e6:.0f}M on revolver "
            f"draws rather than paying down. The modeled {moic_str} MOIC / {irr_str} IRR over "
            f"{inputs.holding_period_years} years are exit-multiple-dependent (no operating "
            f"deleveraging), not returns a sponsor could underwrite at "
            f"{inputs.leverage_multiple:.1f}× leverage. "
        )
    else:
        headline = (
            f"LBO implies {moic_str} MOIC and {irr_str} IRR over "
            f"{inputs.holding_period_years} years. "
        )
    narrative = (
        f"{warning_prefix}"
        f"{headline}"
        f"Entry equity: ${result.entry_equity / 1e6:.0f}M, "
        f"{exit_equity_clause} "
        f"Entry EV: ${result.entry_ev / 1e6:.0f}M "
        f"({inputs.entry_ev_ebitda:.1f}× EBITDA), "
        f"Entry debt: ${result.entry_debt / 1e6:.0f}M."
    )
    return StepOutput(text=narrative, structured=result)


def create_lbo_pipeline(agents: dict[str, Agent]) -> Pipeline:
    """4-step LBO analysis pipeline factory."""
    from finrobot.artifact.builders import build_lbo_artifact

    return Pipeline(
        artifact_builder=build_lbo_artifact,
        steps=[
            PipelineStep(
                name="data_collection",
                skill_section=None,
                agent=agents["data"],
                required_data=[DataType.FINANCIALS, DataType.PRICE],
                validator=StructuredValidator(
                    validate_financial_data,
                    lambda out: validate_has_fields(out, ["revenue", "ebitda"]),
                ),
                executor=execute_financial_data_step,
                # lbo_parameters/lbo_calculation read this FinancialData — abort
                # if it fails.
                critical=True,
            ),
            PipelineStep(
                name="lbo_parameters",
                skill_section=None,
                agent=agents["modeling"],
                required_data=[],
                validator=StructuredValidator(validate_lbo_inputs, validate_is_non_empty),
                executor=_execute_lbo_params,
                # Deterministic seed_lbo_inputs — ignores the re-prompt (BUG-059).
                deterministic=True,
            ),
            PipelineStep(
                name="lbo_calculation",
                skill_section=None,
                agent=agents["modeling"],
                required_data=[],
                validator=StructuredValidator(validate_lbo_result, validate_is_non_empty),
                executor=_execute_lbo_calc,
                # Deterministic calculate_lbo — ignores the re-prompt (BUG-059).
                deterministic=True,
            ),
            PipelineStep(
                name="lbo_narrative",
                skill_section=None,
                agent=agents["report"],
                required_data=[],
                validator=TextValidator(validate_is_non_empty),
            ),
        ],
    )
