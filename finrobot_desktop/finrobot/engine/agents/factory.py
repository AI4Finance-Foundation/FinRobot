import json
from pathlib import Path

from pydantic_ai import Agent, ModelRetry, RunContext

from finrobot.config import FinRobotSettings
from finrobot.engine.compute.coordinators.news import render_news_for_prompt
from finrobot.engine.data.normalize.contracts import NormalizedPrice
from finrobot.engine.data.ticker import validate_ticker
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
        # Both args are LLM-chosen — guard them before they become fetch
        # parameters (mirror of the lead orchestrator's same-named tool):
        # - bad ticker → returned error string: usually a hallucinated symbol
        #   the model cannot self-correct, so let it see the error and narrate;
        # - bad data_type → ModelRetry: the model picked outside the enum and
        #   CAN self-correct (per pydantic-ai docs, ModelRetry becomes a
        #   RetryPromptPart fed back to the model, bounded by max_retries).
        # Previously an invalid data_type raised a bare ValueError inside
        # fetch(), which pydantic-ai does NOT catch — it propagated out of the
        # sub-agent run and burned the whole pipeline step.
        try:
            norm_ticker = validate_ticker(ticker)
        except ValueError:
            return f"Invalid ticker symbol: {ticker}"
        try:
            canonical_type = DataType(data_type.strip().lower())
        except ValueError as exc:
            raise ModelRetry(
                f"Unknown data_type {data_type!r}. Valid values: {[d.value for d in DataType]}"
            ) from exc
        # PRICE / FINANCIALS MUST come through the canonical (validated,
        # provenance-stamped) contract — the SAME path the pipeline's structured
        # FinancialData uses (fetch_canonical, ADR-0006). Bare fetch() here was a
        # SECOND, un-validated quote source: the data agent narrated a price from
        # raw fetch() while every structured/valuation field used the canonical
        # one, so one artifact carried two "current prices" ($391 narrative vs
        # $408.95 structured, 2026-06-09 TSLA). Only NEWS (no canonical contract)
        # stays on raw fetch().
        if canonical_type in (DataType.PRICE, DataType.FINANCIALS):
            normalized = await ctx.deps.data_layer.fetch_canonical(canonical_type, norm_ticker)
            # PRICE: hand back the derived summary + MOST-RECENT bars, not the full
            # 52-week ascending series — the agent narrated the OLDEST bars as
            # "recent" off the raw series (2026-06-09 TSLA's year-old window).
            if isinstance(normalized, NormalizedPrice):
                body = json.dumps(normalized.to_prompt_summary(), indent=2, default=str)
            else:
                body = normalized.model_dump_json(indent=2)
            return (
                f"[canonical] {canonical_type.value} (normalized contract — the single "
                f"source of truth; quote these figures verbatim)\n"
                f"```json\n{body}\n```"
            )
        result = await ctx.deps.data_layer.fetch(canonical_type, norm_ticker)
        if canonical_type is DataType.NEWS:
            # Headlines are third-party text — flatten + untrusted-wrap before
            # they enter the agent's context (BUG-087 choke point).
            return render_news_for_prompt(result)
        return result.to_context_string()

    return agents  # type: ignore[return-value]
