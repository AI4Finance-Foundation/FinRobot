import logging
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, ModelRetry, RunContext

from finrobot.config import FinRobotSettings
from finrobot.engine.agents.factory import create_sub_agents
from finrobot.engine.data.ticker import validate_ticker
from finrobot.engine.data.types import DataType
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.pipelines.base import Pipeline
from finrobot.engine.pipelines.comps import create_comps_pipeline
from finrobot.engine.pipelines.dcf import create_dcf_pipeline
from finrobot.engine.pipelines.ddm import create_ddm_pipeline
from finrobot.engine.pipelines.earnings_analysis import create_earnings_analysis_pipeline
from finrobot.engine.pipelines.equity_research import create_equity_research_pipeline
from finrobot.engine.pipelines.ic_memo import create_ic_memo_pipeline
from finrobot.engine.pipelines.lbo import create_lbo_pipeline
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

    equity_pipeline = create_equity_research_pipeline(sub_agents)

    @agent.tool
    async def run_equity_research(
        ctx: RunContext[FinRobotDeps], ticker: str
    ) -> dict[str, Any] | str:
        """Generate a comprehensive equity research report.
        Uses a multi-step enforced pipeline. Takes 30-120 seconds.
        Use this when the user asks for: equity research, initiating coverage,
        stock analysis report, investment thesis, or deep-dive analysis."""
        return await _run_pipeline_tool(ctx, ticker, equity_pipeline)

    comps_pipeline = create_comps_pipeline(sub_agents)

    @agent.tool
    async def run_comps_analysis(
        ctx: RunContext[FinRobotDeps], ticker: str
    ) -> dict[str, Any] | str:
        """Build a comparable company analysis.
        Uses a multi-step enforced pipeline.
        Use when user asks for: comps, comparable companies, peer analysis,
        trading multiples comparison."""
        return await _run_pipeline_tool(ctx, ticker, comps_pipeline)

    dcf_pipeline = create_dcf_pipeline(sub_agents)

    @agent.tool
    async def run_dcf_valuation(ctx: RunContext[FinRobotDeps], ticker: str) -> dict[str, Any] | str:
        """Run a DCF valuation model.
        Uses a multi-step enforced pipeline.
        Use when user asks for: DCF, discounted cash flow, intrinsic value,
        valuation model."""
        return await _run_pipeline_tool(ctx, ticker, dcf_pipeline)

    lbo_pipeline = create_lbo_pipeline(sub_agents)

    @agent.tool
    async def run_lbo_analysis(ctx: RunContext[FinRobotDeps], ticker: str) -> dict[str, Any] | str:
        """Run an LBO (leveraged buyout) analysis.
        Uses a multi-step enforced pipeline with deterministic IRR/MOIC math.
        Use when user asks for: LBO, leveraged buyout, private equity analysis,
        buyout returns, IRR analysis, MOIC."""
        return await _run_pipeline_tool(ctx, ticker, lbo_pipeline)

    ddm_pipeline = create_ddm_pipeline(sub_agents)

    @agent.tool
    async def run_ddm_valuation(ctx: RunContext[FinRobotDeps], ticker: str) -> dict[str, Any] | str:
        """Run a DDM (Dividend Discount Model) valuation.
        Uses a multi-step enforced pipeline with deterministic dividend-based math.
        Use when user asks for: DDM, dividend discount model, bank valuation,
        or when the company is a bank/financial institution.
        Also auto-selected when 'finrobot dcf' detects a bank."""
        return await _run_pipeline_tool(ctx, ticker, ddm_pipeline)

    earnings_pipeline = create_earnings_analysis_pipeline(sub_agents)

    @agent.tool
    async def run_earnings_analysis(
        ctx: RunContext[FinRobotDeps], ticker: str
    ) -> dict[str, Any] | str:
        """Run an earnings quality analysis (beat rate, surprise trends, streak).
        Uses a multi-step enforced pipeline with deterministic beat/miss classification.
        Use when user asks for: earnings analysis, earnings quality, beat rate,
        earnings surprise, EPS trend."""
        return await _run_pipeline_tool(ctx, ticker, earnings_pipeline)

    ic_memo_pipeline = create_ic_memo_pipeline(sub_agents)

    @agent.tool
    async def run_ic_memo(ctx: RunContext[FinRobotDeps], ticker: str) -> dict[str, Any] | str:
        """Generate an Investment Committee (IC) memo with DCF + LBO analysis.
        Uses a multi-step pipeline with IRR hurdle gate (PASS if IRR < 15%).
        Use when user asks for: IC memo, investment committee memo, PE analysis,
        buyout memo, invest/pass recommendation."""
        return await _run_pipeline_tool(ctx, ticker, ic_memo_pipeline)

    return agent  # type: ignore[return-value]
