from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.exceptions import AgentRunError

from finagent.engine.data.types import DataType
from finagent.engine.deps import FinAgentDeps
from finagent.engine.models.financial import DCFInputs, StepOutput
from finagent.engine.compute.dcf import calculate_dcf, calculate_sensitivity
from finagent.engine.pipelines.base import (
    Pipeline,
    PipelineStep,
    StructuredValidator,
    TextValidator,
)
from finagent.engine.pipelines._helpers import (
    build_sensitivity_ranges,
    execute_financial_data_step,
)
from finagent.engine.pipelines.validators import (
    validate_has_fields,
    validate_is_non_empty,
    validate_dcf_output,
    validate_financial_data,
    validate_dcf_result,
)

logger = logging.getLogger(__name__)


async def _execute_dcf_calc(
    agent: Agent[Any, Any],
    deps: FinAgentDeps,
    prompt: str,
    structured_context: dict[str, object],
    ticker: str,
) -> StepOutput:
    """param_agent selects DCFInputs; code computes full DCFResult + sensitivity."""
    # Extract actual D&A from financial data so the LLM can set da_pct_revenue correctly
    da_instruction = ""
    financial_data = structured_context.get("financial_data")
    if financial_data and hasattr(financial_data, "income"):
        income = financial_data.income
        da_val = getattr(income, "depreciation_amortization", None)
        rev_val = getattr(income, "revenue", None)
        if da_val and rev_val and rev_val > 0:
            da_pct = da_val / rev_val
            da_instruction = (
                f"\n\nIMPORTANT: Actual D&A from financial data is ${da_val / 1e9:.1f}B "
                f"({da_pct:.1%} of revenue). You MUST set da_pct_revenue={da_pct:.4f} "
                f"to use the standard FCF formula: EBIT(1-T)+D&A-CapEx-ΔNWC. "
                f"Do NOT leave da_pct_revenue as null — that triggers an inaccurate simplified formula."
            )
        else:
            da_instruction = (
                "\n\nNote: D&A data is not available from providers. "
                "Set da_pct_revenue to your best estimate (typically 0.02-0.08 depending on industry). "
                "Leaving it null will use a simplified FCF formula that may be inaccurate for capital-intensive companies."
            )

    param_agent = Agent(
        deps.settings.create_model(),
        output_type=DCFInputs,
        instructions=(
            "Select DCF valuation parameters based on the historical financial data. "
            "Use conservative assumptions. Revenue growth rates must reflect realistic projections."
            + da_instruction
            + "\n\nFor each assumption you select, provide a brief justification in the "
            "assumption_provenance dict. "
            "Keys should be the field name (e.g., 'revenue_growth_rates', 'ebitda_margin', "
            "'terminal_growth_rate', 'beta'). "
            "Values should be one sentence explaining why (e.g., 'Based on 5-year CAGR of "
            "8.2% with deceleration assumption')."
        ),
        defer_model_check=True,
    )
    try:
        param_result = await param_agent.run(prompt, deps=deps)  # type: ignore[call-overload]
        dcf_inputs = param_result.output
    except (AgentRunError, ValidationError, ValueError) as e:
        raise ValueError(f"LLM failed to produce valid DCF parameters: {e}") from e

    dcf_result = calculate_dcf(dcf_inputs)
    wacc_range, tg_range = build_sensitivity_ranges(
        dcf_result.wacc, dcf_result.inputs.terminal_growth_rate
    )
    sensitivity = calculate_sensitivity(dcf_inputs, wacc_range=wacc_range, tg_range=tg_range)
    dcf_result = dcf_result.model_copy(update={"sensitivity_table": sensitivity})

    valid_prices = [
        p for row in sensitivity["implied_prices"] for p in row if p is not None and p > 0
    ]
    price_range = f"${min(valid_prices):.0f}–${max(valid_prices):.0f}" if valid_prices else "N/A"
    narrative = (
        f"DCF implies ${dcf_result.implied_price:.2f} per share. "
        f"WACC: {dcf_result.wacc:.1%}. EV: ${dcf_result.enterprise_value / 1e9:.1f}B. "
        f"Sensitivity: {price_range}."
    )
    if dcf_result.fcf_formula_warning:
        narrative = f"[{dcf_result.fcf_formula_warning}]\n\n{narrative}"
    return StepOutput(text=narrative, structured=dcf_result)


def create_dcf_pipeline(agents: dict[str, Agent]) -> Pipeline:
    """3-step DCF valuation pipeline (steps 2-5 collapsed into dcf_calc)."""
    from finagent.artifact.builders import build_dcf_artifact

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
            ),
            PipelineStep(
                name="dcf_calc",
                skill_section="dcf-model",
                agent=agents["modeling"],
                required_data=[],
                validator=StructuredValidator(validate_dcf_result, validate_is_non_empty),
                executor=_execute_dcf_calc,
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
