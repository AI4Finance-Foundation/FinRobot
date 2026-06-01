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

from finrobot.engine.compute.dcf import calculate_dcf, calculate_sensitivity
from finrobot.engine.compute.dcf_seed import seed_dcf_inputs
from finrobot.engine.compute.wacc import calculate_wacc
from finrobot.engine.compute.historical_extractor import (
    fetch_historical_metrics,
)
from finrobot.engine.data.types import DataType
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.models.financial import FinancialData, StepOutput
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

    # Multi-year history powers the 3y-median assumption derivation.
    historical = await fetch_historical_metrics(deps.data_layer, ticker)
    dcf_inputs = seed_dcf_inputs(financial_data, historical)

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
                f"DCF 不适用：加权资本成本 WACC {wacc:.1%} 不高于永续增长率 "
                f"{dcf_inputs.terminal_growth_rate:.1%}，Gordon 永续增长模型在此情形下无定义。"
                f"本标的跳过 DCF 估值，请以相对估值（可比公司倍数、历史估值区间）为准。"
            ),
            structured=None,
        )

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
