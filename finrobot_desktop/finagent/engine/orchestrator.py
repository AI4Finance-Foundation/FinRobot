from pathlib import Path

from pydantic_ai import Agent, RunContext

from finagent.config import FinAgentSettings
from finagent.engine.agents.factory import create_sub_agents
from finagent.engine.deps import FinAgentDeps
from finagent.engine.skills.registry import SkillRegistry


def create_lead_agent(
    settings: FinAgentSettings, skill_registry: SkillRegistry | None = None
) -> Agent:
    """Factory: create lead agent with tools and instructions.

    Tool registration uses @agent.tool decorator inside factory scope.
    The decorator targets the `agent` instance created within this function.
    """
    instructions = (Path(__file__).parent / "instructions.md").read_text()
    if skill_registry:
        instructions += "\n\n" + skill_registry.list_summary()

    agent: Agent[FinAgentDeps, str] = Agent(
        settings.model_name,
        deps_type=FinAgentDeps,
        instructions=instructions,
        defer_model_check=True,
    )

    # Create sub-agents for pipelines
    sub_agents = create_sub_agents(settings, skill_registry)

    # --- Mode A tools: conversational, direct response ---

    @agent.tool
    async def query_financial_data(
        ctx: RunContext[FinAgentDeps], ticker: str, data_type: str
    ) -> str:
        """Fetch financial data for quick questions.
        data_type: financials | price | news (filings available from P2b)"""
        result = await ctx.deps.data_layer.fetch(data_type, ticker)
        return result.to_context_string()

    @agent.tool
    async def activate_skill(ctx: RunContext[FinAgentDeps], skill_id: str) -> str:
        """Activate a skill for ad-hoc professional workflows.
        Use this for tasks that don't have a dedicated pipeline."""
        if not ctx.deps.skill_runtime:
            return "Skill system is not yet available. Use direct data queries or pipeline commands instead."
        skill = ctx.deps.skill_runtime.get(skill_id)
        if not skill:
            return f"Unknown skill. Available: {ctx.deps.skill_runtime.list_ids()}"
        return skill.full_content

    # --- Mode B tools: pipeline dispatch for deep analysis ---

    from finagent.engine.pipelines.equity_research import create_equity_research_pipeline

    equity_pipeline = create_equity_research_pipeline(sub_agents)

    @agent.tool
    async def run_equity_research(ctx: RunContext[FinAgentDeps], ticker: str) -> str:
        """Generate a comprehensive equity research report.
        Uses a multi-step enforced pipeline. Takes 30-120 seconds.
        Use this when the user asks for: equity research, initiating coverage,
        stock analysis report, investment thesis, or deep-dive analysis."""
        result = await equity_pipeline.execute(ctx.deps, ticker)
        return result.format_summary()

    from finagent.engine.pipelines.comps import create_comps_pipeline

    comps_pipeline = create_comps_pipeline(sub_agents)

    @agent.tool
    async def run_comps_analysis(
        ctx: RunContext[FinAgentDeps], ticker: str
    ) -> str:
        """Build a comparable company analysis.
        Uses a multi-step enforced pipeline.
        Use when user asks for: comps, comparable companies, peer analysis,
        trading multiples comparison."""
        result = await comps_pipeline.execute(ctx.deps, ticker)
        return result.format_summary()

    from finagent.engine.pipelines.dcf import create_dcf_pipeline

    dcf_pipeline = create_dcf_pipeline(sub_agents)

    @agent.tool
    async def run_dcf_valuation(ctx: RunContext[FinAgentDeps], ticker: str) -> str:
        """Run a DCF valuation model.
        Uses a multi-step enforced pipeline.
        Use when user asks for: DCF, discounted cash flow, intrinsic value,
        valuation model."""
        result = await dcf_pipeline.execute(ctx.deps, ticker)
        return result.format_summary()

    return agent
