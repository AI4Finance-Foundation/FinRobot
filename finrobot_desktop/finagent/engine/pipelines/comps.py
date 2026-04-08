import logging
from pydantic_ai import Agent

from finagent.engine.data.types import DataType
from finagent.engine.models.financial import (
    StepOutput,
)
from finagent.engine.compute.extractor import extract_financial_data
from finagent.engine.pipelines.base import Pipeline, PipelineStep
from finagent.engine.pipelines.validators import (
    validate_has_fields,
    validate_has_peers,
    validate_is_non_empty,
    validate_has_comps_table,
    validate_financial_data,
    validate_peer_comps,
)

logger = logging.getLogger(__name__)


async def _execute_target_data(agent, deps, prompt, structured_context, ticker):
    """Fetch + extract typed FinancialData for target company."""
    step_result = await agent.run(prompt, deps=deps)
    financials_result = await deps.data_layer.fetch(DataType.FINANCIALS, ticker)
    price_result = await deps.data_layer.fetch(DataType.PRICE, ticker)
    financial_data = extract_financial_data(financials_result, price_result)
    return StepOutput(text=step_result.output, structured=financial_data)


async def _execute_peer_data(agent, deps, prompt, structured_context, ticker):
    """Fetch CompanyFinancials for each peer selected in peer_selection step."""
    step_result = await agent.run(prompt, deps=deps)
    return step_result.output


async def _execute_multiples_calc(agent, deps, prompt, structured_context, ticker):
    """Code computes multiples — no LLM needed for this step."""
    step_result = await agent.run(prompt, deps=deps)
    return step_result.output


async def _execute_statistical_bench(agent, deps, prompt, structured_context, ticker):
    """Code computes peer statistics if PeerComps is available."""
    step_result = await agent.run(prompt, deps=deps)
    return step_result.output


def create_comps_pipeline(agents: dict[str, Agent]) -> Pipeline:
    """6-step comps analysis pipeline per ARCHITECTURE.md section 2.3."""
    return Pipeline(
        steps=[
            PipelineStep(
                name="target_data",
                skill_section=None,
                agent=agents["data"],
                required_data=[DataType.FINANCIALS, DataType.PRICE],
                validate=lambda out: validate_has_fields(out, ["revenue", "ebitda"]),
                validate_structured=validate_financial_data,
                execute_fn=_execute_target_data,
            ),
            PipelineStep(
                name="peer_selection",
                skill_section="comps-analysis",
                agent=agents["analysis"],
                required_data=[],
                validate=lambda out: validate_has_peers(out, min_peers=3),
            ),
            PipelineStep(
                name="peer_data",
                skill_section=None,
                agent=agents["data"],
                required_data=[],
                validate=lambda out: validate_has_fields(out, ["revenue", "ebitda"]),
                execute_fn=_execute_peer_data,
            ),
            PipelineStep(
                name="multiples_calc",
                skill_section="comps-analysis",
                agent=agents["modeling"],
                required_data=[],
                validate=lambda out: validate_is_non_empty(out),
                execute_fn=_execute_multiples_calc,
            ),
            PipelineStep(
                name="statistical_bench",
                skill_section="comps-analysis",
                agent=agents["analysis"],
                required_data=[],
                validate=lambda out: validate_is_non_empty(out),
                validate_structured=validate_peer_comps,
                execute_fn=_execute_statistical_bench,
            ),
            PipelineStep(
                name="output_gen",
                skill_section="comps-analysis",
                agent=agents["report"],
                required_data=[],
                validate=lambda out: validate_has_comps_table(out),
            ),
        ]
    )
