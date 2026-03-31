from pydantic_ai import Agent

from finagent.engine.pipelines.base import Pipeline, PipelineStep
from finagent.engine.pipelines.validators import (
    validate_has_fields,
    validate_has_peers,
    validate_has_valuation,
    validate_has_thesis,
    validate_report_format,
)


def create_equity_research_pipeline(agents: dict[str, Agent]) -> Pipeline:
    """Factory function. Now accepts dict of sub-agents instead of a single agent.

    Args:
        agents: dict from create_sub_agents(), keys: data, analysis, modeling, synthesis, report
    """
    return Pipeline(
        steps=[
            # Step 1: Data Collection (code-enforced, all sources queried)
            PipelineStep(
                name="data_collection",
                skill_section=None,
                agent=agents["data"],
                required_data=["financials", "price", "news"],
                validate=lambda out: validate_has_fields(out, ["revenue", "ebitda", "price_history"]),
            ),

            # Step 2: Peer Identification & Comps
            PipelineStep(
                name="peer_analysis",
                skill_section="comps-analysis",
                agent=agents["analysis"],
                required_data=[],
                validate=lambda out: validate_has_peers(out, min_peers=3),
            ),

            # Step 3: Financial Analysis & Modeling
            PipelineStep(
                name="financial_modeling",
                skill_section="dcf-model",
                agent=agents["modeling"],
                required_data=[],
                validate=lambda out: validate_has_valuation(out),
            ),

            # Step 4: Thesis Construction
            PipelineStep(
                name="thesis",
                skill_section="initiating-coverage",
                agent=agents["synthesis"],
                required_data=[],
                validate=lambda out: validate_has_thesis(out),
            ),

            # Step 5: Report Generation
            PipelineStep(
                name="report",
                skill_section=None,
                agent=agents["report"],
                required_data=[],
                validate=lambda out: validate_report_format(out),
            ),
        ]
    )
