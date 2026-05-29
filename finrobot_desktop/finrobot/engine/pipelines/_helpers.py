"""Shared execute_fn factories for pipeline steps that fetch + extract financial data."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.exceptions import AgentRunError
from pydantic import ValidationError

from finrobot.engine.compute.data_processor import (
    extract_historical_metrics,
    forecast_financials,
)
from finrobot.engine.compute.extractor import extract_financial_data, extract_company_financials
from finrobot.engine.compute.fx_normalize import normalize_company_to_usd
from finrobot.engine.compute.multiples import calculate_multiples, calculate_peer_statistics
from finrobot.engine.compute.valuation_aggregator import aggregate_valuation
from finrobot.engine.compute.valuation_synthesis import synthesize_valuations
from finrobot.engine.compute.xbrl_aligned_comps import (
    build_xbrl_aligned_company,
    override_company_with_xbrl,
)
from finrobot.engine.data.interface import DataResult, ProviderError
from finrobot.engine.data.providers.fx import fetch_fx_rate_to_usd
from finrobot.engine.data.types import DataType
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.models.financial import (
    CompanyFinancials,
    DCFResult,
    DDMResult,
    FinancialData,
    ForecastResult,
    HistoricalMetrics,
    LBOResult,
    MarginAssumptions,
    PeerComps,
    PeerSelection,
    StepOutput,
    ValuationMethod,
    ValuationSynthesis,
)

logger = logging.getLogger(__name__)


async def normalize_peer_to_usd(company: CompanyFinancials) -> CompanyFinancials:
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


def _find_target_financial_data(structured_context: dict[str, object]) -> FinancialData | None:
    """Locate the target's FinancialData regardless of which step produced it.

    equity_research names the data step ``data_collection``; comps names it
    ``target_data``. Search by type so the shared peer-analysis executor works
    in both pipelines without hard-coding a step key.
    """
    direct = structured_context.get("data_collection")
    if isinstance(direct, FinancialData):
        return direct
    for value in structured_context.values():
        if isinstance(value, FinancialData):
            return value
    return None


async def execute_peer_analysis(
    agent: Agent[Any, Any],
    deps: FinRobotDeps,
    prompt: str,
    structured_context: dict[str, object],
    ticker: str,
) -> StepOutput:
    """LLM selects peer tickers (structured output); code fetches and computes
    multiples. Shared by equity_research and the standalone comps pipeline so
    BOTH produce deterministic, traceable multiples instead of LLM free text."""
    peer_agent = Agent(
        deps.settings.create_model(),
        output_type=PeerSelection,
        instructions=(
            "Select 3-5 comparable publicly traded companies for peer analysis. "
            "Choose companies in the same sector with similar business models and market cap. "
            "Return valid ticker symbols only (e.g. MSFT, GOOGL, not 'Microsoft').\n\n"
            "**Peer 选择硬约束**：\n"
            "所有 peer 必须与 target 的 yfinance industry 字段完全一致（不是 sector，是 industry）。\n"
            "例：AAPL industry='Consumer Electronics' → peer 必须也是 Consumer Electronics。\n"
            "不允许跨 industry 选 peer（即使同 sector）。\n"
            "如果合规 peer 不足 5 个，宁可 3-4 个也不要补凑跨 industry 的。"
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
            # USD market_cap) collapses EV/EBITDA to 0.158x. A failed FX lookup
            # falls through to the outer except and drops this peer; thinning
            # the set beats publishing a mixed-unit multiple.
            company = await normalize_peer_to_usd(company)
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

    target_fin = _find_target_financial_data(structured_context)
    if target_fin is None:
        raise ValueError("target FinancialData not available in context; cannot build peer target.")
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


async def execute_financial_data_step(
    agent: Agent[Any, Any],
    deps: FinRobotDeps,
    prompt: str,
    structured_context: dict[str, object],
    ticker: str,
) -> StepOutput:
    """Standard data-collection step: run agent + fetch financials/price + extract.

    Used by equity_research, dcf, lbo, comps pipelines.  Centralised here so
    changes to extraction logic propagate everywhere.

    Also builds HistoricalMetrics and ForecastResult from multi-year data
    and injects them into structured_context for chart generation.
    """
    step_result = await agent.run(prompt, deps=deps)
    financials_result = await deps.data_layer.fetch(DataType.FINANCIALS, ticker)
    price_result = await deps.data_layer.fetch(DataType.PRICE, ticker)
    financial_data = extract_financial_data(financials_result, price_result)
    # Merge cross-validation warnings from DataResult into FinancialData so
    # they reach PipelineResult and the final report.
    for w in financials_result.warnings:
        if w not in financial_data.warnings:
            financial_data.warnings.append(w)

    # Build multi-year historical metrics + forecast for chart generation.
    # These are deterministic — no LLM call needed.
    # structured_context IS structured_results (same dict reference) so
    # writes here persist into PipelineResult.structured_data.
    hm = await _build_historical_metrics(deps, ticker, financial_data)
    if hm is not None:
        structured_context["historical_metrics"] = hm
        logger.info(
            "HistoricalMetrics built for %s: %d years (%s)",
            ticker,
            len(hm.years),
            hm.years,
        )
        forecast = _build_forecast(hm)
        if forecast is not None:
            structured_context["forecast"] = forecast
            logger.info("ForecastResult built for %s: %d years", ticker, len(forecast.years))
    else:
        logger.info("HistoricalMetrics not available for %s — charts will be limited", ticker)

    logger.info(
        "structured_context keys after data_collection: %s",
        list(structured_context.keys()),
    )
    return StepOutput(text=step_result.output, structured=financial_data)


async def _build_historical_metrics(
    deps: FinRobotDeps, ticker: str, current_fd: FinancialData
) -> HistoricalMetrics | None:
    """Fetch multi-year data and build HistoricalMetrics. Returns None on failure."""
    try:
        if not hasattr(deps.data_layer, "fetch_historical"):
            return None
        yearly_results = await deps.data_layer.fetch_historical(
            DataType.FINANCIALS, ticker, years=5
        )
        if len(yearly_results) < 2:
            logger.info(
                "Only %d year(s) of data for %s — skipping HistoricalMetrics",
                len(yearly_results),
                ticker,
            )
            return None

        # Convert each yearly DataResult to FinancialData
        # Use a dummy price result (historical price not critical for metrics)
        dummy_price = DataResult(
            data={"price_history": [{"close": current_fd.market.current_price}]},
            provider="derived",
            ticker=ticker,
            data_type="price",
            timestamp=datetime.now(tz=timezone.utc),
        )
        fd_list: list[FinancialData] = []
        for yr in yearly_results:
            try:
                fd = extract_financial_data(yr, dummy_price)
                fd_list.append(fd)
            except (ValueError, KeyError) as e:
                logger.debug("Skipping year for %s: %s", ticker, e)
                continue

        if len(fd_list) < 2:
            return None

        return extract_historical_metrics(fd_list)
    except (ValueError, KeyError, TypeError, RuntimeError) as e:
        logger.warning("Failed to build HistoricalMetrics for %s: %s", ticker, e)
        return None


def _build_forecast(hm: HistoricalMetrics) -> ForecastResult | None:
    """Build 3-year forecast from historical metrics with reasonable defaults."""
    try:
        # Use historical revenue growth trend, clamped to reasonable range
        growth_rates = []
        valid_growths = [g for g in hm.revenue_growth_yoy if g is not None]
        if valid_growths:
            avg_growth = sum(valid_growths) / len(valid_growths)
            # Clamp to [-10%, +30%] and fade toward long-term average
            base = max(-0.10, min(0.30, avg_growth))
            growth_rates = [base, base * 0.9, base * 0.8]  # fade down
        else:
            growth_rates = [0.05, 0.04, 0.03]  # conservative defaults

        return forecast_financials(
            historical=hm,
            revenue_growth_assumptions=growth_rates,
            margin_assumptions=MarginAssumptions(),  # use historical averages
        )
    except (ValueError, ZeroDivisionError, TypeError) as e:
        logger.warning("Failed to build ForecastResult: %s", e)
        return None


def build_sensitivity_ranges(
    discount_rate: float, terminal_growth: float
) -> tuple[list[float], list[float]]:
    """Build (discount-rate, terminal-growth) sweep ranges for sensitivity tables.

    Used by DCF (discount_rate=WACC) and DDM (discount_rate=cost of equity).
    Both apply a ±2% sweep around discount_rate paired with terminal-growth
    candidates filtered to stay strictly below min(discount_rate_range), so
    every cell in the resulting grid is a valid Gordon-growth denominator.
    """
    rate_range = [round(max(0.03, discount_rate - 0.02 + i * 0.01), 4) for i in range(5)]
    tg_candidates = [round(max(0.0, terminal_growth - 0.01 + i * 0.005), 4) for i in range(5)]

    min_rate = min(rate_range)
    tg_range = [g for g in tg_candidates if g < min_rate]

    if len(tg_range) < 2:
        tg_range = [round(0.005 + i * 0.005, 4) for i in range(5) if 0.005 + i * 0.005 < min_rate]

    return rate_range, tg_range


def build_valuation_synthesis(
    structured_context: dict[str, object],
    current_price: float,
    ticker: str,
) -> ValuationSynthesis | None:
    """Build ValuationSynthesis from pipeline structured_context via aggregate_valuation.

    Replaces the old 2-method (DCF + EV/EBITDA) hand-rolled logic with the
    canonical 6-method ``aggregate_valuation`` function used by the REST endpoint.
    Adapts ``ValuationAggregate`` → ``ValuationSynthesis`` so the thesis step
    contract (``ValuationSynthesis``) stays intact.

    When only one method resolves, ``weighted_price`` will be None and the
    thesis step will NOT inject an authoritative price target — the LLM narrates
    without a forced number rather than surfacing a spurious single-method "average".
    """
    dcf = structured_context.get("financial_modeling")
    peers = structured_context.get("peer_analysis")
    ddm = structured_context.get("ddm_calc")
    lbo = structured_context.get("lbo_calc")

    financial_data = structured_context.get("data_collection")
    shares: float | None = None
    if isinstance(financial_data, FinancialData):
        shares = financial_data.market.shares_outstanding
    # Fall back to DCFInputs.shares_outstanding when FinancialData is absent.
    # DCF seed always carries this value from the data-collection step, so this
    # keeps comps_pe functional in the common case where dcf resolved but
    # data_collection is not re-stored in the same dict slice.
    if shares is None and isinstance(dcf, DCFResult):
        shares = dcf.inputs.shares_outstanding

    agg = aggregate_valuation(
        ticker=ticker,
        current_price=current_price,
        dcf=dcf if isinstance(dcf, DCFResult) else None,
        peer_comps=peers if isinstance(peers, PeerComps) else None,
        ddm=ddm if isinstance(ddm, DDMResult) else None,
        lbo=lbo if isinstance(lbo, LBOResult) else None,
        shares_outstanding=shares,
    )

    if not agg.methods:
        return None

    for w in agg.warnings:
        logger.debug("valuation_synthesis: %s", w)

    # Convert ValuationMethodRange → ValuationMethod for the thesis contract.
    vm_list: list[ValuationMethod] = [
        ValuationMethod(
            name=r.method,
            low=r.low,
            mid=r.mid,
            high=r.high,
            confidence=r.confidence,
            source=r.source,
        )
        for r in agg.methods
    ]

    try:
        return synthesize_valuations(vm_list, current_price)
    except ValueError as e:
        logger.warning("Failed to build ValuationSynthesis: %s", e)
        return None
