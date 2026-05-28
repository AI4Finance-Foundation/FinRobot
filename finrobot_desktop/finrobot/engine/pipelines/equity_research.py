from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.exceptions import AgentRunError

from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.types import DataType
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.models.financial import (
    CatalystAnalysis,
    CatalystEvent,
    DCFResult,
    FinancialData,
    CompanyFinancials,
    HistoricalMetrics,
    PeerComps,
    PeerSelection,
    ThesisResult,
    StepOutput,
    ValuationSynthesis,
)
from finrobot.engine.compute.catalyst import (
    extract_catalysts_from_news,
    compute_expected_impact,
    summarize_catalyst_outlook,
)
from finrobot.engine.compute.extractor import extract_company_financials
from finrobot.engine.compute.fx_normalize import normalize_company_to_usd
from finrobot.engine.compute.multiples import calculate_multiples, calculate_peer_statistics
from finrobot.engine.data.providers.fx import fetch_fx_rate_to_usd
from finrobot.engine.compute.dcf import calculate_dcf, calculate_sensitivity
from finrobot.engine.compute.dcf_seed import seed_dcf_inputs
from finrobot.engine.compute.historical_extractor import extract_historical_from_yfinance
from finrobot.engine.compute.ownership import compute_ownership_governance
from finrobot.engine.compute.technical_payload import build_technical_analysis
from finrobot.engine.compute.xbrl_aligned_comps import (
    build_xbrl_aligned_company,
    override_company_with_xbrl,
    xbrl_concept_snapshot,
)
from finrobot.engine.analysis.news_classifier import classify_news
from finrobot.engine.compute.news import fetch_news
from finrobot.engine.pipelines.base import (
    Pipeline,
    PipelineStep,
    StructuredValidator,
    TextValidator,
)
from finrobot.engine.pipelines._helpers import (
    build_sensitivity_ranges,
    execute_financial_data_step,
)
from finrobot.engine.pipelines.validators import (
    validate_catalyst_analysis,
    validate_has_fields,
    validate_has_peers,
    validate_has_thesis,
    validate_report_format,
    validate_is_non_empty,
    validate_financial_data,
    validate_ownership_governance,
    validate_peer_comps,
    validate_dcf_result,
    validate_technical_analysis,
    validate_thesis,
)

logger = logging.getLogger(__name__)


async def _normalize_peer_to_usd(company: CompanyFinancials) -> CompanyFinancials:
    """Convert a peer's IS/BS items (and market_cap if quoted in non-USD) to
    canonical USD using today's spot FX. No-op fast path when both currency
    tags are already USD — the common case for US peers."""
    if company.reporting_currency == "USD" and company.quote_currency == "USD":
        return company
    reporting_rate = (
        1.0
        if company.reporting_currency == "USD"
        else await fetch_fx_rate_to_usd(company.reporting_currency)
    )
    if company.quote_currency == "USD":
        quote_rate = 1.0
    elif company.quote_currency == company.reporting_currency:
        # Local listing (e.g. 2330.TW): both tags equal, reuse the rate.
        quote_rate = reporting_rate
    else:
        quote_rate = await fetch_fx_rate_to_usd(company.quote_currency)
    return normalize_company_to_usd(company, reporting_rate, quote_rate)


async def _fetch_optional_sec(
    deps: FinRobotDeps,
    ticker: str,
    data_type: DataType,
    **kwargs: Any,
) -> dict[str, Any]:
    result = await deps.data_layer.fetch(data_type, ticker, **kwargs)
    if result.data.get("error"):
        return {"available": False, "error": result.data["error"], "warnings": result.warnings}
    return {**result.data, "warnings": result.warnings, "provider": result.provider}


async def _execute_data_collection_with_sec(
    agent: Agent[Any, Any],
    deps: FinRobotDeps,
    prompt: str,
    structured_context: dict[str, object],
    ticker: str,
) -> StepOutput:
    """Collect standard financials plus SEC filing/XBRL context."""
    financial_output = await execute_financial_data_step(
        agent,
        deps,
        prompt,
        structured_context,
        ticker,
    )

    tenk_task = _fetch_optional_sec(deps, ticker, DataType.FILINGS_10K)
    tenq_task = _fetch_optional_sec(deps, ticker, DataType.FILINGS_10Q, n=4)
    eightk_task = _fetch_optional_sec(deps, ticker, DataType.FILINGS_8K, n=10)
    xbrl_task = _fetch_optional_sec(deps, ticker, DataType.XBRL_FACTS)
    tenk, tenq, eightk, xbrl = await asyncio.gather(
        tenk_task,
        tenq_task,
        eightk_task,
        xbrl_task,
    )

    structured_context["sec_filings"] = {
        "10k": tenk,
        "10q_history": tenq.get("quarterly_filings", []),
        "8k_events": eightk.get("events", []),
    }
    structured_context["xbrl_facts_raw"] = xbrl
    structured_context["xbrl_facts_snapshot"] = xbrl_concept_snapshot(xbrl)

    sec_warnings = [
        warning
        for payload in (tenk, tenq, eightk, xbrl)
        for warning in payload.get("warnings", [])
    ]
    if isinstance(financial_output.structured, FinancialData):
        for warning in sec_warnings:
            if warning not in financial_output.structured.warnings:
                financial_output.structured.warnings.append(warning)

    return financial_output


def _sec_8k_to_catalyst(event: dict[str, Any]) -> CatalystEvent:
    items = [str(i) for i in event.get("items", [])]
    item_text = ", ".join(items) if items else "8-K"
    category: Literal[
        "product_launch",
        "earnings",
        "regulatory",
        "acquisition",
        "management",
        "market",
    ] = "regulatory"
    if any(i.startswith("Item 2.02") for i in items):
        category = "earnings"
    elif any(i.startswith("Item 5.02") for i in items):
        category = "management"
    elif any(i.startswith("Item 1.01") or i.startswith("Item 2.01") for i in items):
        category = "acquisition"

    # Inject filing date and SEC URL for traceability
    raw_date = event.get("filing_date") or event.get("filed_at")
    published: datetime | None = None
    if raw_date:
        try:
            dt = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
            published = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            published = None

    source_url: str | None = event.get("source_url") or None
    if source_url is None:
        accession_no = event.get("accession_no")
        if accession_no:
            source_url = (
                f"https://www.sec.gov/cgi-bin/browse-edgar"
                f"?action=getcompany&accession-number={accession_no}"
            )

    return CatalystEvent(
        category=category,
        headline=f"SEC 8-K filed: {item_text}",
        sentiment="neutral",
        impact_score=3,
        probability=1.0,
        reasoning=(
            "Source is a company-filed SEC 8-K current report; treated as "
            "primary-source catalyst context."
        ),
        published=published,
        url=source_url,
    )


async def _execute_catalyst_analysis(
    agent: Agent[Any, Any],
    deps: FinRobotDeps,
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

    # Drop stale news (> 30 days old) before catalyst extraction
    now_utc = datetime.now(tz=timezone.utc)
    fresh_news = [
        n for n in news_items
        if (now_utc - n.published.replace(tzinfo=timezone.utc) if n.published.tzinfo is None else now_utc - n.published).days <= 30
    ]
    stale_count = len(news_items) - len(fresh_news)
    if stale_count > 0:
        logger.debug("Dropped %d stale news items (>30 days) for %s", stale_count, ticker)

    # Extract catalysts from high-importance news
    catalysts = extract_catalysts_from_news(fresh_news)
    sec_filings = structured_context.get("sec_filings")
    if isinstance(sec_filings, dict):
        for event in sec_filings.get("8k_events", [])[:10]:
            if isinstance(event, dict):
                catalysts.append(_sec_8k_to_catalyst(event))
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
    deps: FinRobotDeps,
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
            # Normalize foreign-listed ADRs / local listings to canonical USD
            # BEFORE multiples are computed — otherwise TSM (TWD financials,
            # USD market_cap) collapses EV/EBITDA to 0.158x. ProviderError
            # from a failed FX lookup falls through to the outer except and
            # drops this peer from the comp set; that is the desired
            # behavior — better to thin the peer set than to publish a
            # multiple computed in mixed units.
            company = await _normalize_peer_to_usd(company)
            company = calculate_multiples(company)
            xbrl_result = await deps.data_layer.fetch(DataType.XBRL_FACTS, peer_ticker)
            return override_company_with_xbrl(company, xbrl_result.data)
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
    raw_target_xbrl = structured_context.get("xbrl_facts_raw")
    target_xbrl = raw_target_xbrl if isinstance(raw_target_xbrl, dict) else None
    target = build_xbrl_aligned_company(
        ticker=ticker,
        financial_data=target_fin,
        xbrl_data=target_xbrl,
    )

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


async def _execute_ownership_governance_analysis(
    agent: Agent[Any, Any],  # noqa: ARG001
    deps: FinRobotDeps,
    prompt: str,  # noqa: ARG001
    structured_context: dict[str, object],
    ticker: str,
) -> StepOutput:
    insider_task = _fetch_optional_sec(deps, ticker, DataType.INSIDER_TRADES, days=90)
    holdings_task = _fetch_optional_sec(deps, ticker, DataType.INSTITUTIONAL_HOLDINGS)
    proxy_task = _fetch_optional_sec(deps, ticker, DataType.PROXY_STATEMENT)
    insider, holdings, proxy = await asyncio.gather(insider_task, holdings_task, proxy_task)

    analysis = compute_ownership_governance(
        insider_data=insider,
        institutional_data=holdings,
        proxy_data=proxy,
    )

    # Populate degraded_reasons based on what _fetch_optional_sec returned.
    # "available": False means the provider returned an error payload.
    # Empty list/None after a successful fetch means no recent filings exist.
    if "insider_transactions" in analysis.degraded_sections:
        if insider.get("available") is False:
            error_str = str(insider.get("error", "")).lower()
            if "identity" in error_str or "cik" in error_str or "not found" in error_str:
                analysis.degraded_reasons["insider_transactions"] = "identity_missing"
            else:
                analysis.degraded_reasons["insider_transactions"] = "fetch_error"
        else:
            analysis.degraded_reasons["insider_transactions"] = "no_recent_filings"

    if "proxy_compensation" in analysis.degraded_sections:
        if proxy.get("available") is False:
            analysis.degraded_reasons["proxy_compensation"] = "fetch_error"
        else:
            # Either no filing returned or fields parsed to None (garbage in).
            analysis.degraded_reasons["proxy_compensation"] = "parse_failed"

    narrative = (
        f"Ownership & Governance: {len(analysis.insider_transactions)} insider "
        f"transactions, {len(analysis.institutional_holdings)} institutional holders, "
        f"proxy compensation {'available' if analysis.proxy_compensation else 'unavailable'}."
    )
    if analysis.degraded_sections:
        narrative += f" Degraded sections: {', '.join(analysis.degraded_sections)}."
    return StepOutput(text=narrative, structured=analysis)


async def _execute_financial_modeling(
    agent: Agent[Any, Any],  # noqa: ARG001 — kept for executor signature; unused
    deps: FinRobotDeps,  # noqa: ARG001 — kept for executor signature; unused
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

    # Bug A fix: write DCFResult into structured_context BEFORE calling
    # build_valuation_synthesis so aggregate_valuation can find it. Previously
    # this write happened via _store_output AFTER the executor returned, so
    # isinstance(dcf, DCFResult) was always False and DCF was silently dropped.
    structured_context["financial_modeling"] = dcf_result

    # Build ValuationSynthesis from all available methods for the football field chart.
    current_price = (
        financial_data.market.current_price if hasattr(financial_data, "market") else 0
    )
    if current_price > 0:
        from finrobot.engine.pipelines._helpers import build_valuation_synthesis

        vs = build_valuation_synthesis(structured_context, current_price, ticker=ticker)
        if vs is not None:
            structured_context["valuation_synthesis"] = vs

    return StepOutput(text=narrative, structured=dcf_result)


async def _execute_technical_analysis(
    agent: Agent[Any, Any],  # noqa: ARG001 — kept for executor signature; unused
    deps: FinRobotDeps,
    prompt: str,  # noqa: ARG001 — kept for executor signature; unused
    structured_context: dict[str, object],
    ticker: str,
) -> StepOutput:
    """Run Monte Carlo + Sniper + Historical Bands → chapter 09 payload.

    Deterministic: every number traces back to seeded DCF inputs and the
    data layer's price/financials cache. The LLM contributes nothing here —
    it would only narrate downstream if the thesis step chose to.
    """
    dcf = structured_context.get("financial_modeling")
    financial_data = structured_context.get("data_collection")
    if not isinstance(dcf, DCFResult):
        raise ValueError(
            "technical_analysis requires DCFResult from financial_modeling step "
            "but received: " + type(dcf).__name__
        )
    if not isinstance(financial_data, FinancialData):
        raise ValueError(
            "technical_analysis requires FinancialData from data_collection step "
            "but received: " + type(financial_data).__name__
        )

    current_price = (
        financial_data.market.current_price if hasattr(financial_data, "market") else 0.0
    )

    payload = await build_technical_analysis(
        ticker=ticker,
        dcf_inputs=dcf.inputs,
        dcf_target=dcf.implied_price,
        current_price=current_price,
        data_layer=deps.data_layer,
    )

    summary_parts: list[str] = []
    if payload.monte_carlo is not None:
        mc = payload.monte_carlo
        summary_parts.append(
            f"Monte Carlo ({mc.n_valid:,} sims): mean ${mc.mean:.2f}, "
            f"P5–P95 ${mc.percentiles['5']:.2f}–${mc.percentiles['95']:.2f}, "
            f"current at {mc.current_price_percentile:.0f}th pct."
        )
    if payload.sniper is not None:
        sn = payload.sniper
        summary_parts.append(
            f"Sniper levels: buy ${sn.ideal_buy:.2f}, stop ${sn.stop_loss:.2f}, "
            f"target ${sn.take_profit:.2f} (R/R {sn.risk_reward_ratio:.1f})."
        )
    if payload.historical_bands is not None:
        hb = payload.historical_bands
        cur = f"{hb.current:.1f}x" if hb.current is not None else "n/a"
        med = f"{hb.median:.1f}x" if hb.median is not None else "n/a"
        summary_parts.append(
            f"EV/EBITDA band ({hb.sample_count} pts): current {cur} vs median {med} "
            f"→ {hb.classification}."
        )
    if not summary_parts:
        summary_parts.append("Technical analysis skipped — all branches unavailable.")

    return StepOutput(text=" ".join(summary_parts), structured=payload)


# Recommendation thresholds — applied to ValuationSynthesis.upside_downside.
# Source: sell-side equity-research convention (±15% bands around fair value
# are the standard separators between Buy / Hold / Sell on the Street). The
# numbers travel into both the LLM prompt (so the narrative is consistent)
# and the post-run override (so the contract holds even if the LLM drifts).
_VERDICT_BUY_THRESHOLD = 0.15
_VERDICT_SELL_THRESHOLD = -0.15


def _verdict_from_upside(upside: float) -> str:
    """Deterministic Buy/Hold/Sell from synthesis upside vs current price."""
    if upside >= _VERDICT_BUY_THRESHOLD:
        return "BUY"
    if upside <= _VERDICT_SELL_THRESHOLD:
        return "SELL"
    return "HOLD"


async def _execute_thesis(
    agent: Agent[Any, Any],
    deps: FinRobotDeps,
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

    # CLAUDE.md core contract: "LLM 永远不产出无法追溯到函数调用的数字".
    # The target price MUST trace to ``synthesize_valuations`` (deterministic
    # confidence-weighted average across DCF / Comps / …). Before this fix
    # the LLM picked the number freely — two consecutive 6-minute-apart TSLA
    # runs returned $25.37 vs $57.96 because the model sometimes anchored on
    # DCF, sometimes on Comps median, never on the actual weighted price.
    # ``recommendation`` (Buy/Hold/Sell) had the identical asymmetry — fixed
    # by classifying off ``upside_downside`` with documented thresholds.
    # We now (a) inject canonical values into the prompt so the narrative
    # is consistent and (b) force-override the fields after the run so even
    # a non-cooperative LLM can't desync the contract.
    vs = structured_context.get("valuation_synthesis")
    canonical_target: float | None = None
    canonical_basis: str | None = None
    canonical_verdict: str | None = None
    canonical_upside: float | None = None
    if isinstance(vs, ValuationSynthesis) and vs.weighted_price is not None:
        # Only inject an authoritative target when ≥2 methods converge.
        # Single-method synthesis has weighted_price=None (no cross-check).
        canonical_target = round(vs.weighted_price, 2)
        canonical_upside = vs.upside_downside
        canonical_verdict = (
            _verdict_from_upside(canonical_upside) if canonical_upside is not None else None
        )
        method_breakdown = ", ".join(
            f"{m.name}=${m.mid:.2f}(c={m.confidence:.2f})" for m in vs.methods
        )
        canonical_basis = (
            f"Confidence-weighted mean of {len(vs.methods)} methods: "
            f"{method_breakdown} → ${canonical_target:.2f}"
        )
    elif isinstance(vs, ValuationSynthesis):
        logger.warning(
            "ValuationSynthesis has only %d method(s) — no authoritative price target injected "
            "(single-method synthesis, no cross-check available)",
            len(vs.methods),
        )

    thesis_prompt = prompt
    if catalyst_section:
        thesis_prompt = f"{prompt}\n\nCatalyst Analysis:\n{catalyst_section}"
    if canonical_target is not None:
        upside_str = (
            f"{canonical_upside:+.1%}" if canonical_upside is not None else "n/a"
        )
        thesis_prompt = (
            f"{thesis_prompt}\n\n"
            f"AUTHORITATIVE PRICE TARGET (do not deviate): "
            f"${canonical_target:.2f}\n"
            f"AUTHORITATIVE RECOMMENDATION (do not deviate): "
            f"{canonical_verdict}\n"
            f"Derivation: {canonical_basis}; implied upside vs current price = {upside_str}.\n"
            f"Your `price_target` field MUST equal the authoritative number above. "
            f"Your `recommendation` field MUST equal the authoritative verdict above "
            f"(derived from upside thresholds: BUY ≥ +{int(_VERDICT_BUY_THRESHOLD * 100)}%, "
            f"SELL ≤ {int(_VERDICT_SELL_THRESHOLD * 100)}%, else HOLD). "
            f"Your `price_target_basis` MUST cite that this is the confidence-weighted "
            f"synthesis of the listed methods. Your narrative is free to discuss why each "
            f"method points where it does and why the verdict is consistent with the upside."
        )

    synthesis_agent = Agent(
        deps.settings.create_model(),
        output_type=ThesisResult,
        instructions=(
            "Write an investment thesis based on the DCF valuation, peer analysis, "
            "and catalyst analysis. "
            "Reference specific catalysts from the catalyst analysis when discussing "
            "upside drivers and risks. "
            "Provide a recommendation (Buy/Hold/Sell), price target, catalysts, and risks. "
            "When the prompt supplies an AUTHORITATIVE PRICE TARGET, copy it exactly into "
            "the `price_target` field — that number is computed by deterministic code and "
            "is the contract you are narrating, not negotiating."
            "\n\n"
            "ALSO produce the following analyst-grade narrative fields "
            "(investment-bank tone, no retail simplification; 中文 unless "
            "the surrounding context is in English):\n"
            "  - tagline:           a single sentence ≤ 60 characters that captures the "
            "trade thesis in one line; works as a share-card subtitle.\n"
            "  - key_takeaways:     3-5 bullet points the analyst reader should walk away "
            "with. NOT future events (those are `catalysts`) and NOT downsides (those are "
            "`risks`) — present-tense conclusions about why this is a Buy/Hold/Sell now.\n"
            "  - company_overview:  200-300 字 Company Overview (第 8 synthesis slot). "
            "Cover (a) the core business model and what the firm sells, (b) the reportable "
            "segments with revenue mix percentages and YoY growth, (c) geographic exposure "
            "split, and (d) the durable competitive moat. Investment-bank tone — write as "
            "if introducing the issuer in an initiating-coverage report.\n"
            "  - valuation_overview: 150-200 字解读 — why DCF vs Comps vs DDM give the "
            "implied prices they do, and how the weighted target was reached.\n"
            "  - competitor_analysis: 3-4 句话讲清楚 vs 同业的市占 / 增速 / 估值倍数差异。\n"
            "  - news_summary:      3-5 句话总结近 30 天关键新闻的整体情绪与对论点的支撑/挑战。"
        ),
        defer_model_check=True,
    )
    try:
        result = await synthesis_agent.run(thesis_prompt, deps=deps)  # type: ignore[call-overload]
        thesis = result.output
    except (AgentRunError, ValidationError, ValueError) as e:
        raise ValueError(f"LLM failed to produce valid thesis: {e}") from e

    # Hard-enforce the deterministic target + verdict — same inputs always
    # produce the same numbers. If the LLM ignored the prompt, log the
    # drift so we can detect prompt-fidelity regressions in evals.
    if canonical_target is not None and canonical_basis is not None:
        if abs(thesis.price_target - canonical_target) > 0.01:
            logger.warning(
                "Thesis LLM price_target drift: llm=%s, canonical=%s — overriding",
                thesis.price_target,
                canonical_target,
            )
        if (
            canonical_verdict is not None
            and thesis.recommendation.strip().upper() != canonical_verdict
        ):
            logger.warning(
                "Thesis LLM recommendation drift: llm=%s, canonical=%s — overriding",
                thesis.recommendation,
                canonical_verdict,
            )
        updates: dict[str, Any] = {
            "price_target": canonical_target,
            "price_target_basis": canonical_basis,
        }
        if canonical_verdict is not None:
            updates["recommendation"] = canonical_verdict
        thesis = thesis.model_copy(update=updates)

    narrative = (
        f"Recommendation: {thesis.recommendation}. "
        f"Price target: ${thesis.price_target:.2f} ({thesis.price_target_basis}). "
        f"Catalysts: {', '.join(thesis.catalysts[:2])}. "
        f"Risks: {', '.join(thesis.risks[:2])}."
    )
    return StepOutput(text=narrative, structured=thesis)


def create_equity_research_pipeline(agents: dict[str, Agent]) -> Pipeline:
    """Factory function. Accepts dict of sub-agents."""
    from finrobot.artifact.builders import build_equity_research_artifact

    return Pipeline(
        artifact_builder=build_equity_research_artifact,
        steps=[
            PipelineStep(
                name="data_collection",
                skill_section=None,
                agent=agents["data"],
                required_data=[
                    DataType.FINANCIALS,
                    DataType.PRICE,
                    DataType.NEWS,
                    DataType.FILINGS_10K,
                    DataType.FILINGS_10Q,
                    DataType.FILINGS_8K,
                    DataType.XBRL_FACTS,
                ],
                validator=StructuredValidator(
                    validate_financial_data,
                    lambda out: validate_has_fields(out, ["revenue", "ebitda"]),
                ),
                executor=_execute_data_collection_with_sec,
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
                name="ownership_governance_analysis",
                skill_section=None,
                agent=agents["analysis"],
                required_data=[],
                validator=StructuredValidator(
                    validate_ownership_governance,
                    validate_is_non_empty,
                ),
                executor=_execute_ownership_governance_analysis,
            ),
            PipelineStep(
                name="technical_analysis",
                skill_section=None,
                agent=agents["modeling"],
                required_data=[],
                validator=StructuredValidator(
                    validate_technical_analysis,
                    validate_is_non_empty,
                ),
                executor=_execute_technical_analysis,
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
