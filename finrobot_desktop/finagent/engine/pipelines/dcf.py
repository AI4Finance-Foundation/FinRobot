import logging
from pydantic_ai import Agent

from finagent.engine.models.financial import DCFInputs, DCFResult, StepOutput
from finagent.engine.compute.extractor import extract_financial_data
from finagent.engine.compute.dcf import calculate_dcf, calculate_sensitivity
from finagent.engine.pipelines.base import Pipeline, PipelineStep
from finagent.engine.pipelines.validators import (
    validate_has_fields, validate_is_non_empty, validate_dcf_output,
    validate_financial_data, validate_dcf_result,
)
from finagent.engine.pipelines.equity_research import _build_sensitivity_ranges

logger = logging.getLogger(__name__)


async def _execute_historical_data(agent, deps, prompt, structured_context, ticker):
    """Fetch + extract typed FinancialData."""
    step_result = await agent.run(prompt, deps=deps)
    financials_result = await deps.data_layer.fetch("financials", ticker)
    price_result = await deps.data_layer.fetch("price", ticker)
    financial_data = extract_financial_data(financials_result, price_result)
    return StepOutput(text=step_result.output, structured=financial_data)


async def _execute_dcf_calc(agent, deps, prompt, structured_context, ticker):
    """param_agent selects DCFInputs; code computes full DCFResult + sensitivity."""
    param_agent = Agent(
        deps.settings.model_name,
        output_type=DCFInputs,
        instructions=(
            "Select DCF valuation parameters based on the historical financial data. "
            "Use conservative assumptions. Revenue growth rates must reflect realistic projections."
        ),
        defer_model_check=True,
    )
    try:
        param_result = await param_agent.run(prompt, deps=deps)
        dcf_inputs = param_result.output
    except Exception as e:
        raise ValueError(f"LLM failed to produce valid DCF parameters: {e}") from e

    dcf_result = calculate_dcf(dcf_inputs)
    wacc_range, tg_range = _build_sensitivity_ranges(dcf_result)
    sensitivity = calculate_sensitivity(dcf_inputs, wacc_range=wacc_range, tg_range=tg_range)
    dcf_result = dcf_result.model_copy(update={"sensitivity_table": sensitivity})

    valid_prices = [p for row in sensitivity["implied_prices"] for p in row if p is not None and p > 0]
    price_range = f"${min(valid_prices):.0f}–${max(valid_prices):.0f}" if valid_prices else "N/A"
    narrative = (
        f"DCF implies ${dcf_result.implied_price:.2f} per share. "
        f"WACC: {dcf_result.wacc:.1%}. EV: ${dcf_result.enterprise_value/1e9:.1f}B. "
        f"Sensitivity: {price_range}."
    )
    return StepOutput(text=narrative, structured=dcf_result)


def create_dcf_pipeline(agents: dict[str, Agent]) -> Pipeline:
    """3-step DCF valuation pipeline (steps 2-5 collapsed into dcf_calc)."""
    return Pipeline(
        steps=[
            PipelineStep(
                name="historical_data",
                skill_section=None,
                agent=agents["data"],
                required_data=["financials", "price"],
                validate=lambda out: validate_has_fields(out, ["revenue", "ebitda"]),
                validate_structured=validate_financial_data,
                execute_fn=_execute_historical_data,
            ),
            PipelineStep(
                name="dcf_calc",
                skill_section="dcf-model",
                agent=agents["modeling"],
                required_data=[],
                validate=lambda out: validate_is_non_empty(out),
                validate_structured=validate_dcf_result,
                execute_fn=_execute_dcf_calc,
            ),
            PipelineStep(
                name="output_gen",
                skill_section="dcf-model",
                agent=agents["report"],
                required_data=[],
                validate=lambda out: validate_dcf_output(out),
            ),
        ]
    )
