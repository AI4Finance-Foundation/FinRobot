from pathlib import Path

from pydantic_ai import Agent, RunContext

from finagent.config import FinAgentSettings
from finagent.engine.deps import FinAgentDeps
from finagent.engine.skills.registry import SkillRegistry

INSTRUCTIONS_DIR = Path(__file__).parent / "instructions"


def create_sub_agents(
    settings: FinAgentSettings,
    skill_registry: SkillRegistry | None = None,
) -> dict[str, Agent]:
    """Create all 5 dedicated sub-agents.

    Returns:
        dict mapping role name to Agent:
        {
            "data": Agent,
            "analysis": Agent,
            "modeling": Agent,
            "synthesis": Agent,
            "report": Agent,
        }
    """
    agents = {}

    for role in ["data", "analysis", "modeling", "synthesis", "report"]:
        instructions = (INSTRUCTIONS_DIR / f"{role}_agent.md").read_text()

        agent = Agent(
            settings.create_model(),
            deps_type=FinAgentDeps,
            instructions=instructions,
        )

        agents[role] = agent

    # Only data_agent gets the query_financial_data tool
    @agents["data"].tool
    async def query_financial_data(
        ctx: RunContext[FinAgentDeps], ticker: str, data_type: str
    ) -> str:
        """Fetch financial data. data_type: financials | price | news"""
        result = await ctx.deps.data_layer.fetch(data_type, ticker)
        return result.to_context_string()

    return agents
