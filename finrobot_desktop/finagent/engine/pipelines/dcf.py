from pydantic_ai import Agent

from finagent.engine.pipelines.base import Pipeline, PipelineStep
from finagent.engine.pipelines.validators import (
    validate_has_fields,
    validate_is_non_empty,
    validate_dcf_output,
    validate_has_valuation,
)


def create_dcf_pipeline(agents: dict[str, Agent]) -> Pipeline:
    """6-step DCF valuation pipeline per ARCHITECTURE.md section 2.3."""
    return Pipeline(
        steps=[
            PipelineStep(
                name="historical_data",
                skill_section=None,
                agent=agents["data"],
                required_data=["financials", "price"],
                validate=lambda out: validate_has_fields(out, ["revenue", "ebitda"]),
            ),
            PipelineStep(
                name="projection",
                skill_section="dcf-model",
                agent=agents["modeling"],
                required_data=[],
                validate=lambda out: validate_is_non_empty(out),
            ),
            PipelineStep(
                name="wacc",
                skill_section="dcf-model",
                agent=agents["modeling"],
                required_data=[],
                validate=lambda out: validate_has_valuation(out),
            ),
            PipelineStep(
                name="terminal_value",
                skill_section="dcf-model",
                agent=agents["modeling"],
                required_data=[],
                validate=lambda out: validate_is_non_empty(out),
            ),
            PipelineStep(
                name="sensitivity",
                skill_section="dcf-model",
                agent=agents["modeling"],
                required_data=[],
                validate=lambda out: validate_is_non_empty(out),
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
