import base64
import logging
import statistics
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic_ai import Agent, RunContext

from finagent.config import FinAgentSettings
from finagent.engine.agents.factory import create_sub_agents
from finagent.engine.charts.base import ChartDataPoint
from finagent.engine.charts.eps_pe import render as render_eps_pe
from finagent.engine.charts.football_field import render as render_football_field
from finagent.engine.charts.margin_trend import render as render_margin_trend
from finagent.engine.charts.peer_comparison import render as render_peer_comparison
from finagent.engine.charts.radar import render as render_radar
from finagent.engine.charts.revenue_ebitda import render as render_revenue_ebitda
from finagent.engine.charts.revenue_yoy import render as render_revenue_yoy
from finagent.engine.charts.sensitivity import render as render_sensitivity
from finagent.engine.charts.time_series_multi import render as render_time_series_multi
from finagent.engine.charts.waterfall import render as render_waterfall
from finagent.engine.data.types import DataType
from finagent.engine.deps import FinAgentDeps
from finagent.engine.models.financial import (
    CatalystAnalysis,
    DCFResult,
    DDMResult,
    FinancialData,
    ForecastResult,
    HistoricalMetrics,
    LBOInputs,
    LBOResult,
    PeerComps,
    ThesisResult,
    ValuationSynthesis,
)
from finagent.engine.pipelines.base import Pipeline, PipelineResult
from finagent.engine.pipelines.comps import create_comps_pipeline
from finagent.engine.pipelines.dcf import create_dcf_pipeline
from finagent.engine.pipelines.ddm import create_ddm_pipeline
from finagent.engine.pipelines.earnings_analysis import create_earnings_analysis_pipeline
from finagent.engine.pipelines.equity_research import create_equity_research_pipeline
from finagent.engine.pipelines.ic_memo import create_ic_memo_pipeline
from finagent.engine.pipelines.lbo import create_lbo_pipeline
from finagent.engine.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


def _first_of_type(sd: Mapping[str, Any], keys: Iterable[str], cls: type[_T]) -> _T | None:
    """Return the first sd[key] that is an instance of cls, or None."""
    for key in keys:
        value = sd.get(key)
        if isinstance(value, cls):
            return value
    return None


def _safe_render(chart_name: str, render_fn: Any, *args: Any) -> str | None:
    """Call a chart render function; return base64 data URI or None on failure."""
    try:
        png_bytes: bytes = render_fn(*args)
        encoded = base64.b64encode(png_bytes).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    except (ValueError, TypeError, KeyError, IndexError, RuntimeError, AttributeError) as e:
        logger.warning("Chart '%s' skipped: %s", chart_name, e, exc_info=True)
        return None


def _generate_charts(
    *,
    fin: FinancialData | None,
    historical_metrics: HistoricalMetrics | None,
    forecast: ForecastResult | None,
    dcf_result: DCFResult | None,
    peer_comps: PeerComps | None,
    valuation_synthesis: ValuationSynthesis | None,
) -> dict[str, str]:
    """Generate all available charts from structured pipeline data.

    Each chart is wrapped in try/except so one failure never blocks the report.
    Returns a dict of chart_name → base64 data URI string.
    """
    charts: dict[str, str] = {}

    # --- Charts from HistoricalMetrics ---
    if historical_metrics and len(historical_metrics.years) >= 2:
        hm = historical_metrics
        years = hm.years

        # revenue_ebitda: grouped bars
        rev_ebitda_rows: list[dict[str, Any]] = []
        for i, y in enumerate(years):
            rev_ebitda_rows.append(
                {
                    "year": y,
                    "revenue": hm.revenue[i],
                    "ebitda": hm.ebitda[i],
                    "is_forecast": False,
                }
            )
        if forecast:
            for i, y in enumerate(forecast.years):
                rev_ebitda_rows.append(
                    {
                        "year": y,
                        "revenue": forecast.revenue[i],
                        "ebitda": forecast.ebitda[i],
                        "is_forecast": True,
                    }
                )
        data = ChartDataPoint(
            chart_type="revenue_ebitda",
            title=f"{hm.ticker} Revenue & EBITDA",
            data=rev_ebitda_rows,
        )
        uri = _safe_render("revenue_ebitda", render_revenue_ebitda, data)
        if uri:
            charts["revenue_ebitda"] = uri

        # margin_trend: 3 margin lines
        margin_rows: list[dict[str, Any]] = [
            {
                "year": years[i],
                "gross_margin": hm.gross_margin[i],
                "ebitda_margin": hm.ebitda_margin[i],
                "operating_margin": hm.operating_margin[i],
            }
            for i in range(len(years))
        ]
        data = ChartDataPoint(
            chart_type="margin_trend",
            title=f"{hm.ticker} Margin Trends",
            data=margin_rows,
        )
        uri = _safe_render("margin_trend", render_margin_trend, data)
        if uri:
            charts["margin_trend"] = uri

        # eps_pe
        eps_rows: list[dict[str, Any]] = [
            {"year": years[i], "eps": hm.eps[i], "pe_ratio": hm.pe_ratio[i]}
            for i in range(len(years))
        ]
        if forecast:
            for i, y in enumerate(forecast.years):
                eps_rows.append({"year": y, "eps": forecast.eps[i], "pe_ratio": None})
        data = ChartDataPoint(
            chart_type="eps_pe",
            title=f"{hm.ticker} EPS & P/E",
            data=eps_rows,
        )
        uri = _safe_render("eps_pe", render_eps_pe, data)
        if uri:
            charts["eps_pe"] = uri

        # revenue_yoy
        rev_yoy_rows: list[dict[str, Any]] = [
            {"year": str(years[i]), "revenue": hm.revenue[i]} for i in range(len(years))
        ]
        data = ChartDataPoint(
            chart_type="revenue_yoy",
            title=f"{hm.ticker} Revenue YoY Growth",
            data=rev_yoy_rows,
        )
        uri = _safe_render("revenue_yoy", render_revenue_yoy, data)
        if uri:
            charts["revenue_yoy"] = uri

        # time_series_multi: dual-axis (revenue + margin)
        ts_rows: list[dict[str, Any]] = [
            {
                "year": str(years[i]),
                "revenue": hm.revenue[i],
                "net_income": hm.net_income[i],
                "operating_margin": hm.operating_margin[i],
            }
            for i in range(len(years))
        ]
        data = ChartDataPoint(
            chart_type="time_series_multi",
            title=f"{hm.ticker} Key Metrics",
            data=ts_rows,
        )
        uri = _safe_render("time_series_multi", render_time_series_multi, data)
        if uri:
            charts["time_series_multi"] = uri

    # --- Charts from DCFResult ---
    if dcf_result:
        # sensitivity heatmap
        st = dcf_result.sensitivity_table
        if st and isinstance(st, dict):
            wacc_values = st.get("wacc_values", [])
            tg_values = st.get("tg_values", [])
            implied_prices = st.get("implied_prices", [])
            if wacc_values and tg_values and implied_prices:
                sens_rows: list[dict[str, Any]] = []
                for i, w in enumerate(wacc_values):
                    for j, tg in enumerate(tg_values):
                        price = (
                            implied_prices[i][j]
                            if i < len(implied_prices) and j < len(implied_prices[i])
                            else None
                        )
                        sens_rows.append({"wacc": w, "tg": tg, "implied_price": price})
                data = ChartDataPoint(
                    chart_type="sensitivity",
                    title="DCF Sensitivity",
                    data=sens_rows,
                )
                uri = _safe_render("sensitivity", render_sensitivity, data)
                if uri:
                    charts["sensitivity"] = uri

        # waterfall: EV bridge
        wf_rows: list[dict[str, Any]] = [
            {"label": "PV of FCFs", "value": dcf_result.pv_fcf_total, "is_total": False},
            {"label": "PV Terminal", "value": dcf_result.pv_terminal, "is_total": False},
            {
                "label": "Enterprise Value",
                "value": dcf_result.pv_fcf_total + dcf_result.pv_terminal,
                "is_total": True,
            },
        ]
        data = ChartDataPoint(chart_type="waterfall", title="DCF Waterfall", data=wf_rows)
        uri = _safe_render("waterfall", render_waterfall, data)
        if uri:
            charts["waterfall"] = uri

    # --- Charts from PeerComps ---
    if peer_comps:
        # peer_comparison: horizontal bars
        pc_rows: list[dict[str, Any]] = []
        pc_rows.append(
            {
                "ticker": peer_comps.target.ticker,
                "ev_ebitda": peer_comps.target.ev_ebitda or 0,
                "is_target": True,
            }
        )
        for p in peer_comps.peers:
            pc_rows.append(
                {
                    "ticker": p.ticker,
                    "ev_ebitda": p.ev_ebitda or 0,
                    "is_target": False,
                }
            )
        data = ChartDataPoint(
            chart_type="peer_comparison",
            title="EV/EBITDA Peer Comparison",
            data=pc_rows,
        )
        uri = _safe_render("peer_comparison", render_peer_comparison, data)
        if uri:
            charts["peer_comparison"] = uri

        # radar: target vs peer median
        target = peer_comps.target
        if peer_comps.peers:

            def _median(vals: list[float]) -> float:
                return statistics.median(vals) if vals else 0.0

            peer_gm = [p.gross_margin for p in peer_comps.peers if p.gross_margin]
            peer_om = [p.operating_margin for p in peer_comps.peers if p.operating_margin]
            peer_ev = [p.ev_ebitda for p in peer_comps.peers if p.ev_ebitda]

            radar_rows: list[dict[str, Any]] = [
                {
                    "dimension": "Gross Margin",
                    "value": target.gross_margin,
                    "benchmark": _median(peer_gm),
                },
                {
                    "dimension": "Op. Margin",
                    "value": target.operating_margin,
                    "benchmark": _median(peer_om),
                },
                {
                    "dimension": "EV/EBITDA",
                    "value": target.ev_ebitda or 0,
                    "benchmark": _median(peer_ev),
                },
            ]
            data = ChartDataPoint(
                chart_type="radar", title=f"{target.ticker} vs Peers", data=radar_rows
            )
            uri = _safe_render("radar", render_radar, data)
            if uri:
                charts["radar"] = uri

    # --- Charts from ValuationSynthesis ---
    if valuation_synthesis and valuation_synthesis.methods:
        ff_rows: list[dict[str, Any]] = [
            {"method": m.name, "low": m.low, "mid": m.mid, "high": m.high}
            for m in valuation_synthesis.methods
        ]
        data = ChartDataPoint(
            chart_type="football_field",
            title="Valuation Range",
            data=ff_rows,
        )
        uri = _safe_render("football_field", render_football_field, data)
        if uri:
            charts["football_field"] = uri

    logger.info("Generated %d charts: %s", len(charts), list(charts.keys()))
    return charts


async def _run_pipeline_tool(
    ctx: RunContext[FinAgentDeps], ticker: str, pipeline: Pipeline
) -> dict[str, Any]:
    """Execute a pipeline, cache its report context, and return the tool summary dict.

    Shared dispatch for every @agent.tool that wraps a Pipeline — keeps the
    execute/cache/return-shape contract identical across all run_* tools.
    """
    result = await pipeline.execute(ctx.deps, ticker)
    ctx.deps.report_cache[ticker.upper()] = build_report_context(ticker, result)
    return {
        "summary": result.format_summary(),
        "artifact_id": result.artifact_id,
        "ticker": ticker.upper(),
    }


def _collect_warnings(result: PipelineResult) -> list[str]:
    """Collect all warnings from structured data for the Data Source Notes section."""
    warnings: list[str] = []
    for model in result.structured_data.values():
        if hasattr(model, "warnings"):
            for w in model.warnings:
                if w not in warnings:
                    warnings.append(w)
    return warnings


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

    fin = _first_of_type(sd, ("data_collection", "historical_data", "target_data"), FinancialData)
    dcf_result = _first_of_type(sd, ("financial_modeling", "dcf_calc"), DCFResult)
    peer_comps = _first_of_type(sd, ("peer_analysis", "statistical_bench"), PeerComps)
    thesis = _first_of_type(sd, ("thesis",), ThesisResult)
    historical_metrics = _first_of_type(sd, ("historical_metrics",), HistoricalMetrics)
    forecast = _first_of_type(sd, ("forecast",), ForecastResult)
    catalyst_analysis = _first_of_type(sd, ("catalyst_analysis",), CatalystAnalysis)
    valuation_synthesis = _first_of_type(sd, ("valuation_synthesis",), ValuationSynthesis)
    lbo_inputs = _first_of_type(sd, ("lbo_parameters",), LBOInputs)
    lbo_result = _first_of_type(sd, ("lbo_calculation",), LBOResult)
    ddm_result = _first_of_type(sd, ("ddm_calc",), DDMResult)

    logger.info(
        "build_report_context: sd_keys=%s hm=%s forecast=%s dcf=%s peers=%s vs=%s",
        list(sd.keys()),
        type(historical_metrics).__name__ if historical_metrics else None,
        type(forecast).__name__ if forecast else None,
        type(dcf_result).__name__ if dcf_result else None,
        type(peer_comps).__name__ if peer_comps else None,
        type(valuation_synthesis).__name__ if valuation_synthesis else None,
    )

    charts = _generate_charts(
        fin=fin,
        historical_metrics=historical_metrics,
        forecast=forecast,
        dcf_result=dcf_result,
        peer_comps=peer_comps,
        valuation_synthesis=valuation_synthesis,
    )

    return {
        "ticker": ticker.upper(),
        "company_name": (fin.company_name or fin.ticker) if fin else ticker.upper(),
        "current_price": fin.market.current_price if fin else 0,
        "market_cap": fin.market.market_cap if fin else 0,
        "recommendation": thesis.recommendation if thesis else "N/A",
        "price_target": thesis.price_target if thesis else 0,
        "charts": charts,
        "historical_metrics": historical_metrics,
        "forecast": forecast,
        "dcf_result": dcf_result,
        "peer_comps": peer_comps,
        "catalyst_analysis": catalyst_analysis,
        "valuation_synthesis": valuation_synthesis,
        "lbo_inputs": lbo_inputs,
        "lbo_result": lbo_result,
        "ddm_result": ddm_result,
        "report_date": datetime.now().strftime("%B %d, %Y"),
        "data_source": fin.data_source if fin else "N/A",
        "data_timestamp": fin.timestamp.strftime("%Y-%m-%d %H:%M UTC") if fin else "N/A",
        "sector": "Technology",  # placeholder, can be enhanced later
        "thesis_text": thesis.price_target_basis if thesis else "",
        "report_text": result.steps.get("report", ""),
        "data_warnings": _collect_warnings(result),
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
