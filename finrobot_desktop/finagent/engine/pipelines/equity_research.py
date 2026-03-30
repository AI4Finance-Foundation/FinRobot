from pydantic_ai import Agent

from finagent.engine.pipelines.base import Pipeline, PipelineStep
from finagent.engine.pipelines.validators import validate_has_fields, validate_is_non_empty


def create_equity_research_pipeline(agent: Agent) -> Pipeline:
    """Factory function. Called by orchestrator.py with lead_agent.

    Does NOT import from orchestrator — the agent is injected to avoid circular imports.
    """
    return Pipeline(
        steps=[
            # Step 1: Data Collection (code-enforced, all sources queried)
            PipelineStep(
                name="data_collection",
                skill_section=None,              # no skill needed, pure data fetch
                agent=agent,
                required_data=["financials", "price", "news"],  # filings: P2b (SEC EDGAR)
                validate=lambda out: validate_has_fields(out, ["revenue", "ebitda", "price_history"]),
            ),

            # Step 2: Peer Identification & Comps
            PipelineStep(
                name="peer_analysis",
                skill_section="comps-analysis",  # Anthropic's comps methodology (P1a+)
                agent=agent,
                required_data=[],                # uses step 1 output
                # P0: validate_is_non_empty (skill not yet loaded, strict validator would false-fail)
                # P1b+: validate_has_peers(out, min_peers=3)
                validate=lambda out: validate_is_non_empty(out),
            ),

            # Step 3: Financial Analysis & Modeling
            PipelineStep(
                name="financial_modeling",
                skill_section="dcf-model",       # Anthropic's DCF methodology (P1a+)
                agent=agent,
                required_data=[],
                # P0: validate_is_non_empty
                # P1b+: validate_has_valuation(out)
                validate=lambda out: validate_is_non_empty(out),
            ),

            # Step 4: Thesis Construction
            PipelineStep(
                name="thesis",
                skill_section="initiating-coverage",  # Anthropic's IC methodology (P1a+)
                agent=agent,
                required_data=[],
                # P0: validate_is_non_empty
                # P1b+: validate_has_sections(out)
                validate=lambda out: validate_is_non_empty(out),
            ),

            # Step 5: Report Generation
            PipelineStep(
                name="report",
                skill_section=None,              # structured output, no skill
                agent=agent,
                required_data=[],
                # P0: validate_is_non_empty
                # P1b+: validate_report_format(out)
                validate=lambda out: validate_is_non_empty(out),
            ),
        ]
    )
