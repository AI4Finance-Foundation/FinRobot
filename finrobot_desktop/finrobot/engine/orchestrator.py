import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, ModelRetry, RunContext

from finrobot.config import FinRobotSettings
from finrobot.engine.agents.factory import create_sub_agents
from finrobot.engine.data.ticker import validate_ticker
from finrobot.engine.data.types import DataType
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.pipelines.base import Pipeline
from finrobot.engine.pipelines.registry import PipelineSpec, iter_pipeline_specs
from finrobot.engine.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


async def _run_pipeline_tool(
    ctx: RunContext[FinRobotDeps], ticker: str, pipeline: Pipeline
) -> dict[str, Any] | str:
    """Execute a pipeline and return the tool summary dict.

    Shared dispatch for every @agent.tool that wraps a Pipeline — every result
    is persisted to ArtifactStore by the pipeline itself; the tool returns the
    artifact_id so the caller can route to the detail page.

    On a syntactically invalid ticker this RETURNS a plain error string rather
    than raising: a raised ValueError inside a tool propagates out of the
    PydanticAI run and crashes the live chat SSE stream. Returning lets the LLM
    see the error and ask the user to correct the symbol.
    """
    try:
        norm = validate_ticker(ticker)
    except ValueError:
        return f"Invalid ticker symbol: {ticker}"
    result = await pipeline.execute(ctx.deps, norm)
    return {
        "summary": result.format_summary(),
        "artifact_id": result.artifact_id,
        "ticker": norm,
    }


def _make_pipeline_tool(
    pipeline: Pipeline,
) -> Callable[[RunContext[FinRobotDeps], str], Awaitable[dict[str, Any] | str]]:
    """Build a Mode B tool closure that dispatches to ``pipeline``.

    One closure per :class:`PipelineSpec`, replacing the seven near-identical
    hand-written ``@agent.tool`` wrappers — every body was
    ``return await _run_pipeline_tool(ctx, ticker, X_pipeline)``. The tool name
    and the LLM-facing description come from the spec (see
    ``create_lead_agent``), so the only thing that varies per pipeline is the
    bound ``pipeline`` object captured here.
    """

    async def run_pipeline(ctx: RunContext[FinRobotDeps], ticker: str) -> dict[str, Any] | str:
        return await _run_pipeline_tool(ctx, ticker, pipeline)

    return run_pipeline


def create_lead_agent(
    settings: FinRobotSettings,
    skill_registry: SkillRegistry | None = None,
    sub_agents: dict[str, Agent] | None = None,
) -> Agent:
    """Factory: create lead agent with tools and instructions.

    ``sub_agents`` lets the caller share a single set of sub-agents with the
    pipeline dispatcher (``app.state.sub_agents``) so the LLM-side and the
    REST-side don't double-create connections. When None, builds its own.
    """
    instructions = (Path(__file__).parent / "instructions.md").read_text(encoding="utf-8")
    if skill_registry:
        instructions += "\n\n" + skill_registry.list_summary()

    agent: Agent[FinRobotDeps, str] = Agent(
        settings.create_model(),
        deps_type=FinRobotDeps,
        instructions=instructions,
    )

    if sub_agents is None:
        sub_agents = create_sub_agents(settings, skill_registry)

    # --- Mode A tools: conversational, direct response ---

    @agent.tool
    async def query_financial_data(
        ctx: RunContext[FinRobotDeps], ticker: str, data_type: str | DataType
    ) -> str:
        """Fetch financial data for quick questions.
        data_type: one of the DataType values, commonly financials, price, quote,
        news, earnings, filings, profile, historical, quarterly, forward_estimates,
        10k_rag."""
        # RETURN (not raise) on bad ticker — a raised ValueError here crashes
        # the live chat SSE stream; a returned string lets the LLM recover.
        try:
            norm = validate_ticker(ticker)
        except ValueError:
            return f"Invalid ticker symbol: {ticker}"
        # Coerce the enum up front: an unguarded DataType(bad) inside fetch()
        # raises ValueError that would tear down the SSE stream. ModelRetry feeds
        # the error back so the model self-corrects to a valid value.
        try:
            dt = DataType(data_type)
        except ValueError as exc:
            raise ModelRetry(
                f"Unknown data_type {data_type!r}. Valid values: {[d.value for d in DataType]}"
            ) from exc
        result = await ctx.deps.data_layer.fetch(dt, norm)
        return result.to_context_string()

    @agent.tool
    async def activate_skill(ctx: RunContext[FinRobotDeps], skill_id: str) -> str:
        """Activate a skill for ad-hoc professional workflows.
        Use this for tasks that don't have a dedicated pipeline."""
        if not ctx.deps.skill_runtime:
            return "Skill system is not yet available. Use direct data queries or pipeline commands instead."
        skill = ctx.deps.skill_runtime.get(skill_id)
        if not skill:
            return f"Unknown skill. Available: {ctx.deps.skill_runtime.list_ids()}"
        return skill.full_content

    # --- Mode B tools: pipeline dispatch for deep analysis ---
    #
    # Generated from the pipeline registry (the single source of truth) instead
    # of seven hand-copied @agent.tool wrappers. Adding a pipeline is now a
    # one-line change to engine/pipelines/registry.py. The tool NAME and the
    # LLM-facing DESCRIPTION come verbatim from each PipelineSpec — the
    # description is the LLM's tool-selection signal, so it carries the original
    # docstrings unchanged. ``ctx.deps`` and behaviour are identical to the old
    # wrappers (each still dispatches through ``_run_pipeline_tool``).
    spec: PipelineSpec
    for spec in iter_pipeline_specs():
        # Decorator form (keyword-only name/description) — the positional-arg
        # overload of agent.tool does not accept name/description.
        agent.tool(name=spec.tool_name, description=spec.tool_description)(
            _make_pipeline_tool(spec.factory(sub_agents))
        )

    return agent  # type: ignore[return-value]
