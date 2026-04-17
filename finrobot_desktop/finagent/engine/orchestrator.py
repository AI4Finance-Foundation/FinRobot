from pathlib import Path
from typing import Any

from pydantic_ai import Agent, RunContext

from finagent.config import FinAgentSettings
from finagent.engine.agents.factory import create_sub_agents
from finagent.engine.deps import FinAgentDeps
from finagent.engine.models.financial import (
    DCFResult,
    FinancialData,
    LBOInputs,
    LBOResult,
    PeerComps,
    ThesisResult,
    CatalystAnalysis,
    ForecastResult,
    HistoricalMetrics,
    ValuationSynthesis,
)
from finagent.engine.data.types import DataType
from finagent.engine.pipelines.base import PipelineResult
from finagent.engine.skills.registry import SkillRegistry


def build_report_context(ticker: str, result: PipelineResult) -> dict[str, Any]:
    """Extract structured data from PipelineResult into a report template context.

    Handles three pipeline types by probing known step names:
    - equity_research: data_collection, peer_analysis, financial_modeling, thesis
    - dcf: historical_data, dcf_calc
    - comps: target_data, statistical_bench

    **What this code does that raw LLM cannot**: deterministic field extraction
    from typed Pydantic models into a flat dict keyed for Jinja2 templates.
    No LLM calls, no computation — pure structural mapping.
    """
    sd = result.structured_data

    # Find FinancialData from whichever step produced it
    fin: FinancialData | None = None
    for key in ("data_collection", "historical_data", "target_data"):
        candidate = sd.get(key)
        if isinstance(candidate, FinancialData):
            fin = candidate
            break

    # Extract typed models from known step names
    dcf_result: DCFResult | None = None
    for key in ("financial_modeling", "dcf_calc"):
        candidate = sd.get(key)
        if isinstance(candidate, DCFResult):
            dcf_result = candidate
            break

    peer_comps: PeerComps | None = None
    for key in ("peer_analysis", "statistical_bench"):
        candidate = sd.get(key)
        if isinstance(candidate, PeerComps):
            peer_comps = candidate
            break

    thesis: ThesisResult | None = None
    candidate = sd.get("thesis")
    if isinstance(candidate, ThesisResult):
        thesis = candidate

    # Optional models (may not exist yet in all pipelines)
    historical_metrics = sd.get("historical_metrics")
    if not isinstance(historical_metrics, HistoricalMetrics):
        historical_metrics = None

    forecast = sd.get("forecast")
    if not isinstance(forecast, ForecastResult):
        forecast = None

    catalyst_analysis = sd.get("catalyst_analysis")
    if not isinstance(catalyst_analysis, CatalystAnalysis):
        catalyst_analysis = None

    valuation_synthesis = sd.get("valuation_synthesis")
    if not isinstance(valuation_synthesis, ValuationSynthesis):
        valuation_synthesis = None

    lbo_inputs = sd.get("lbo_parameters")
    if not isinstance(lbo_inputs, LBOInputs):
        lbo_inputs = None

    lbo_result = sd.get("lbo_calculation")
    if not isinstance(lbo_result, LBOResult):
        lbo_result = None

    return {
        "ticker": ticker.upper(),
        "company_name": fin.ticker if fin else ticker.upper(),
        "current_price": fin.market.current_price if fin else 0,
        "market_cap": fin.market.market_cap if fin else 0,
        "recommendation": thesis.recommendation if thesis else "N/A",
        "price_target": thesis.price_target if thesis else 0,
        "charts": {},
        "historical_metrics": historical_metrics,
        "forecast": forecast,
        "dcf_result": dcf_result,
        "peer_comps": peer_comps,
        "catalyst_analysis": catalyst_analysis,
        "valuation_synthesis": valuation_synthesis,
        "lbo_inputs": lbo_inputs,
        "lbo_result": lbo_result,
    }


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
        settings.create_model(),
        deps_type=FinAgentDeps,
        instructions=instructions,
    )

    # Create sub-agents for pipelines
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

    from finagent.engine.pipelines.equity_research import create_equity_research_pipeline

    equity_pipeline = create_equity_research_pipeline(sub_agents)

    @agent.tool
    async def run_equity_research(ctx: RunContext[FinAgentDeps], ticker: str) -> str:
        """Generate a comprehensive equity research report.
        Uses a multi-step enforced pipeline. Takes 30-120 seconds.
        Use this when the user asks for: equity research, initiating coverage,
        stock analysis report, investment thesis, or deep-dive analysis."""
        result = await equity_pipeline.execute(ctx.deps, ticker)
        ctx.deps.report_cache[ticker.upper()] = build_report_context(ticker, result)
        return result.format_summary()

    from finagent.engine.pipelines.comps import create_comps_pipeline

    comps_pipeline = create_comps_pipeline(sub_agents)

    @agent.tool
    async def run_comps_analysis(ctx: RunContext[FinAgentDeps], ticker: str) -> str:
        """Build a comparable company analysis.
        Uses a multi-step enforced pipeline.
        Use when user asks for: comps, comparable companies, peer analysis,
        trading multiples comparison."""
        result = await comps_pipeline.execute(ctx.deps, ticker)
        ctx.deps.report_cache[ticker.upper()] = build_report_context(ticker, result)
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
        ctx.deps.report_cache[ticker.upper()] = build_report_context(ticker, result)
        return result.format_summary()

    from finagent.engine.pipelines.lbo import create_lbo_pipeline

    lbo_pipeline = create_lbo_pipeline(sub_agents)

    @agent.tool
    async def run_lbo_analysis(ctx: RunContext[FinAgentDeps], ticker: str) -> str:
        """Run an LBO (leveraged buyout) analysis.
        Uses a multi-step enforced pipeline with deterministic IRR/MOIC math.
        Use when user asks for: LBO, leveraged buyout, private equity analysis,
        buyout returns, IRR analysis, MOIC."""
        result = await lbo_pipeline.execute(ctx.deps, ticker)
        ctx.deps.report_cache[ticker.upper()] = build_report_context(ticker, result)
        return result.format_summary()

    from finagent.engine.pipelines.earnings_analysis import create_earnings_analysis_pipeline

    earnings_pipeline = create_earnings_analysis_pipeline(sub_agents)

    @agent.tool
    async def run_earnings_analysis(ctx: RunContext[FinAgentDeps], ticker: str) -> str:
        """Run an earnings quality analysis (beat rate, surprise trends, streak).
        Uses a multi-step enforced pipeline with deterministic beat/miss classification.
        Use when user asks for: earnings analysis, earnings quality, beat rate,
        earnings surprise, EPS trend."""
        result = await earnings_pipeline.execute(ctx.deps, ticker)
        ctx.deps.report_cache[ticker.upper()] = build_report_context(ticker, result)
        return result.format_summary()

    from finagent.engine.pipelines.ic_memo import create_ic_memo_pipeline

    ic_memo_pipeline = create_ic_memo_pipeline(sub_agents)

    @agent.tool
    async def run_ic_memo(ctx: RunContext[FinAgentDeps], ticker: str) -> str:
        """Generate an Investment Committee (IC) memo with DCF + LBO analysis.
        Uses a multi-step pipeline with IRR hurdle gate (PASS if IRR < 15%).
        Use when user asks for: IC memo, investment committee memo, PE analysis,
        buyout memo, invest/pass recommendation."""
        result = await ic_memo_pipeline.execute(ctx.deps, ticker)
        ctx.deps.report_cache[ticker.upper()] = build_report_context(ticker, result)
        return result.format_summary()

    return agent  # type: ignore[return-value]
