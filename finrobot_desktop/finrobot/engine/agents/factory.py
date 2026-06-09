from pathlib import Path

from pydantic_ai import Agent, RunContext

from finrobot.config import FinRobotSettings
from finrobot.engine.data.types import DataType
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
        # PRICE / FINANCIALS MUST come through the canonical (validated,
        # provenance-stamped) contract — the SAME path the pipeline's structured
        # FinancialData uses (fetch_canonical, ADR-0006). Bare fetch() here was a
        # SECOND, un-validated quote source: the data agent narrated a price from
        # raw fetch() while every structured/valuation field used the canonical
        # one, so one artifact carried two "current prices" ($391 narrative vs
        # $408.95 structured, 2026-06-09 TSLA). Only NEWS (no canonical contract)
        # stays on raw fetch().
        normalized_type = data_type.strip().lower()
        if normalized_type in (DataType.PRICE.value, DataType.FINANCIALS.value):
            canonical_type = DataType(normalized_type)
            normalized = await ctx.deps.data_layer.fetch_canonical(canonical_type, ticker)
            return (
                f"[canonical] {canonical_type.value} (normalized contract — the single "
                f"source of truth; quote these figures verbatim)\n"
                f"```json\n{normalized.model_dump_json(indent=2)}\n```"
            )
        result = await ctx.deps.data_layer.fetch(data_type, ticker)
        return result.to_context_string()

    return agents  # type: ignore[return-value]
