from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.exceptions import AgentRunError

from finagent.engine.data.interface import ProviderError
from finagent.engine.data.types import DataType
from finagent.engine.deps import FinAgentDeps
from finagent.engine.models.financial import (
    CatalystAnalysis,
    FinancialData,
    CompanyFinancials,
    PeerComps,
    PeerSelection,
    DCFInputs,
    DCFResult,
    ThesisResult,
    StepOutput,
)
from finagent.engine.compute.catalyst import (
    extract_catalysts_from_news,
    compute_expected_impact,
    summarize_catalyst_outlook,
)
from finagent.engine.compute.extractor import extract_company_financials
from finagent.engine.compute.multiples import calculate_multiples, calculate_peer_statistics
from finagent.engine.compute.dcf import calculate_dcf, calculate_sensitivity
from finagent.engine.compute.news import fetch_news, classify_news
from finagent.engine.pipelines.base import (
    Pipeline, PipelineStep, StructuredValidator, TextValidator,
)
from finagent.engine.pipelines._helpers import execute_financial_data_step
from finagent.engine.pipelines.validators import (
    validate_catalyst_analysis,
    validate_has_fields,
    validate_has_peers,
    validate_has_thesis,
    validate_report_format,
    validate_is_non_empty,
    validate_financial_data,
    validate_peer_comps,
    validate_dcf_result,
    validate_thesis,
)

logger = logging.getLogger(__name__)


async def _execute_catalyst_analysis(
    agent: Agent[Any, Any],
    deps: FinAgentDeps,
    prompt: str,
    structured_context: dict[str, object],
    ticker: str,
) -> StepOutput:
    """Fetch news, classify, extract catalysts, compute impact, summarize.

    What this code does that raw LLM cannot:
    - Deterministic extraction of catalyst events from classified news
    - Quantitative expected-impact scoring with sentiment multiplier
    - Structured summary with net sentiment, category breakdown, top events
    - All computation is reproducible -- no LLM randomness in scoring
    """
    # Fetch and classify news
    raw_news = await fetch_news(deps.data_layer, ticker)
    news_items = await classify_news(raw_news, deps)

    # Extract catalysts from high-importance news
    catalysts = extract_catalysts_from_news(news_items)
    catalysts = compute_expected_impact(catalysts)
    summary = summarize_catalyst_outlook(catalysts)

    # Build CatalystAnalysis
    net = summary["net_sentiment"]
    overall: Literal["bullish", "bearish", "neutral"]
    if net > 0.5:
        overall = "bullish"
    elif net < -0.5:
        overall = "bearish"
    else:
        overall = "neutral"

    top_pos = summary["top_positive"]
    analysis = CatalystAnalysis(
        events=catalysts,
        overall_sentiment=overall,
        key_catalysts=[e.headline for e in top_pos[:3]],
        net_sentiment=net,
        category_breakdown=summary["category_breakdown"],
        top_positive=summary["top_positive"],
        top_negative=summary["top_negative"],
    )

    # Build narrative
    cat_labels = ", ".join(
        f"{cat}({cnt})" for cat, cnt in summary["category_breakdown"].items()
    )
    narrative = (
        f"Catalyst analysis: {summary['total_catalysts']} events identified. "
        f"Net sentiment: {net:+.2f} ({overall}). "
        f"Categories: {cat_labels or 'none'}."
    )
    if top_pos:
        narrative += f" Top catalyst: {top_pos[0].headline}."

    return StepOutput(text=narrative, structured=analysis)


async def _execute_peer_analysis(
    agent: Agent[Any, Any],
    deps: FinAgentDeps,
    prompt: str,
    structured_context: dict[str, object],
    ticker: str,
) -> StepOutput:
    """LLM selects peer tickers (structured output); code fetches and computes multiples."""
    peer_agent = Agent(
        deps.settings.create_model(),
        output_type=PeerSelection,
        instructions=(
            "Select 3-5 comparable publicly traded companies for peer analysis. "
            "Choose companies in the same sector with similar business models and market cap. "
            "Return valid ticker symbols only (e.g. MSFT, GOOGL, not 'Microsoft')."
        ),
        defer_model_check=True,
    )
    try:
        peer_result = await peer_agent.run(prompt, deps=deps)  # type: ignore[call-overload]
        selection = peer_result.output
    except (AgentRunError, ValidationError, ValueError) as e:
        raise ValueError(f"Failed to select peer companies: {e}") from e

    async def _fetch_one_peer(peer_ticker: str) -> CompanyFinancials | None:
        try:
            fin_result = await deps.data_layer.fetch(DataType.FINANCIALS, peer_ticker)
            company = extract_company_financials(fin_result)
            return calculate_multiples(company)
        except (ProviderError, ValueError, KeyError, ArithmeticError) as e:
            logger.warning(f"Skipping peer {peer_ticker}: {e}")
            return None

    peer_results = await asyncio.gather(*[_fetch_one_peer(t) for t in selection.tickers])
    peers: list[CompanyFinancials] = [p for p in peer_results if p is not None]

    if len(peers) < 3:
        raise ValueError(
            f"Only {len(peers)} peers fetched successfully (need >=3). "
            f"Attempted: {selection.tickers}."
        )

    target_fin_raw = structured_context.get("data_collection")
    if not isinstance(target_fin_raw, FinancialData):
        raise ValueError(
            "data_collection structured output not available; cannot build peer target."
        )
    target_fin = target_fin_raw
    target = CompanyFinancials(
        ticker=ticker,
        revenue=target_fin.income.revenue,
        ebitda=target_fin.income.ebitda,
        net_income=target_fin.income.net_income,
        market_cap=target_fin.market.market_cap,
        total_debt=target_fin.balance.total_debt,
        total_cash=target_fin.balance.total_cash,
        gross_margin=target_fin.income.gross_margin,
        operating_margin=target_fin.income.operating_margin,
    )
    target = calculate_multiples(target)

    peer_comps = PeerComps(
        target=target,
        peers=peers,
        peer_justification=selection.rationale,
    )
    peer_comps = calculate_peer_statistics(peer_comps)

    ev_ebitda_str = (
        f"{peer_comps.median_ev_ebitda:.1f}x" if peer_comps.median_ev_ebitda is not None else "N/A"
    )
    pe_str = f"{peer_comps.median_pe:.1f}x" if peer_comps.median_pe is not None else "N/A"
    narrative = (
        f"Peer set ({len(peers)} companies): {', '.join(p.ticker for p in peers)}. "
        f"Median EV/EBITDA: {ev_ebitda_str}. "
        f"Median P/E: {pe_str}. "
        f"{selection.rationale}"
    )
    return StepOutput(text=narrative, structured=peer_comps)


async def _execute_financial_modeling(
    agent: Agent[Any, Any],
    deps: FinAgentDeps,
    prompt: str,
    structured_context: dict[str, object],
    ticker: str,
) -> StepOutput:
    """param_agent selects DCF assumptions; calculate_dcf() does all math."""
    param_agent = Agent(
        deps.settings.create_model(),
        output_type=DCFInputs,
        instructions=(
            "Select DCF valuation parameters based on the financial data and peer analysis. "
            "Use conservative assumptions. Revenue growth rates must reflect realistic projections. "
            "WACC inputs must be internally consistent."
            "\n\nFor each assumption you select, provide a brief justification in the "
            "assumption_provenance dict. "
            "Keys should be the field name (e.g., 'revenue_growth_rates', 'ebitda_margin', "
            "'terminal_growth_rate', 'beta'). "
            "Values should be one sentence explaining why (e.g., 'Based on 5-year CAGR of "
            "8.2% with deceleration assumption')."
        ),
        defer_model_check=True,
    )
    try:
        param_result = await param_agent.run(prompt, deps=deps)  # type: ignore[call-overload]
        dcf_inputs = param_result.output
    except (AgentRunError, ValidationError, ValueError) as e:
        raise ValueError(f"LLM failed to produce valid DCF parameters: {e}") from e

    try:
        dcf_result = calculate_dcf(dcf_inputs)
    except (ValueError, ArithmeticError) as e:
        raise ValueError(f"DCF calculation failed with provided parameters: {e}") from e
    wacc_range, tg_range = _build_sensitivity_ranges(dcf_result)
    sensitivity = calculate_sensitivity(dcf_inputs, wacc_range=wacc_range, tg_range=tg_range)
    dcf_result = dcf_result.model_copy(update={"sensitivity_table": sensitivity})

    valid_prices = [
        p for row in sensitivity["implied_prices"] for p in row if p is not None and p > 0
    ]
    price_range = f"${min(valid_prices):.0f}-${max(valid_prices):.0f}" if valid_prices else "N/A"
    narrative = (
        f"DCF base case implies ${dcf_result.implied_price:.2f} per share. "
        f"WACC: {dcf_result.wacc:.1%}, Terminal growth: {dcf_inputs.terminal_growth_rate:.1%}. "
        f"Enterprise value: ${dcf_result.enterprise_value / 1e9:.1f}B. "
        f"Sensitivity range: {price_range}."
    )

    # Build ValuationSynthesis from DCF + peer comps for football field chart.
    fin = structured_context.get("data_collection")
    current_price = fin.market.current_price if hasattr(fin, "market") else 0
    if current_price > 0:
        from finagent.engine.pipelines._helpers import build_valuation_synthesis

        vs = build_valuation_synthesis(structured_context, current_price)
        if vs is not None:
            structured_context["valuation_synthesis"] = vs

    return StepOutput(text=narrative, structured=dcf_result)


async def _execute_thesis(
    agent: Agent[Any, Any],
    deps: FinAgentDeps,
    prompt: str,
    structured_context: dict[str, object],
    ticker: str,
) -> StepOutput:
    """synthesis_agent writes thesis with structured output."""
    # Inject catalyst context into the thesis prompt if available
    catalyst_section = ""
    catalyst_data = structured_context.get("catalyst_analysis")
    if isinstance(catalyst_data, CatalystAnalysis):
        cat_lines = [
            f"Catalyst outlook: {catalyst_data.overall_sentiment} "
            f"(net sentiment: {catalyst_data.net_sentiment:+.2f})"
        ]
        if catalyst_data.top_positive:
            cat_lines.append("Key positive catalysts:")
            for e in catalyst_data.top_positive[:3]:
                cat_lines.append(f"  - {e.headline} (impact: {e.impact_score}, {e.category})")
        if catalyst_data.top_negative:
            cat_lines.append("Key negative catalysts:")
            for e in catalyst_data.top_negative[:3]:
                cat_lines.append(f"  - {e.headline} (impact: {e.impact_score}, {e.category})")
        if catalyst_data.category_breakdown:
            breakdown = ", ".join(
                f"{cat}: {cnt}" for cat, cnt in catalyst_data.category_breakdown.items()
            )
            cat_lines.append(f"Category breakdown: {breakdown}")
        catalyst_section = "\n".join(cat_lines)

    thesis_prompt = prompt
    if catalyst_section:
        thesis_prompt = f"{prompt}\n\nCatalyst Analysis:\n{catalyst_section}"

    synthesis_agent = Agent(
        deps.settings.create_model(),
        output_type=ThesisResult,
        instructions=(
            "Write an investment thesis based on the DCF valuation, peer analysis, "
            "and catalyst analysis. "
            "Reference specific catalysts from the catalyst analysis when discussing "
            "upside drivers and risks. "
            "Provide a recommendation (Buy/Hold/Sell), price target, catalysts, and risks."
        ),
        defer_model_check=True,
    )
    try:
        result = await synthesis_agent.run(thesis_prompt, deps=deps)  # type: ignore[call-overload]
        thesis = result.output
    except (AgentRunError, ValidationError, ValueError) as e:
        raise ValueError(f"LLM failed to produce valid thesis: {e}") from e

    narrative = (
        f"Recommendation: {thesis.recommendation}. "
        f"Price target: ${thesis.price_target:.2f} ({thesis.price_target_basis}). "
        f"Catalysts: {', '.join(thesis.catalysts[:2])}. "
        f"Risks: {', '.join(thesis.risks[:2])}."
    )
    return StepOutput(text=narrative, structured=thesis)


def _build_sensitivity_ranges(dcf_result: DCFResult) -> tuple[list[float], list[float]]:
    """Build WACC and terminal growth ranges for sensitivity analysis."""
    wacc = dcf_result.wacc
    tg = dcf_result.inputs.terminal_growth_rate

    wacc_range = [round(max(0.03, wacc - 0.02 + i * 0.01), 4) for i in range(5)]
    tg_candidates = [round(max(0.0, tg - 0.01 + i * 0.005), 4) for i in range(5)]

    min_wacc = min(wacc_range)
    tg_range = [g for g in tg_candidates if g < min_wacc]

    if len(tg_range) < 2:
        tg_range = [round(0.005 + i * 0.005, 4) for i in range(5) if 0.005 + i * 0.005 < min_wacc]

    return wacc_range, tg_range


def create_equity_research_pipeline(agents: dict[str, Agent]) -> Pipeline:
    """Factory function. Accepts dict of sub-agents."""
    return Pipeline(
        steps=[
            PipelineStep(
                name="data_collection",
                skill_section=None,
                agent=agents["data"],
                required_data=[DataType.FINANCIALS, DataType.PRICE, DataType.NEWS],
                validator=StructuredValidator(
                    validate_financial_data,
                    lambda out: validate_has_fields(out, ["revenue", "ebitda"]),
                ),
                executor=execute_financial_data_step,
            ),
            PipelineStep(
                name="catalyst_analysis",
                skill_section=None,
                agent=agents["data"],
                required_data=[],
                validator=StructuredValidator(
                    validate_catalyst_analysis,
                    validate_is_non_empty,
                ),
                executor=_execute_catalyst_analysis,
            ),
            PipelineStep(
                name="peer_analysis",
                skill_section="comps-analysis",
                agent=agents["analysis"],
                required_data=[],
                validator=StructuredValidator(
                    validate_peer_comps,
                    lambda out: validate_has_peers(out, min_peers=3),
                ),
                executor=_execute_peer_analysis,
            ),
            PipelineStep(
                name="financial_modeling",
                skill_section="dcf-model",
                agent=agents["modeling"],
                required_data=[],
                validator=StructuredValidator(validate_dcf_result, validate_is_non_empty),
                executor=_execute_financial_modeling,
            ),
            PipelineStep(
                name="thesis",
                skill_section="initiating-coverage",
                agent=agents["synthesis"],
                required_data=[],
                validator=StructuredValidator(
                    validate_thesis,
                    lambda out: validate_has_thesis(out),
                ),
                executor=_execute_thesis,
            ),
            PipelineStep(
                name="report",
                skill_section=None,
                agent=agents["report"],
                required_data=[],
                validator=TextValidator(validate_report_format),
            ),
        ]
    )
