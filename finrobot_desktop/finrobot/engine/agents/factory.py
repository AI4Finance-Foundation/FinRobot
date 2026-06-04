from pathlib import Path

from pydantic_ai import Agent, RunContext

from finrobot.config import FinRobotSettings
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.skills.registry import SkillRegistry

INSTRUCTIONS_DIR = Path(__file__).parent / "instructions"

SUB_AGENT_ROLES: tuple[str, ...] = ("data", "analysis", "modeling", "synthesis", "report")


def create_sub_agents(
    settings: FinRobotSettings,
    skill_registry: SkillRegistry | None = None,
) -> dict[str, Agent]:
    """Create one Agent per role in SUB_AGENT_ROLES.

    Each role loads its instructions from instructions/{role}_agent.md. All
    roles run on the single configured model (settings.model_name) — there are
    no per-role overrides. Only the 'data' agent gets query_financial_data.
    """
    agents = {}

    for role in SUB_AGENT_ROLES:
        instructions = (INSTRUCTIONS_DIR / f"{role}_agent.md").read_text(encoding="utf-8")

        agent = Agent(
            settings.create_model(),
            deps_type=FinRobotDeps,
            instructions=instructions,
        )

        agents[role] = agent

    # Only data_agent gets the query_financial_data tool
    @agents["data"].tool
    async def query_financial_data(
        ctx: RunContext[FinRobotDeps], ticker: str, data_type: str
    ) -> str:
        """Fetch financial data. data_type: financials | price | news"""
        result = await ctx.deps.data_layer.fetch(data_type, ticker)
        return result.to_context_string()

    return agents  # type: ignore[return-value]
