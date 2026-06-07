"""Shared IO loaders for historical-band computation.

Both the valuation route (GET /api/valuation/historical-bands/{ticker}) and
the equity-research pipeline's technical-analysis step need the same
fetch-yearly-financials + fetch-price-history + classify-band glue. Lives
here so neither layer has to import from the other.

The pure leaf (engine.primitives.historical_valuation.compute_historical_band)
stays provider-agnostic; this module owns the data-layer translation.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from finrobot.engine.primitives.historical_valuation import (
    HistoricalBand,
    HistoricalMetricName,
    PricePoint,
    YearlyFinancials,
    compute_historical_band,
)
from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.data.types import DataType

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


async def load_price_history(ticker: str, data_layer: DataLayer, years: int) -> list[PricePoint]:
    """Pull `years` of adjusted daily (date, close) PRICE_RANGE points.

    ``NormalizedPrice`` deliberately keeps only the trailing 52-week dashboard
    window. Historical valuation bands need caller-sized multi-year samples, so
    they must use the explicit PRICE_RANGE door.
    """
    if years <= 0:
        return []
    if not hasattr(data_layer, "fetch_price_range"):
        return []

    end = datetime.now(tz=timezone.utc).date()
    start = _same_day_years_ago(end, years)
    end_exclusive = end + timedelta(days=1)
    try:
        bars = await data_layer.fetch_price_range(
            ticker, start.isoformat(), end_exclusive.isoformat()
        )
    except (ProviderError, ValueError, KeyError) as exc:
        logger.info("price history fetch failed for %s: %s", ticker, exc)
        return []

    points: list[PricePoint] = []
    for bar in bars:
        if bar.date < start:
            continue
        if bar.close <= 0:
            continue
        points.append(PricePoint(sample_date=bar.date, close=bar.close))
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
    *,
    current_override: float | None = None,
) -> HistoricalBand:
    """End-to-end: fetch financials + price, hand off to the compute leaf.

    ``current_override`` (B2): the canonical TTM multiple for the current point,
    so the report's band and comps chapters agree on "current EV/EBITDA". When
    None (e.g. the standalone /historical-bands route), the band stays purely on
    trailing-annual EBITDA.
    """
    yearly = await load_yearly_financials(ticker, data_layer, years=max(years, 5))
    prices = await load_price_history(ticker, data_layer, years=years)
    shares = extract_shares_from_yearly(yearly)
    return compute_historical_band(
        metric=metric,
        yearly=[y for y, _ in yearly],
        prices=prices,
        shares_outstanding=shares or 0.0,
        current_override=current_override,
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


def _same_day_years_ago(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, month=2, day=28)
