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
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from finrobot.engine.primitives.historical_valuation import (
    HistoricalBand,
    HistoricalMetricName,
    PricePoint,
    YearlyFinancials,
    compute_historical_band,
)
from finrobot.engine.data.interface import DataResult, ProviderError
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.data.types import DataType

logger = logging.getLogger(__name__)


BandClassification = Literal["expensive", "fair", "cheap", "unknown"]


# The single trailing window an equity-research report uses for EV/EBITDA (and
# P/FCF) historical bands. Both band surfaces inside one report must share it, or
# the report shows two windows for the "same" band and their cheap/fair/expensive
# verdicts silently disagree:
#   - the valuation-method band (fetch_reverse_multiple_band → _ev_ebitda_method /
#     _p_fcf_method, labelled "self_5y_…"), and
#   - the technical chapter's band snapshot (build_technical_analysis → this
#     module's compute_bands_via_data_layer).
# Before this constant the two relied on independent literal defaults (5 vs 3) and
# GOOGL's report printed a 3y technical band (P25 16.9 / med 19.0 / P75 23.1)
# against a 5y method band (mid 17.6) — the drift this pins shut. The standalone
# GET /api/valuation/historical-bands route deliberately does NOT use this: it
# exposes its own user-chosen `years` query param (default 3, range 1-10) for the
# live band card, a separate surface from the report.
REPORT_BAND_WINDOW_YEARS = 5


@dataclass(frozen=True)
class HistoricalFx:
    """Resolved FX context for per-year FINANCIALS history.

    ``rate`` is the financial→quote spot factor to apply to native figures:
      - 1.0  — no conversion due (same currency, or tags absent in test fakes)
      - >0   — conversion factor
      - None — conversion DUE but FX unavailable. Callers must NOT fall back
        to 1.0 silently (fx.py's own contract): a band would mix currencies
        in one multiple (TSM ~0.05x), so it refuses; per-year metrics stay
        native but carry the honest currency tag.
    """

    rate: float | None
    financial_currency: str | None
    quote_currency: str | None

    @property
    def currency_of_figures(self) -> str | None:
        """Currency the figures are in AFTER applying ``rate or 1``."""
        if self.rate is None:
            return self.financial_currency
        return self.quote_currency or self.financial_currency


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

    # ADR FX (W3-A路 · Bug B): FMP reports a foreign issuer's yearly statements
    # in its native currency (financial_currency, e.g. TWD/JPY) while the ADR —
    # and this band's price history — is quoted in quote_currency (USD). The
    # native EBITDA / net-debt must be put in the quote currency BEFORE they meet
    # the USD price in _compute_multiple, or EV/EBITDA mixes currencies and
    # collapses (TSM live band came out ~0.05x vs the ~23x canonical). Mirrors the
    # canonical FX chokepoint (layer._apply_canonical_fx); the share count and the
    # FCF/ratio caliber are handled per field below. A current spot rate is
    # applied to every year — the per-year FX drift is a single-digit-% residual
    # on the equity term, vs the ~600× currency error it replaces; period-matched
    # historical FX is tracked as a follow-up.
    fx = await resolve_historical_fx(results, data_layer, ticker)
    if fx.rate is None:
        # FX due but unavailable: a band multiple mixes the native financial
        # leg with the quote-currency price leg in ONE number — that's the
        # ~0.05x TSM garbage, not a degraded approximation. Refuse the band
        # (callers degrade to "no band") instead of silently applying 1.0,
        # honoring fx.py's "never fall back to 1.0" contract.
        logger.warning(
            "historical-band FX %s→%s unavailable for %s — band withheld "
            "(refusing a currency-mixed multiple)",
            fx.financial_currency,
            fx.quote_currency,
            ticker,
        )
        return []
    fx_rate = fx.rate

    out: list[tuple[YearlyFinancials, float | None]] = []
    for result in results:
        data = result.data if isinstance(result.data, dict) else {}
        fiscal_raw = data.get("fiscal_year") or data.get("date")
        fy_date = _parse_date(fiscal_raw)
        if fy_date is None:
            continue
        ebitda_native = _pos_or_none(data.get("ebitda"))
        fcf_native = _pos_or_none(_derive_fcf(data))
        # None ≠ 0: a year whose balance rows failed to align (or a provider
        # that omits debt/cash for the yearly path) has an UNKNOWN net debt —
        # filling 0 fabricated a debt-free EV and skewed the band low for
        # levered issuers. Both legs must be present.
        debt = _opt_float(data.get("total_debt"))
        cash = _opt_float(data.get("total_cash"))
        net_debt_native = debt - cash if (debt is not None and cash is not None) else None
        out.append(
            (
                YearlyFinancials(
                    fiscal_date=fy_date,
                    ebitda=ebitda_native * fx_rate if ebitda_native is not None else None,
                    free_cash_flow=fcf_native * fx_rate if fcf_native is not None else None,
                    net_debt=net_debt_native * fx_rate if net_debt_native is not None else None,
                ),
                _pos_or_none(data.get("shares_outstanding")),
            )
        )
    return out


async def resolve_historical_fx(
    results: list[DataResult], data_layer: DataLayer, ticker: str
) -> HistoricalFx:
    """Resolve the financial→quote FX context for per-year history.

    Shared chokepoint for BOTH per-year consumers — the band loader above and
    the metrics coordinator (compute.coordinators.historical_extractor) — so
    they can't drift apart on currency handling. ``rate=None`` means a
    conversion is due but the FX fetch failed: callers decide (band → refuse a
    currency-mixed multiple; metrics → keep native figures + honest currency
    tag). Never silently 1.0 on failure (fx.py's contract).
    """
    if not results or not hasattr(data_layer, "reporting_to_quote_rate"):
        return HistoricalFx(rate=1.0, financial_currency=None, quote_currency=None)
    first = results[0].data if isinstance(results[0].data, dict) else {}
    fin_ccy = str(first.get("financial_currency") or "").upper() or None
    quote_ccy = str(first.get("quote_currency") or "").upper() or None
    if not fin_ccy or not quote_ccy or fin_ccy == quote_ccy:
        return HistoricalFx(rate=1.0, financial_currency=fin_ccy, quote_currency=quote_ccy)
    try:
        rate = await data_layer.reporting_to_quote_rate(fin_ccy, quote_ccy)
    except (ProviderError, ValueError) as exc:
        logger.warning(
            "historical FX %s→%s failed for %s: %s",
            fin_ccy,
            quote_ccy,
            ticker,
            exc,
        )
        return HistoricalFx(rate=None, financial_currency=fin_ccy, quote_currency=quote_ccy)
    logger.info("historical FX %s→%s=%.5f applied for %s", fin_ccy, quote_ccy, rate, ticker)
    return HistoricalFx(rate=rate, financial_currency=fin_ccy, quote_currency=quote_ccy)


def _opt_float(v: Any) -> float | None:
    """float(v) or None — missing/unparseable stays None (None ≠ 0)."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


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


# Minimum price-multiple samples behind a historical band before it may price a
# reverse-multiple method (EV/EBITDA, P/FCF) on the Football Field.
# ``sample_count`` counts daily (price × trailing-annual-financial) multiples, so
# a name with even one year of public price history clears this easily (~250
# trading days). The floor only screens out a band so sparse it carries no
# distribution — a freshly-listed name with a handful of price points whose p25/p75
# would just echo a single multiple, dressing one number as a range. Below the
# floor the band is withheld (method drops with a warning) rather than emitting a
# degenerate point in a range's clothing.
_MIN_BAND_SAMPLES = 60


@dataclass(frozen=True)
class HistoricalBandSpread:
    """The (p25, p75) reverse-multiple band + provenance for a Football Field row.

    ``sample_count`` and ``years_thin`` let the consumer record on the emitted
    ``ValuationMethodRange`` HOW degraded the band is, so the confidence dial and
    the analyst both see a thin-history reverse multiple for what it is rather than
    a fully-corroborated one.
    """

    p25: float
    p75: float
    sample_count: int


async def fetch_reverse_multiple_band(
    ticker: str,
    metric: HistoricalMetricName,
    data_layer: DataLayer | None,
    *,
    years: int = REPORT_BAND_WINDOW_YEARS,
    current_override: float | None = None,
) -> HistoricalBandSpread | None:
    """Resolve the (p25, p75) historical-multiple band for a reverse method.

    This is the single door both the equity-research pipeline
    (``build_valuation_synthesis``) and the ``/api/valuation/aggregate`` route use
    to feed ``aggregate_valuation``'s ``historical_ev_ebitda_band`` /
    ``historical_p_fcf_band`` inputs. Before this existed both callers passed
    ``None``, so the EV/EBITDA and P/FCF reverse-multiple rows could NEVER fire in
    production even though the band itself is fully computable (it already powers
    ``GET /api/valuation/historical-bands``). Wiring it revives a real degraded
    valuation method: the band's own historical P25/P75 multiple × a real forward
    number − real net debt — every input a reported figure, none fabricated.

    Returns None (the method then drops, as before) when no data layer is
    configured, the band fetch fails, the band has no usable P25/P75, or the
    sample count is below ``_MIN_BAND_SAMPLES`` (too sparse to be a distribution).
    """
    if data_layer is None:
        return None
    try:
        band = await compute_bands_via_data_layer(
            ticker, metric, years, data_layer, current_override=current_override
        )
    except (ProviderError, ValueError, KeyError, TypeError) as exc:
        logger.info("reverse-multiple band fetch failed for %s/%s: %s", ticker, metric, exc)
        return None
    p25, p75 = band.p25, band.p75
    if p25 is None or p75 is None or p25 <= 0 or p75 <= 0:
        return None
    if band.sample_count < _MIN_BAND_SAMPLES:
        logger.info(
            "reverse-multiple band for %s/%s has only %d samples (< %d) — withheld",
            ticker,
            metric,
            band.sample_count,
            _MIN_BAND_SAMPLES,
        )
        return None
    return HistoricalBandSpread(p25=p25, p75=p75, sample_count=band.sample_count)


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
