"""DCF pipeline — deterministic from real filings.

Previously this pipeline used a pydantic-ai agent to select DCFInputs from a
prompt, which produced unstable, source-less assumptions (the LLM would pick
EBITDA margin 20% for AAPL on one call and 35% on another). That path is gone.

Now:
  1. ``historical_data``: pull FinancialData snapshot + multi-year history.
  2. ``dcf_calc``: deterministic — calls ``seed_dcf_inputs`` to derive every
     DCF parameter from 3y medians of the company's own filings (or Damodaran
     industry medians as fallback), then runs ``calculate_dcf`` and the
     sensitivity grid.
  3. ``output_gen``: LLM-written natural-language narrative *interpreting*
     the seeded inputs. The LLM never picks numbers — it only explains them.

Pipeline API (CLI / SDK / routes) is unchanged. The behavior change is purely
internal: numbers come from filings, not from LLM guesses.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import Agent

from finrobot.engine.compute.operators.dcf import (
    calculate_dcf,
    calculate_sensitivity,
    margin_swing,
)
from finrobot.engine.compute.operators.dcf_seed import dcf_current_actuals, seed_dcf_inputs
from finrobot.engine.compute.operators.forward_estimates import get_forward_revenue_growth
from finrobot.engine.compute.coordinators.extractor import normalize_financials_to_usd
from finrobot.engine.compute.operators.wacc import calculate_wacc
from finrobot.engine.compute.coordinators.historical_extractor import (
    fetch_historical_metrics,
)
from finrobot.engine.data.types import DataType
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.models.financial import FinancialData, StepOutput
from finrobot.engine.primitives.industry import (
    is_balance_sheet_financial,
    is_commodity_cyclical,
)
from finrobot.engine.pipelines._helpers import (
    build_sensitivity_ranges,
    execute_financial_data_step,
)
from finrobot.engine.pipelines.base import (
    Pipeline,
    PipelineStep,
    StructuredValidator,
    TextValidator,
)
from finrobot.engine.pipelines.validators import (
    validate_has_fields,
    validate_is_non_empty,
    validate_dcf_output,
    validate_financial_data,
    validate_dcf_result,
)

logger = logging.getLogger(__name__)


async def _execute_dcf_calc(
    agent: Agent[Any, Any],  # noqa: ARG001 — kept for executor signature; unused
    deps: FinRobotDeps,
    prompt: str,  # noqa: ARG001 — kept for executor signature; unused
    structured_context: dict[str, object],
    ticker: str,
    **_kwargs: object,
) -> StepOutput:
    """Deterministic DCF: seed inputs from real filings, compute, sensitivity.

    No LLM call. Every assumption traces to either the company's own 3y
    historical median or a Damodaran industry median; see ``seed_dcf_inputs``
    for the full precedence ladder. The ``assumption_provenance`` dict on
    DCFInputs carries a Chinese explanation per field, rendered by the UI
    when the user clicks "展开专家详情".
    """
    financial_data = structured_context.get("historical_data")
    if not isinstance(financial_data, FinancialData):
        raise ValueError(
            "dcf_calc requires FinancialData from the historical_data step "
            "but received: " + type(financial_data).__name__
        )

    # Financial-sector issuers (banks / risk-carrying insurers) cannot be valued
    # with an FCF-DCF: free cash flow and the net-debt bridge are ill-defined when
    # deposits / float / reserves ARE the operating raw material, not capital
    # structure. is_balance_sheet_financial is the SINGLE authority the full report
    # uses to suppress the cash-flow methods (it leads with P/B · DDM there, see
    # valuation_aggregator). Degrade to a text-only step BEFORE seeding — never emit
    # a structurally meaningless implied price — mirroring the Gordon-undefined skip
    # below and keeping the bank/insurer pointed at the methods that DO apply. Done
    # here (not just at synthesis) because the standalone DCF artifact IS the DCF:
    # there is no football field to suppress the row in.
    if is_balance_sheet_financial(
        industry=financial_data.market.industry, sector=financial_data.market.sector
    ):
        logger.info("DCF not applicable for %s: balance-sheet financial issuer", ticker)
        return StepOutput(
            text=(
                f"DCF not applicable: {ticker} is a financial-sector issuer (bank / insurer). "
                f"Free cash flow and the net-debt bridge are ill-defined for balance-sheet "
                f"financials — deposits / float / reserves are operating raw material, not "
                f"capital structure. Use a dividend-discount model (DDM) or relative valuation "
                f"(P/B · P/E) instead."
            ),
            structured=None,
        )

    # Multi-year history powers the 3y-median assumption derivation.
    historical = await fetch_historical_metrics(deps.data_layer, ticker)

    # FX-normalize a foreign issuer's financials to canonical USD before seeding so
    # a TWD numerator never mixes with the USD market_cap/shares (BUG-073). No-op
    # for US issuers (both currency tags USD).
    financial_data = await normalize_financials_to_usd(
        financial_data, fmp_api_key=getattr(deps.settings, "fmp_api_key", None)
    )
    # Write the USD-normalized snapshot BACK so build_dcf_artifact's raw_data
    # (→ entry_price via summary_extractor) is the SAME currency as the USD DCF
    # implied_price/target. Without it a foreign issuer's entry stayed native
    # (NT$1000) while the target was USD (~$31), so the coverage signal lamp /
    # hit-rate compared a cross-currency entry-vs-target (BUG-073 caliber drift).
    # equity_research already does this via data_collection; the standalone DCF
    # pipeline did not. No-op for US issuers (normalize returns the same object).
    structured_context["historical_data"] = financial_data
    # Stage-1 growth seed: analyst consensus over a backward-looking trailing CAGR,
    # the same authoritative path equity_research uses — the historical_data step
    # already fetched forward_estimates_raw into structured_context (shared dict).
    # Best-effort: a miss → [] → seed falls back to trailing CAGR.
    forward_raw = structured_context.get("forward_estimates_raw")
    forward_growth = (
        get_forward_revenue_growth(forward_raw) if isinstance(forward_raw, dict) else []
    )
    # Commodity-cyclical (memory/storage/steel/oil…) → through-cycle earnings
    # normalization in the seed so the DCF anchors on normalized through-cycle
    # earnings power, not whatever phase the cycle is in now. Ticker anchor covers
    # memory under the generic "Semiconductors" tag; industry covers the rest.
    cyclical = is_commodity_cyclical(
        industry=financial_data.market.industry,
        sector=financial_data.market.sector,
        ticker=ticker,
    )
    dcf_inputs = seed_dcf_inputs(
        financial_data, historical, forward_growth=forward_growth, cyclical=cyclical
    )

    # Gordon Growth terminal value is undefined when terminal growth >= WACC,
    # which arises for very low-WACC profiles (low-beta, high-leverage utilities /
    # REITs). Degrade gracefully — emit a text-only step stating DCF is not
    # applicable rather than letting calculate_dcf raise and crash the whole run.
    # build_dcf_artifact tolerates the missing DCFResult; the report falls back to
    # relative valuation.
    _, wacc = calculate_wacc(
        dcf_inputs.risk_free_rate,
        dcf_inputs.beta,
        dcf_inputs.equity_risk_premium,
        dcf_inputs.cost_of_debt,
        dcf_inputs.tax_rate,
        dcf_inputs.debt_ratio,
    )
    if dcf_inputs.terminal_growth_rate >= wacc:
        logger.warning(
            "DCF not applicable for %s: WACC %.4f <= terminal growth %.4f",
            ticker,
            wacc,
            dcf_inputs.terminal_growth_rate,
        )
        return StepOutput(
            text=(
                f"DCF not applicable: WACC {wacc:.1%} is not above the terminal growth "
                f"rate {dcf_inputs.terminal_growth_rate:.1%}, leaving the Gordon perpetual-"
                f"growth model undefined in this case. This issuer skips the DCF valuation; "
                f"rely on relative valuation (peer multiples, historical valuation range)."
            ),
            structured=None,
        )

    dcf_result = calculate_dcf(dcf_inputs)
    wacc_range, tg_range = build_sensitivity_ranges(
        dcf_result.wacc, dcf_result.inputs.terminal_growth_rate
    )
    sensitivity = calculate_sensitivity(dcf_inputs, wacc_range=wacc_range, tg_range=tg_range)
    # Symmetric with the equity_research report path: the ±2pp margin swing and the
    # latest-year driver actuals feed the same reconciliation table + swing note the
    # tool page reuses via SensitivityBody. Both degrade gracefully to None.
    current_actuals, capex_is_ttm = dcf_current_actuals(financial_data, historical)
    dcf_result = dcf_result.model_copy(
        update={
            "sensitivity_table": sensitivity,
            "margin_swing": margin_swing(dcf_inputs),
            "assumption_current_actuals": current_actuals,
            "assumption_current_actuals_fy": (historical.years[-1] if historical.years else None),
            "assumption_current_actuals_capex_ttm": capex_is_ttm,
        }
    )

    valid_prices = [
        p for row in sensitivity["implied_prices"] for p in row if p is not None and p > 0
    ]
    price_range = f"${min(valid_prices):.0f}–${max(valid_prices):.0f}" if valid_prices else "N/A"
    narrative = (
        f"DCF implies ${dcf_result.implied_price:.2f} per share. "
        f"WACC: {dcf_result.wacc:.1%}. EV: ${dcf_result.enterprise_value / 1e9:.1f}B. "
        f"Sensitivity: {price_range}."
    )
    return StepOutput(text=narrative, structured=dcf_result)


def create_dcf_pipeline(agents: dict[str, Agent]) -> Pipeline:
    """3-step deterministic DCF pipeline.

    Step 1 ``historical_data`` pulls financial data + price. Step 2 ``dcf_calc``
    is deterministic — runs seed_dcf_inputs + calculate_dcf without any LLM
    call. Step 3 ``output_gen`` is the only LLM step; it produces a natural
    language narrative explaining the seeded assumptions and result.
    """
    from finrobot.artifact.builders import build_dcf_artifact

    return Pipeline(
        artifact_builder=build_dcf_artifact,
        steps=[
            PipelineStep(
                name="historical_data",
                skill_section=None,
                agent=agents["data"],
                required_data=[DataType.FINANCIALS, DataType.PRICE],
                validator=StructuredValidator(
                    validate_financial_data,
                    lambda out: validate_has_fields(out, ["revenue", "ebitda"]),
                ),
                executor=execute_financial_data_step,
                # dcf_calc reads this FinancialData — abort if it fails.
                critical=True,
            ),
            PipelineStep(
                name="dcf_calc",
                skill_section="dcf-model",
                agent=agents["modeling"],
                required_data=[],
                validator=StructuredValidator(validate_dcf_result, validate_is_non_empty),
                executor=_execute_dcf_calc,
                # Deterministic seed_dcf_inputs + calculate_dcf — ignores the
                # re-prompt, so a validation failure can't change on retry (BUG-059).
                deterministic=True,
            ),
            PipelineStep(
                name="output_gen",
                skill_section="dcf-model",
                agent=agents["report"],
                required_data=[],
                validator=TextValidator(validate_dcf_output),
            ),
        ],
    )
