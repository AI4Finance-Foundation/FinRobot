import logging
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, RunContext

from finagent.config import FinAgentSettings
from finagent.engine.agents.factory import create_sub_agents
from finagent.engine.data.types import DataType
from finagent.engine.deps import FinAgentDeps
from finagent.engine.pipelines.base import Pipeline
from finagent.engine.pipelines.comps import create_comps_pipeline
from finagent.engine.pipelines.dcf import create_dcf_pipeline
from finagent.engine.pipelines.ddm import create_ddm_pipeline
from finagent.engine.pipelines.earnings_analysis import create_earnings_analysis_pipeline
from finagent.engine.pipelines.equity_research import create_equity_research_pipeline
from finagent.engine.pipelines.ic_memo import create_ic_memo_pipeline
from finagent.engine.pipelines.lbo import create_lbo_pipeline
from finagent.engine.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


async def _run_pipeline_tool(
    ctx: RunContext[FinAgentDeps], ticker: str, pipeline: Pipeline
) -> dict[str, Any]:
    """Execute a pipeline and return the tool summary dict.

    Shared dispatch for every @agent.tool that wraps a Pipeline — every result
    is persisted to ArtifactStore by the pipeline itself; the tool returns the
    artifact_id so the caller can route to the detail page.
    """
    result = await pipeline.execute(ctx.deps, ticker)
    return {
        "summary": result.format_summary(),
        "artifact_id": result.artifact_id,
        "ticker": ticker.upper(),
    }


def create_lead_agent(
    settings: FinAgentSettings,
    skill_registry: SkillRegistry | None = None,
    sub_agents: dict[str, Agent] | None = None,
) -> Agent:
    """Factory: create lead agent with tools and instructions.

    ``sub_agents`` lets the caller share a single set of sub-agents with the
    pipeline dispatcher (``app.state.sub_agents``) so the LLM-side and the
    REST-side don't double-create connections. When None, builds its own.
    """
    instructions = (Path(__file__).parent / "instructions.md").read_text()
    if skill_registry:
        instructions += "\n\n" + skill_registry.list_summary()

    agent: Agent[FinAgentDeps, str] = Agent(
        settings.create_model(),
        deps_type=FinAgentDeps,
        instructions=instructions,
    )

    if sub_agents is None:
        sub_agents = create_sub_agents(settings, skill_registry)

    # --- Mode A tools: conversational, direct response ---

    @agent.tool
    async def query_financial_data(
        ctx: RunContext[FinAgentDeps], ticker: str, data_type: str | DataType
    ) -> str:
        """Fetch financial data for quick questions.
        data_type: one of DataType values (financials, price, news, earnings, filings, 10k_rag)"""
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

    equity_pipeline = create_equity_research_pipeline(sub_agents)

    @agent.tool
    async def run_equity_research(ctx: RunContext[FinAgentDeps], ticker: str) -> dict[str, Any]:
        """Generate a comprehensive equity research report.
        Uses a multi-step enforced pipeline. Takes 30-120 seconds.
        Use this when the user asks for: equity research, initiating coverage,
        stock analysis report, investment thesis, or deep-dive analysis."""
        return await _run_pipeline_tool(ctx, ticker, equity_pipeline)

    comps_pipeline = create_comps_pipeline(sub_agents)

    @agent.tool
    async def run_comps_analysis(ctx: RunContext[FinAgentDeps], ticker: str) -> dict[str, Any]:
        """Build a comparable company analysis.
        Uses a multi-step enforced pipeline.
        Use when user asks for: comps, comparable companies, peer analysis,
        trading multiples comparison."""
        return await _run_pipeline_tool(ctx, ticker, comps_pipeline)

    dcf_pipeline = create_dcf_pipeline(sub_agents)

    @agent.tool
    async def run_dcf_valuation(ctx: RunContext[FinAgentDeps], ticker: str) -> dict[str, Any]:
        """Run a DCF valuation model.
        Uses a multi-step enforced pipeline.
        Use when user asks for: DCF, discounted cash flow, intrinsic value,
        valuation model."""
        return await _run_pipeline_tool(ctx, ticker, dcf_pipeline)

    lbo_pipeline = create_lbo_pipeline(sub_agents)

    @agent.tool
    async def run_lbo_analysis(ctx: RunContext[FinAgentDeps], ticker: str) -> dict[str, Any]:
        """Run an LBO (leveraged buyout) analysis.
        Uses a multi-step enforced pipeline with deterministic IRR/MOIC math.
        Use when user asks for: LBO, leveraged buyout, private equity analysis,
        buyout returns, IRR analysis, MOIC."""
        return await _run_pipeline_tool(ctx, ticker, lbo_pipeline)

    ddm_pipeline = create_ddm_pipeline(sub_agents)

    @agent.tool
    async def run_ddm_valuation(ctx: RunContext[FinAgentDeps], ticker: str) -> dict[str, Any]:
        """Run a DDM (Dividend Discount Model) valuation.
        Uses a multi-step enforced pipeline with deterministic dividend-based math.
        Use when user asks for: DDM, dividend discount model, bank valuation,
        or when the company is a bank/financial institution.
        Also auto-selected when 'finagent dcf' detects a bank."""
        return await _run_pipeline_tool(ctx, ticker, ddm_pipeline)

    earnings_pipeline = create_earnings_analysis_pipeline(sub_agents)

    @agent.tool
    async def run_earnings_analysis(ctx: RunContext[FinAgentDeps], ticker: str) -> dict[str, Any]:
        """Run an earnings quality analysis (beat rate, surprise trends, streak).
        Uses a multi-step enforced pipeline with deterministic beat/miss classification.
        Use when user asks for: earnings analysis, earnings quality, beat rate,
        earnings surprise, EPS trend."""
        return await _run_pipeline_tool(ctx, ticker, earnings_pipeline)

    ic_memo_pipeline = create_ic_memo_pipeline(sub_agents)

    @agent.tool
    async def run_ic_memo(ctx: RunContext[FinAgentDeps], ticker: str) -> dict[str, Any]:
        """Generate an Investment Committee (IC) memo with DCF + LBO analysis.
        Uses a multi-step pipeline with IRR hurdle gate (PASS if IRR < 15%).
        Use when user asks for: IC memo, investment committee memo, PE analysis,
        buyout memo, invest/pass recommendation."""
        return await _run_pipeline_tool(ctx, ticker, ic_memo_pipeline)

    return agent  # type: ignore[return-value]
