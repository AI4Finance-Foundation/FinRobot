"""Shared execute_fn factories for pipeline steps that fetch + extract financial data."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from pydantic_ai import Agent

from finrobot.engine.compute.data_processor import (
    extract_historical_metrics,
    forecast_financials,
)
from finrobot.engine.compute.extractor import extract_financial_data
from finrobot.engine.compute.valuation_synthesis import synthesize_valuations
from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.types import DataType
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.models.financial import (
    DCFResult,
    FinancialData,
    ForecastResult,
    HistoricalMetrics,
    MarginAssumptions,
    PeerComps,
    StepOutput,
    ValuationMethod,
    ValuationSynthesis,
)

logger = logging.getLogger(__name__)


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
) -> ValuationSynthesis | None:
    """Build ValuationSynthesis from DCFResult + PeerComps in structured_context."""
    methods: list[ValuationMethod] = []

    dcf = structured_context.get("financial_modeling")
    if isinstance(dcf, DCFResult):
        # DCF method: ±20% range around implied price
        methods.append(
            ValuationMethod(
                name="DCF",
                low=dcf.implied_price * 0.8,
                mid=dcf.implied_price,
                high=dcf.implied_price * 1.2,
                confidence=0.7,
                source="Discounted Cash Flow model",
            )
        )

    peers = structured_context.get("peer_analysis")
    if isinstance(peers, PeerComps) and peers.median_ev_ebitda:
        # EV/EBITDA comps: apply peer median to target's EBITDA
        target = peers.target
        if target.ebitda > 0 and target.market_cap > 0:
            shares = target.market_cap / current_price if current_price > 0 else 1
            ev_from_peers = peers.median_ev_ebitda * target.ebitda
            equity_from_peers = ev_from_peers - (target.total_debt - target.total_cash)
            implied = equity_from_peers / shares if shares > 0 else 0
            if implied > 0:
                methods.append(
                    ValuationMethod(
                        name="EV/EBITDA Comps",
                        low=implied * 0.85,
                        mid=implied,
                        high=implied * 1.15,
                        confidence=0.5,
                        source=f"Peer median EV/EBITDA {peers.median_ev_ebitda:.1f}x",
                    )
                )

    if not methods:
        return None

    try:
        return synthesize_valuations(methods, current_price)
    except ValueError as e:
        logger.warning("Failed to build ValuationSynthesis: %s", e)
        return None
