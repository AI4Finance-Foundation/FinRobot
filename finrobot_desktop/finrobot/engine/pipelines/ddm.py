"""DDM (Dividend Discount Model) pipeline — for banks and dividend-paying stocks.

4 steps:
  1. historical_data    — fetch financials/price, produce FinancialData
  2. ddm_params         — deterministic: seed_ddm_inputs derives DDMInputs from
                          provider dividend/payout/ROE/beta (no LLM parameter pick)
  3. ddm_calc           — deterministic calculate_ddm() + sensitivity
  4. ddm_narrative      — LLM generates narrative with valuation thesis

Banks don't have meaningful free cash flow, so FCF-DCF produces misleading results.
DDM values the company based on projected dividends discounted at cost of equity.

Previously ``ddm_params`` used a pydantic-ai agent typed to emit DDMInputs that
let the LLM hand-pick dividend growth ("typically 3-8%"), payout, beta, and
terminal growth from a prompt — the same source-less, unstable path DCF/LBO
already removed. Numbers now trace to the company's own filings (or Damodaran
industry medians) via ``seed_ddm_inputs``; the LLM only narrates them.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import Agent

from finrobot.engine.compute.ddm import calculate_ddm, calculate_ddm_sensitivity
from finrobot.engine.compute.ddm_seed import seed_ddm_inputs
from finrobot.engine.data.types import DataType
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.models.financial import DDMInputs, FinancialData, StepOutput
from finrobot.engine.pipelines.base import (
    Pipeline,
    PipelineStep,
    StructuredValidator,
    TextValidator,
)
from finrobot.engine.pipelines._helpers import (
    build_sensitivity_ranges,
    execute_financial_data_step,
)
from finrobot.engine.pipelines.validators import (
    validate_ddm_inputs,
    validate_ddm_output,
    validate_ddm_result,
    validate_financial_data,
    validate_has_fields,
    validate_is_non_empty,
)

logger = logging.getLogger(__name__)


async def _execute_ddm_seed(
    agent: Agent[Any, Any],  # noqa: ARG001 — kept for executor signature; unused
    deps: FinRobotDeps,
    prompt: str,  # noqa: ARG001 — kept for executor signature; unused
    structured_context: dict[str, object],
    ticker: str,
    **_kwargs: object,
) -> StepOutput:
    """Deterministic DDMInputs: seed every assumption from real provider data.

    No LLM call. Dividend, payout, ROE and beta come from the provider snapshot;
    dividend growth is the textbook sustainable rate g = ROE×(1−payout) decayed
    to perpetuity, and the terminal payout is normalized to 1 − tg/ROE. See
    ``seed_ddm_inputs`` for the full precedence ladder; ``assumption_provenance``
    carries a Chinese explanation per field for the UI.

    FinancialData (from the historical_data step) supplies the validated market
    fields; the dividend-specific fields (DPS/payout/ROE/BVPS) are read from the
    same financials DataResult via ``normalize_financials`` — they aren't carried
    on FinancialData. The fetch is cache-served, so this re-fetch is free.
    """
    financial_data = structured_context.get("historical_data")
    if not isinstance(financial_data, FinancialData):
        raise ValueError(
            "ddm_params requires FinancialData from the historical_data step "
            "but received: " + type(financial_data).__name__
        )

    _fin = await deps.data_layer.fetch_canonical(DataType.FINANCIALS, ticker)
    ddm_inputs = seed_ddm_inputs(financial_data, _fin)

    return StepOutput(text=ddm_inputs.model_dump_json(), structured=ddm_inputs)


async def _execute_ddm_calc(
    agent: Agent[Any, Any],
    deps: FinRobotDeps,
    prompt: str,
    structured_context: dict[str, object],
    ticker: str,
    **_kwargs: object,
) -> StepOutput:
    """Deterministic DDM calculation from DDMInputs + sensitivity table."""
    inputs = structured_context.get("ddm_params")
    if not isinstance(inputs, DDMInputs):
        raise ValueError("ddm_params step must produce DDMInputs structured output")

    ddm_result = calculate_ddm(inputs)

    coe_range, tg_range = build_sensitivity_ranges(
        ddm_result.cost_of_equity, inputs.terminal_growth_rate
    )
    sensitivity = calculate_ddm_sensitivity(inputs, coe_range=coe_range, tg_range=tg_range)

    # Extract price range from sensitivity
    all_prices = [
        p for row in sensitivity["implied_prices"] for p in row if p is not None and p > 0
    ]
    price_range = f"${min(all_prices):.0f}–${max(all_prices):.0f}" if all_prices else "N/A"

    # Build narrative
    upside = ddm_result.upside
    direction = "upside" if upside >= 0 else "downside"
    narrative = (
        f"DDM implies ${ddm_result.equity_value_per_share:.2f} per share "
        f"({abs(upside):.1%} {direction} vs ${inputs.current_price:.2f}). "
        f"Cost of equity: {ddm_result.cost_of_equity:.1%}. "
        f"Terminal growth: {inputs.terminal_growth_rate:.1%}. "
        f"Sensitivity range: {price_range}."
    )

    # Store sensitivity in a combined result for report context
    # (DDMResult is frozen, so we attach it via structured_context)
    structured_context["ddm_sensitivity"] = sensitivity

    return StepOutput(text=narrative, structured=ddm_result)


def create_ddm_pipeline(agents: dict[str, Agent]) -> Pipeline:
    """4-step DDM valuation pipeline factory.

    Used for banks and dividend-paying stocks where FCF-DCF is inappropriate.
    """
    from finrobot.artifact.builders import build_ddm_artifact

    return Pipeline(
        artifact_builder=build_ddm_artifact,
        steps=[
            PipelineStep(
                name="historical_data",
                skill_section=None,
                agent=agents["data"],
                required_data=[DataType.FINANCIALS, DataType.PRICE],
                validator=StructuredValidator(
                    validate_financial_data,
                    lambda out: validate_has_fields(out, ["revenue"]),
                ),
                executor=execute_financial_data_step,
                # ddm_params/ddm_calc read this FinancialData — abort if it fails.
                critical=True,
            ),
            PipelineStep(
                name="ddm_params",
                skill_section=None,
                agent=agents["modeling"],
                required_data=[],
                validator=StructuredValidator(validate_ddm_inputs, validate_is_non_empty),
                executor=_execute_ddm_seed,
            ),
            PipelineStep(
                name="ddm_calc",
                skill_section=None,
                agent=agents["modeling"],
                required_data=[],
                validator=StructuredValidator(validate_ddm_result, validate_is_non_empty),
                executor=_execute_ddm_calc,
            ),
            PipelineStep(
                name="ddm_narrative",
                skill_section=None,
                agent=agents["report"],
                required_data=[],
                validator=TextValidator(validate_ddm_output),
            ),
        ],
    )
