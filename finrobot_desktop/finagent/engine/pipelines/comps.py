from pydantic_ai import Agent

from finagent.engine.pipelines.base import Pipeline, PipelineStep
from finagent.engine.pipelines.validators import (
    validate_has_fields,
    validate_has_peers,
    validate_is_non_empty,
    validate_has_comps_table,
)


def create_comps_pipeline(agents: dict[str, Agent]) -> Pipeline:
    """6-step comps analysis pipeline per ARCHITECTURE.md section 2.3."""
    return Pipeline(
        steps=[
            PipelineStep(
                name="target_data",
                skill_section=None,
                agent=agents["data"],
                required_data=["financials", "price"],
                validate=lambda out: validate_has_fields(out, ["revenue", "ebitda"]),
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
            ),
            PipelineStep(
                name="multiples_calc",
                skill_section="comps-analysis",
                agent=agents["modeling"],
                required_data=[],
                validate=lambda out: validate_is_non_empty(out),  # TODO(P2c): validate_has_multiples_table
            ),
            PipelineStep(
                name="statistical_bench",
                skill_section="comps-analysis",
                agent=agents["analysis"],
                required_data=[],
                validate=lambda out: validate_is_non_empty(out),  # TODO(P2c): validate_has_statistics
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
