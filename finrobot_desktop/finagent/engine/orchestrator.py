from pathlib import Path

from pydantic_ai import Agent, RunContext

from finagent.engine.deps import FinAgentDeps

_instructions = (Path(__file__).parent / "instructions.md").read_text()

lead_agent: Agent[FinAgentDeps, str] = Agent(
    "anthropic:claude-sonnet-4-6",
    deps_type=FinAgentDeps,
    instructions=_instructions,
    defer_model_check=True,   # don't validate API key at import time
)


# --- Mode A tools: conversational, direct response ---

@lead_agent.tool
async def query_financial_data(
    ctx: RunContext[FinAgentDeps], ticker: str, data_type: str
) -> str:
    """Fetch financial data for quick questions.
    data_type: financials | price | news | filings"""
    result = await ctx.deps.data_layer.fetch(data_type, ticker)
    return result.to_context_string()


@lead_agent.tool
async def activate_skill(ctx: RunContext[FinAgentDeps], skill_id: str) -> str:
    """Activate a skill for ad-hoc professional workflows.
    Use this for tasks that don't have a dedicated pipeline."""
    if not ctx.deps.skill_runtime:   # P0: skill runtime not yet available
        return "Skill system is not yet available. Use direct data queries or pipeline commands instead."
    skill = ctx.deps.skill_runtime.get(skill_id)
    if not skill:
        return f"Unknown skill. Available: {ctx.deps.skill_runtime.list_ids()}"
    return skill.full_content


# --- Mode B tools: pipeline dispatch for deep analysis ---

@lead_agent.tool
async def run_equity_research(ctx: RunContext[FinAgentDeps], ticker: str) -> str:
    """Generate a comprehensive equity research report.
    Uses a multi-step enforced pipeline. Takes 30-120 seconds.
    Use this when the user asks for: equity research, initiating coverage,
    stock analysis report, investment thesis, or deep-dive analysis."""
    from finagent.engine.pipelines.equity_research import create_equity_research_pipeline
    pipeline = create_equity_research_pipeline(lead_agent)
    result = await pipeline.execute(ctx, ticker)
    return result.format_summary()

# TODO(P1b): register run_comps_analysis and run_dcf_valuation when comps/dcf pipelines ship
