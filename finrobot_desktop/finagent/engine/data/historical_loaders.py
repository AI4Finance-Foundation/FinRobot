"""Shared IO loaders for historical-band computation.

Both the valuation route (GET /api/valuation/historical-bands/{ticker}) and
the equity-research pipeline's technical-analysis step need the same
fetch-yearly-financials + fetch-price-history + classify-band glue. Lives
here so neither layer has to import from the other.

The compute leaf (engine.compute.historical_valuation.compute_historical_band)
stays provider-agnostic; this module owns the data-layer translation.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Literal

from finagent.engine.compute.historical_valuation import (
    HistoricalBand,
    HistoricalMetricName,
    PricePoint,
    YearlyFinancials,
    compute_historical_band,
)
from finagent.engine.data.interface import ProviderError
from finagent.engine.data.layer import DataLayer
from finagent.engine.data.types import DataType

logger = logging.getLogger(__name__)


BandClassification = Literal["expensive", "fair", "cheap", "unknown"]


async def load_yearly_financials(
    ticker: str, data_layer: DataLayer, years: int
) -> list[tuple[YearlyFinancials, float | None]]:
    """Return (yearly snapshot, shares-or-None) tuples for the last N years.

    Returns an empty list when the data layer does not implement
    ``fetch_historical`` (e.g. lightweight fakes in tests), so that callers
    degrade gracefully instead of raising AttributeError.
    """
    if not hasattr(data_layer, "fetch_historical"):
        return []
    try:
        results = await data_layer.fetch_historical(DataType.FINANCIALS, ticker, years=years)
    except (ProviderError, ValueError, KeyError) as exc:
        logger.info("yearly financials fetch failed for %s: %s", ticker, exc)
        return []

    out: list[tuple[YearlyFinancials, float | None]] = []
    for result in results:
        data = result.data if isinstance(result.data, dict) else {}
        fiscal_raw = data.get("fiscal_year") or data.get("date")
        fy_date = _parse_date(fiscal_raw)
        if fy_date is None:
            continue
        out.append(
            (
                YearlyFinancials(
                    fiscal_date=fy_date,
                    ebitda=_pos_or_none(data.get("ebitda")),
                    free_cash_flow=_pos_or_none(_derive_fcf(data)),
                    net_debt=float(data.get("total_debt") or 0.0)
                    - float(data.get("total_cash") or 0.0),
                ),
                _pos_or_none(data.get("shares_outstanding")),
            )
        )
    return out


async def load_price_history(
    ticker: str, data_layer: DataLayer, years: int
) -> list[PricePoint]:
    """Pull `years` of (date, close) points from DataType.PRICE."""
    try:
        result = await data_layer.fetch(DataType.PRICE, ticker)
    except (ProviderError, ValueError, KeyError) as exc:
        logger.info("price history fetch failed for %s: %s", ticker, exc)
        return []
    history = result.data.get("price_history") if isinstance(result.data, dict) else None
    if not isinstance(history, list):
        return []

    cutoff = date(datetime.now(tz=timezone.utc).year - years, 1, 1)
    points: list[PricePoint] = []
    for row in history:
        if not isinstance(row, dict):
            continue
        d = _parse_date(row.get("date"))
        if d is None or d < cutoff:
            continue
        close = row.get("close")
        try:
            close_f = float(close) if close is not None else None
        except (TypeError, ValueError):
            continue
        if close_f is None or close_f <= 0:
            continue
        points.append(PricePoint(sample_date=d, close=close_f))
    points.sort(key=lambda p: p.sample_date)
    return points


def extract_shares_from_yearly(
    yearly: list[tuple[YearlyFinancials, float | None]],
) -> float | None:
    """Most recent year's shares; fall back to the newest non-None entry."""
    for _, shares in reversed(yearly):
        if shares is not None and shares > 0:
            return shares
    return None


async def compute_bands_via_data_layer(
    ticker: str,
    metric: HistoricalMetricName,
    years: int,
    data_layer: DataLayer,
) -> HistoricalBand:
    """End-to-end: fetch financials + price, hand off to the compute leaf."""
    yearly = await load_yearly_financials(ticker, data_layer, years=max(years, 5))
    prices = await load_price_history(ticker, data_layer, years=years)
    shares = extract_shares_from_yearly(yearly)
    return compute_historical_band(
        metric=metric,
        yearly=[y for y, _ in yearly],
        prices=prices,
        shares_outstanding=shares or 0.0,
    )


def classify_band(band: HistoricalBand) -> BandClassification:
    """UI hint: where does `current` sit vs P25 / P75 / P90 (spec §6.6)."""
    if band.current is None or band.p25 is None or band.p75 is None:
        return "unknown"
    if band.p90 is not None and band.current >= band.p90:
        return "expensive"
    if band.current >= band.p75:
        return "expensive"
    if band.current <= band.p25:
        return "cheap"
    return "fair"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _derive_fcf(data: dict[str, Any]) -> float | None:
    """FCF = OperatingCashFlow - CapEx when both rows are present."""
    ocf = data.get("operating_cash_flow")
    capex = data.get("capital_expenditure")
    if ocf is None or capex is None:
        explicit = data.get("free_cash_flow")
        try:
            return float(explicit) if explicit is not None else None
        except (TypeError, ValueError):
            return None
    try:
        return float(ocf) - abs(float(capex))
    except (TypeError, ValueError):
        return None


def _pos_or_none(v: Any) -> float | None:
    try:
        f = float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
    return f if f is not None and f > 0 else None


def _parse_date(raw: Any) -> date | None:
    if isinstance(raw, date):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None
