"""DDM (Dividend Discount Model) pipeline — for banks and dividend-paying stocks.

4 steps:
  1. historical_data    — fetch financials/price, produce FinancialData
  2. ddm_params         — LLM selects DDMInputs (dividend growth, terminal growth, CAPM)
  3. ddm_calc           — deterministic calculate_ddm() + sensitivity
  4. ddm_narrative      — LLM generates narrative with valuation thesis

Banks don't have meaningful free cash flow, so FCF-DCF produces misleading results.
DDM values the company based on projected dividends discounted at cost of equity.
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.exceptions import AgentRunError

from finagent.engine.compute.ddm import calculate_ddm, calculate_ddm_sensitivity
from finagent.engine.data.types import DataType
from finagent.engine.deps import FinAgentDeps
from finagent.engine.models.financial import DDMInputs, StepOutput
from finagent.engine.pipelines.base import (
    Pipeline,
    PipelineStep,
    StructuredValidator,
    TextValidator,
)
from finagent.engine.pipelines._helpers import execute_financial_data_step
from finagent.engine.pipelines.validators import (
    validate_ddm_inputs,
    validate_ddm_output,
    validate_ddm_result,
    validate_financial_data,
    validate_has_fields,
    validate_is_non_empty,
)

logger = logging.getLogger(__name__)


async def _execute_ddm_params(
    agent: Agent[Any, Any],
    deps: FinAgentDeps,
    prompt: str,
    structured_context: dict[str, object],
    ticker: str,
) -> StepOutput:
    """LLM selects DDMInputs assumptions from financial data.

    Extracts dividend data from FinancialData if available and provides it
    as context to the LLM for more grounded parameter selection.
    """
    # Extract dividend context from financial data
    dividend_instruction = ""
    financial_data = structured_context.get("financial_data")
    if financial_data and hasattr(financial_data, "market"):
        market = financial_data.market
        current_price = getattr(market, "current_price", None)
        if current_price:
            dividend_instruction += f"\n\nCurrent price: ${current_price:.2f}."

    # Check for raw dividend data passed through DataResult
    raw_data = structured_context.get("_raw_financials_data")
    if isinstance(raw_data, dict):
        dps = raw_data.get("dividend_per_share")
        payout = raw_data.get("payout_ratio")
        bvps = raw_data.get("book_value_per_share")
        roe = raw_data.get("return_on_equity")
        if dps:
            dividend_instruction += f"\nActual dividend per share: ${dps:.2f}."
        if payout:
            dividend_instruction += f"\nPayout ratio: {payout:.1%}."
        if bvps:
            dividend_instruction += f"\nBook value per share: ${bvps:.2f}."
        if roe:
            dividend_instruction += f"\nReturn on equity: {roe:.1%}."

    param_agent = Agent(
        deps.settings.create_model(),
        output_type=DDMInputs,
        instructions=(
            "Select DDM (Dividend Discount Model) valuation parameters for this bank "
            "or dividend-paying stock. This company is being valued using DDM because "
            "banks do not have traditional free cash flow.\n\n"
            "Key guidelines:\n"
            "- dividend_per_share: Use the actual current annual DPS if available\n"
            "- dividend_growth_rates: Project 3-5 years of growth, typically 3-8% for "
            "mature banks, tapering toward terminal growth\n"
            "- terminal_growth_rate: Long-run nominal GDP growth, typically 2-3%\n"
            "- payout_ratio: Current payout ratio if available, typically 30-60% for banks\n"
            "- beta: Banks typically 0.8-1.3\n"
            "- If book_value_per_share and return_on_equity are available, include them "
            "for P/B-based cross-check\n\n"
            "For each assumption you select, provide a brief justification in the "
            "assumption_provenance dict."
            + dividend_instruction
        ),
        defer_model_check=True,
    )
    try:
        result = await param_agent.run(prompt, deps=deps)  # type: ignore[call-overload]
        ddm_inputs = result.output
    except (AgentRunError, ValidationError, ValueError) as e:
        raise ValueError(f"LLM failed to produce valid DDM parameters: {e}") from e

    return StepOutput(text=ddm_inputs.model_dump_json(), structured=ddm_inputs)


async def _execute_ddm_calc(
    agent: Agent[Any, Any],
    deps: FinAgentDeps,
    prompt: str,
    structured_context: dict[str, object],
    ticker: str,
) -> StepOutput:
    """Deterministic DDM calculation from DDMInputs + sensitivity table."""
    inputs = structured_context.get("ddm_params")
    if not isinstance(inputs, DDMInputs):
        raise ValueError("ddm_params step must produce DDMInputs structured output")

    ddm_result = calculate_ddm(inputs)

    # Build sensitivity table: CoE range x terminal growth range
    coe = ddm_result.cost_of_equity
    tg = inputs.terminal_growth_rate
    coe_range = [round(max(0.03, coe - 0.02 + i * 0.01), 4) for i in range(5)]
    tg_candidates = [round(max(0.0, tg - 0.01 + i * 0.005), 4) for i in range(5)]
    min_coe = min(coe_range)
    tg_range = [g for g in tg_candidates if g < min_coe]
    if len(tg_range) < 2:
        tg_range = [
            round(0.005 + i * 0.005, 4)
            for i in range(5)
            if 0.005 + i * 0.005 < min_coe
        ]

    sensitivity = calculate_ddm_sensitivity(inputs, coe_range=coe_range, tg_range=tg_range)

    # Extract price range from sensitivity
    all_prices = [
        p
        for row in sensitivity["implied_prices"]  # type: ignore[union-attr]
        for p in row  # type: ignore[union-attr]
        if p is not None and p > 0  # type: ignore[operator]
    ]
    price_range = (
        f"${min(all_prices):.0f}–${max(all_prices):.0f}" if all_prices else "N/A"
    )

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
    from finagent.artifact.builders import build_ddm_artifact

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
            ),
            PipelineStep(
                name="ddm_params",
                skill_section=None,
                agent=agents["modeling"],
                required_data=[],
                validator=StructuredValidator(validate_ddm_inputs, validate_is_non_empty),
                executor=_execute_ddm_params,
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
        ]
    )
