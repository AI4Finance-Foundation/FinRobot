from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import Agent

from finagent.engine.data.types import DataType
from finagent.engine.deps import FinAgentDeps
from finagent.engine.pipelines.base import (
    Pipeline, PipelineStep, StructuredValidator, TextValidator,
)
from finagent.engine.pipelines._helpers import execute_financial_data_step
from finagent.engine.pipelines.validators import (
    validate_has_fields,
    validate_has_peers,
    validate_is_non_empty,
    validate_has_comps_table,
    validate_financial_data,
    validate_peer_comps,
)

logger = logging.getLogger(__name__)


async def _execute_peer_data(
    agent: Agent[Any, Any],
    deps: FinAgentDeps,
    prompt: str,
    structured_context: dict[str, object],
    ticker: str,
) -> str:
    """Fetch CompanyFinancials for each peer selected in peer_selection step."""
    step_result = await agent.run(prompt, deps=deps)  # type: ignore[call-overload]
    return step_result.output  # type: ignore[no-any-return]


async def _execute_multiples_calc(
    agent: Agent[Any, Any],
    deps: FinAgentDeps,
    prompt: str,
    structured_context: dict[str, object],
    ticker: str,
) -> str:
    """Code computes multiples — no LLM needed for this step."""
    step_result = await agent.run(prompt, deps=deps)  # type: ignore[call-overload]
    return step_result.output  # type: ignore[no-any-return]


async def _execute_statistical_bench(
    agent: Agent[Any, Any],
    deps: FinAgentDeps,
    prompt: str,
    structured_context: dict[str, object],
    ticker: str,
) -> str:
    """Code computes peer statistics if PeerComps is available."""
    step_result = await agent.run(prompt, deps=deps)  # type: ignore[call-overload]
    return step_result.output  # type: ignore[no-any-return]


def create_comps_pipeline(agents: dict[str, Agent]) -> Pipeline:
    """6-step comps analysis pipeline per ARCHITECTURE.md section 2.3."""
    from finagent.artifact.builders import build_comps_artifact

    return Pipeline(
        artifact_builder=build_comps_artifact,
        steps=[
            PipelineStep(
                name="target_data",
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
                name="peer_selection",
                skill_section="comps-analysis",
                agent=agents["analysis"],
                required_data=[],
                validator=TextValidator(lambda out: validate_has_peers(out, min_peers=3)),
            ),
            PipelineStep(
                name="peer_data",
                skill_section=None,
                agent=agents["data"],
                required_data=[],
                validator=TextValidator(lambda out: validate_has_fields(out, ["revenue", "ebitda"])),
                executor=_execute_peer_data,
            ),
            PipelineStep(
                name="multiples_calc",
                skill_section="comps-analysis",
                agent=agents["modeling"],
                required_data=[],
                validator=TextValidator(validate_is_non_empty),
                executor=_execute_multiples_calc,
            ),
            PipelineStep(
                name="statistical_bench",
                skill_section="comps-analysis",
                agent=agents["analysis"],
                required_data=[],
                validator=StructuredValidator(
                    validate_peer_comps,
                    validate_is_non_empty,
                ),
                executor=_execute_statistical_bench,
            ),
            PipelineStep(
                name="output_gen",
                skill_section="comps-analysis",
                agent=agents["report"],
                required_data=[],
                validator=TextValidator(validate_has_comps_table),
            ),
        ]
    )
