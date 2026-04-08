"""LBO analysis pipeline.

4 steps:
  1. data_collection  — fetch financials/price, produce FinancialData
  2. lbo_parameters   — LLM selects LBOInputs assumptions
  3. lbo_calculation  — deterministic calculate_lbo() + sensitivity
  4. lbo_narrative    — LLM writes narrative / investment memo section
"""
import logging

from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.exceptions import AgentRunError

from finagent.engine.compute.extractor import extract_financial_data
from finagent.engine.compute.lbo import calculate_lbo, calculate_lbo_sensitivity
from finagent.engine.data.types import DataType
from finagent.engine.models.financial import LBOInputs, LBOResult, StepOutput
from finagent.engine.pipelines.base import Pipeline, PipelineStep
from finagent.engine.pipelines.validators import (
    validate_financial_data,
    validate_has_fields,
    validate_is_non_empty,
    validate_lbo_inputs,
    validate_lbo_result,
)

logger = logging.getLogger(__name__)


async def _execute_lbo_data(agent, deps, prompt, structured_context, ticker):
    """Fetch financials + price, extract typed FinancialData."""
    step_result = await agent.run(prompt, deps=deps)
    financials_result = await deps.data_layer.fetch(DataType.FINANCIALS, ticker)
    price_result = await deps.data_layer.fetch(DataType.PRICE, ticker)
    financial_data = extract_financial_data(financials_result, price_result)
    return StepOutput(text=step_result.output, structured=financial_data)


async def _execute_lbo_params(agent, deps, prompt, structured_context, ticker):
    """LLM selects LBOInputs assumptions from financial data."""
    param_agent = Agent(
        deps.settings.model_name,
        output_type=LBOInputs,
        instructions=(
            "Select LBO model assumptions for a private equity acquisition of this company. "
            "Use realistic assumptions: entry EV/EBITDA 6-12×, exit 8-14×, leverage 3-7×, "
            "holding period 3-7 years. Ticker must be the company's ticker symbol."
        ),
        defer_model_check=True,
    )
    try:
        result = await param_agent.run(prompt, deps=deps)
        inputs = result.output
    except (AgentRunError, ValidationError, ValueError) as e:
        raise ValueError(f"LLM failed to produce valid LBO parameters: {e}") from e

    return StepOutput(text=inputs.model_dump_json(), structured=inputs)


async def _execute_lbo_calc(agent, deps, prompt, structured_context, ticker):
    """Deterministic LBO calculation from LBOInputs."""
    inputs = structured_context.get("lbo_parameters")
    if not isinstance(inputs, LBOInputs):
        raise ValueError("lbo_parameters step must produce LBOInputs structured output")

    result: LBOResult = calculate_lbo(inputs)

    narrative = (
        f"LBO implies {result.moic:.1f}× MOIC and {result.irr:.1%} IRR over "
        f"{inputs.holding_period_years} years. "
        f"Entry equity: ${result.entry_equity / 1e6:.0f}M, "
        f"Exit equity: ${result.exit_equity / 1e6:.0f}M. "
        f"Entry EV: ${result.entry_ev / 1e6:.0f}M "
        f"({inputs.entry_ev_ebitda:.1f}× EBITDA), "
        f"Entry debt: ${result.entry_debt / 1e6:.0f}M.\n"
        f"[NOTE: IRR uses closed-form formula assuming single entry/exit cash flow. "
        f"Does not account for interim dividends or recapitalizations. "
        f"Actual PE returns may differ.]"
    )
    return StepOutput(text=narrative, structured=result)


def create_lbo_pipeline(agents: dict[str, Agent]) -> Pipeline:
    """4-step LBO analysis pipeline factory."""
    return Pipeline(
        steps=[
            PipelineStep(
                name="data_collection",
                skill_section=None,
                agent=agents["data"],
                required_data=[DataType.FINANCIALS, DataType.PRICE],
                validate=lambda out: validate_has_fields(out, ["revenue", "ebitda"]),
                validate_structured=validate_financial_data,
                execute_fn=_execute_lbo_data,
            ),
            PipelineStep(
                name="lbo_parameters",
                skill_section=None,
                agent=agents["modeling"],
                required_data=[],
                validate=lambda out: validate_is_non_empty(out),
                validate_structured=validate_lbo_inputs,
                execute_fn=_execute_lbo_params,
            ),
            PipelineStep(
                name="lbo_calculation",
                skill_section=None,
                agent=agents["modeling"],
                required_data=[],
                validate=lambda out: validate_is_non_empty(out),
                validate_structured=validate_lbo_result,
                execute_fn=_execute_lbo_calc,
            ),
            PipelineStep(
                name="lbo_narrative",
                skill_section=None,
                agent=agents["report"],
                required_data=[],
                validate=lambda out: validate_is_non_empty(out),
            ),
        ]
    )
