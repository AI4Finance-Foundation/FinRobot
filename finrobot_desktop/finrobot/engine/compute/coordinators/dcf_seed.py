"""Coordinator: fetch a ticker's financials + price + history → seed DCFInputs.

The single fetch-and-seed path shared by the REST compute endpoints
(routes/compute.py) and the chat orchestrator's ``run_monte_carlo`` tool. It
lives in the engine (not routes/) so the orchestrator can reuse it without an
engine→routes upward import. Consumes ``DataLayer`` (coordinator tier,
ADR-0005) and takes ``data_layer`` + ``fmp_api_key`` as parameters rather than
the request ``FinRobotDeps`` so it stays a leaf-respecting compute module.
"""

from __future__ import annotations

import logging

from finrobot.engine.compute.coordinators.extractor import (
    extract_financial_data,
    normalize_financials_to_usd,
)
from finrobot.engine.compute.coordinators.historical_extractor import fetch_historical_metrics
from finrobot.engine.compute.operators.dcf_seed import seed_dcf_inputs
from finrobot.engine.compute.operators.forward_estimates import get_forward_revenue_growth
from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.data.types import DataType
from finrobot.engine.models.financial import DCFInputs, FinancialData, HistoricalMetrics
from finrobot.engine.primitives.industry import is_commodity_cyclical

logger = logging.getLogger(__name__)


async def fetch_forward_growth(data_layer: DataLayer, ticker: str) -> list[float]:
    """Analyst-consensus YoY revenue-growth path for the DCF explicit-window seed.

    Best-effort fetch of the canonical FORWARD_ESTIMATES snapshot, run through
    the single authoritative producer ``get_forward_revenue_growth``. Returns
    ``[]`` on any miss so the seed falls back to trailing CAGR — a forward gap
    must never fail the seed. Shared by every *fetch-path* seed entry (REST
    ``/dcf-seed`` + chat Monte-Carlo via ``seed_dcf_inputs_for_ticker``, and the
    IC-memo pipeline) so one ticker can't get a consensus seed on one surface and
    a trailing-CAGR seed on another — the single-authoritative-seed contract the
    report path already honours via the same producer. ``fetch_canonical`` (not
    raw ``fetch()``) is what makes the source HARD-single: all entries share one
    versioned cache slot, one in-flight fetch and one failure semantic, so a
    transient provider flake can't hand consensus to one surface and trailing
    CAGR to another within the TTL.
    """
    try:
        _fwd = await data_layer.fetch_canonical(DataType.FORWARD_ESTIMATES, ticker)
    except (ProviderError, ValueError, KeyError, TypeError) as exc:
        logger.debug("forward estimates unavailable for %s: %s", ticker, exc)
        return []
    return get_forward_revenue_growth(_fwd.payload())


async def seed_dcf_inputs_for_ticker(
    data_layer: DataLayer, ticker: str, *, fmp_api_key: str | None = None
) -> tuple[FinancialData, DCFInputs]:
    """Fetch financials + price + multi-year history for a ticker and seed a
    DCFInputs.

    Seeds the explicit-window growth from analyst consensus (``fetch_forward_growth``)
    when available — the same authoritative path the equity-research report uses —
    so REST ``/dcf-seed`` and the chat Monte-Carlo tool can't print a different DCF
    than the report for the same ticker. A forward miss → ``[]`` → trailing-CAGR seed.

    Degrades gracefully: if historical extraction fails (yfinance / provider
    variability), seeds from an empty HistoricalMetrics so seed_dcf_inputs falls
    through to Damodaran industry medians rather than raising.
    """
    _fin = await data_layer.fetch_canonical(DataType.FINANCIALS, ticker)
    _price = await data_layer.fetch_canonical(DataType.PRICE, ticker)
    financial_data = extract_financial_data(_fin, _price)

    # FX-normalize a foreign issuer's financials to canonical USD before seeding so
    # the implied price comes out in USD (not a ~32x-inflated TWD-per-share) and the
    # WACC debt-weight isn't cross-currency garbage (BUG-073). No-op for US issuers.
    financial_data = await normalize_financials_to_usd(financial_data, fmp_api_key=fmp_api_key)

    try:
        historical = await fetch_historical_metrics(data_layer, ticker)
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as exc:
        logger.warning("Historical extraction failed for %s: %s", ticker, exc)
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

    forward_growth = await fetch_forward_growth(data_layer, ticker)
    # Commodity-cyclical → through-cycle earnings normalization in the seed. The
    # ticker anchor covers memory/storage even when the provider industry tag is
    # the generic "Semiconductors" (which it is for MU); industry/sector cover the
    # rest (steel/oil/shipping). Same gate the historical window-extension uses.
    cyclical = is_commodity_cyclical(
        industry=financial_data.market.industry,
        sector=financial_data.market.sector,
        ticker=ticker,
    )
    return financial_data, seed_dcf_inputs(
        financial_data, historical, forward_growth=forward_growth, cyclical=cyclical
    )
