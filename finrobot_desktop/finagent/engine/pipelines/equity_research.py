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
    HistoricalMetrics,
    PeerComps,
    PeerSelection,
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
from finagent.engine.compute.dcf_seed import seed_dcf_inputs
from finagent.engine.compute.historical_extractor import extract_historical_from_yfinance
from finagent.engine.analysis.news_classifier import classify_news
from finagent.engine.compute.news import fetch_news
from finagent.engine.pipelines.base import (
    Pipeline,
    PipelineStep,
    StructuredValidator,
    TextValidator,
)
from finagent.engine.pipelines._helpers import (
    build_sensitivity_ranges,
    execute_financial_data_step,
)
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

    # Fetch retail sentiment (optional — Adanos provider may not be registered)
    sentiment_snapshot: dict[str, Any] | None = None
    try:
        sentiment_result = await deps.data_layer.fetch(DataType.SENTIMENT, ticker)
        if sentiment_result.data and not sentiment_result.data.get("error"):
            sentiment_snapshot = sentiment_result.data
    except (ProviderError, ValueError, KeyError):
        logger.debug("Retail sentiment not available for %s", ticker)

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
    cat_labels = ", ".join(f"{cat}({cnt})" for cat, cnt in summary["category_breakdown"].items())
    narrative = (
        f"Catalyst analysis: {summary['total_catalysts']} events identified. "
        f"Net sentiment: {net:+.2f} ({overall}). "
        f"Categories: {cat_labels or 'none'}."
    )
    if top_pos:
        narrative += f" Top catalyst: {top_pos[0].headline}."

    if sentiment_snapshot and sentiment_snapshot.get("average_buzz") is not None:
        narrative += (
            f" Retail sentiment: buzz {sentiment_snapshot['average_buzz']}/100, "
            f"bullish {sentiment_snapshot.get('bullish_avg', 'N/A')}%, "
            f"{sentiment_snapshot['source_alignment'].lower()} "
            f"({sentiment_snapshot['coverage']})."
        )

    if sentiment_snapshot:
        structured_context["retail_sentiment"] = sentiment_snapshot

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
    agent: Agent[Any, Any],  # noqa: ARG001 — kept for executor signature; unused
    deps: FinAgentDeps,  # noqa: ARG001 — kept for executor signature; unused
    prompt: str,  # noqa: ARG001 — kept for executor signature; unused
    structured_context: dict[str, object],
    ticker: str,
) -> StepOutput:
    """Deterministic DCF: seed inputs from real filings, compute, sensitivity.

    DCFInputs is constructed exclusively via ``seed_dcf_inputs`` (CLAUDE.md
    architecture red-line #5). The LLM does not pick any numbers here — its
    role is reduced to narrating the seeded result downstream (the thesis +
    report steps). Every field traces to either the ticker's 3y historical
    median or a Damodaran industry median, with provenance recorded in
    DCFInputs.assumption_provenance for the UI's "展开专家详情" panel.

    Previously this step ran a ``param_agent`` (LLM) that produced DCFInputs
    from the prompt — that path is gone. Resurrecting it would walk back the
    P0 reconfiguration audited by ``tests/audit/test_dcf_red_lines.py``.
    """
    financial_data = structured_context.get("data_collection")
    if not isinstance(financial_data, FinancialData):
        raise ValueError(
            "financial_modeling requires FinancialData from the data_collection "
            "step but received: " + type(financial_data).__name__
        )

    # Prefer historical_metrics already built by execute_financial_data_step;
    # fall back to a fresh yfinance fetch when the pipeline ran in a mode that
    # skipped multi-year extraction.
    historical = structured_context.get("historical_metrics")
    if not isinstance(historical, HistoricalMetrics):
        try:
            historical = await extract_historical_from_yfinance(ticker)
        except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as exc:
            logger.warning(
                "Historical extraction failed for %s: %s — falling back to "
                "Damodaran industry medians via seed_dcf_inputs.",
                ticker,
                exc,
            )
            historical = HistoricalMetrics(
                years=[],
                revenue=[],
                revenue_growth_yoy=[],
                cogs=[],
                gross_profit=[],
                gross_margin=[],
                sga=[],
                sga_ratio=[],
                ebitda=[],
                ebitda_margin=[],
                operating_income=[],
                operating_margin=[],
                net_income=[],
                eps=[],
                pe_ratio=[],
                cagr_revenue=None,
                ticker=ticker,
            )

    dcf_inputs = seed_dcf_inputs(financial_data, historical)
    try:
        dcf_result = calculate_dcf(dcf_inputs)
    except (ValueError, ArithmeticError) as e:
        raise ValueError(f"DCF calculation failed with seeded parameters: {e}") from e
    wacc_range, tg_range = build_sensitivity_ranges(
        dcf_result.wacc, dcf_result.inputs.terminal_growth_rate
    )
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
    current_price = (
        financial_data.market.current_price if hasattr(financial_data, "market") else 0
    )
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


def create_equity_research_pipeline(agents: dict[str, Agent]) -> Pipeline:
    """Factory function. Accepts dict of sub-agents."""
    from finagent.artifact.builders import build_equity_research_artifact

    return Pipeline(
        artifact_builder=build_equity_research_artifact,
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
        ],
    )
