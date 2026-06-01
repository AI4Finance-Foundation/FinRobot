"""Provider-agnostic historical financials extractor.

What this code does that raw LLM cannot:
- Consumes ``DataLayer.fetch_historical(FINANCIALS)`` — a list of per-year
  DataResults whose ``.data`` dicts follow the canonical normalized schema both
  providers emit (FMP and yfinance) — and assembles a typed HistoricalMetrics
  with CFA-standard derived ratios/CAGR. An LLM would produce plausible-but-
  varying numbers across invocations.
- Owns no provider/yfinance knowledge: the DataLayer provider chain
  (FMP → yfinance) selects the source and normalizes its shape. This module is
  the single point where all yfinance access for DCF history was收口 into the
  DataLayer abstraction (门一), so the future circuit-breaker covers it.
- Sorts data oldest-first so all parallel list fields are time-aligned. Absolute
  line items keep the None→0.0 fill the downstream dcf_seed medians expect (an
  all-zero row reads as "missing"); derived margins instead stay None when their
  numerator is absent, so a missing margin never reads as a real 0%.
"""

from __future__ import annotations

import math
from typing import Any

from finrobot.engine.compute.data_processor import calculate_cagr
from finrobot.engine.data.interface import DataResult, ProviderError
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.data.types import DataType
from finrobot.engine.models.financial import HistoricalMetrics


async def fetch_historical_metrics(
    data_layer: DataLayer, ticker: str, years: int = 5
) -> HistoricalMetrics:
    """Fetch multi-year financials via the DataLayer and build HistoricalMetrics.

    Args:
        data_layer: The shared DataLayer (provider chain FMP → yfinance).
        ticker: Upper-case stock ticker symbol (e.g. "AAPL").
        years: Maximum number of annual periods to include (default 5).

    Returns:
        Fully populated HistoricalMetrics, sorted oldest-first. Returns a minimal
        placeholder (empty lists) when no usable historical data is available, so
        callers/dcf_seed degrade gracefully to industry medians rather than crash.
    """
    results = await data_layer.fetch_historical(DataType.FINANCIALS, ticker, years=years)
    # Trailing P/E + price_data_available come from the current-snapshot
    # financials (yfinance's info.trailingPE). Best-effort and normally a cache
    # hit — most callers fetched the snapshot moments earlier.
    trailing_pe = await _fetch_trailing_pe(data_layer, ticker)
    return _build_from_yearly(ticker, results, years, trailing_pe)


async def _fetch_trailing_pe(data_layer: DataLayer, ticker: str) -> float | None:
    """Best-effort current trailing P/E from the snapshot FINANCIALS canonical payload."""
    try:
        fin = await data_layer.fetch_canonical(DataType.FINANCIALS, ticker)
        # NormalizedFinancials carries pe_ratio as a typed optional float.
        from finrobot.engine.data.normalize.contracts import NormalizedFinancials

        if isinstance(fin, NormalizedFinancials):
            return fin.pe_ratio
        return None
    except (ProviderError, ValueError, KeyError):
        return None


def _build_from_yearly(
    ticker: str,
    results: list[DataResult],
    max_years: int,
    trailing_pe: float | None,
) -> HistoricalMetrics:
    """Pure function: assemble HistoricalMetrics from normalized per-year dicts.

    Kept separate from the async wrapper so it can be tested synchronously.
    """
    # Parse rows; drop years without usable revenue (mirrors the old
    # revenue-NaN column filter so a NaN year doesn't poison CAGR/medians).
    rows: list[tuple[str, int, dict[str, Any]]] = []
    for result in results:
        data = result.data if isinstance(result.data, dict) else {}
        rev = _safe_float(data.get("revenue"))
        if rev is None or rev <= 0:
            continue
        fiscal_raw = data.get("fiscal_year") or data.get("date")
        year = _year_of(fiscal_raw)
        if year is None:
            continue
        rows.append((str(fiscal_raw), year, data))

    if not rows:
        return _empty_metrics(ticker)

    # Oldest-first, then window to the most recent ``max_years``.
    rows.sort(key=lambda r: r[0])
    rows = rows[-max_years:]

    years_list: list[int] = []
    revenue_list: list[float] = []
    gp_list: list[float] = []
    gross_margin_list: list[float | None] = []
    cogs_list: list[float] = []
    ebitda_list: list[float] = []
    ebitda_margin_list: list[float | None] = []
    oi_list: list[float] = []
    operating_margin_list: list[float | None] = []
    ni_list: list[float] = []
    eps_list: list[float] = []
    sga_list: list[float] = []
    sga_ratio_list: list[float | None] = []
    ocf_list: list[float] = []
    icf_list: list[float] = []
    fcf_list: list[float] = []
    da_list: list[float] = []
    capex_list: list[float] = []
    nwc_change_list: list[float] = []

    for _fy_str, year, data in rows:
        # Raw (None when the provider omitted the row) drives the margins below
        # so a *missing* numerator yields a None margin, not a fabricated 0%.
        # The absolute line-item lists keep the 0.0 fill — downstream consumers
        # (dcf_seed._median_ratio, shares-from-EPS) already treat all-zero rows
        # as "missing", so 0.0 there is the established convention.
        raw_gp = _safe_float(data.get("gross_profit"))
        raw_ebitda = _safe_float(data.get("ebitda"))
        raw_oi = _safe_float(data.get("operating_income"))
        raw_sga = _safe_float(data.get("sga_expense"))
        rev = _safe_float(data.get("revenue")) or 0.0
        gp = raw_gp or 0.0
        ebitda = raw_ebitda or 0.0
        oi = raw_oi or 0.0
        ni = _safe_float(data.get("net_income")) or 0.0
        eps = _safe_float(data.get("eps")) or 0.0
        sga = raw_sga or 0.0

        rev_positive = rev > 0
        years_list.append(year)
        revenue_list.append(rev)
        gp_list.append(gp)
        gross_margin_list.append(raw_gp / rev if (raw_gp is not None and rev_positive) else None)
        cogs_list.append(rev - gp)
        ebitda_list.append(ebitda)
        ebitda_margin_list.append(
            raw_ebitda / rev if (raw_ebitda is not None and rev_positive) else None
        )
        oi_list.append(oi)
        operating_margin_list.append(
            raw_oi / rev if (raw_oi is not None and rev_positive) else None
        )
        ni_list.append(ni)
        eps_list.append(eps)
        sga_list.append(sga)
        sga_ratio_list.append(raw_sga / rev if (raw_sga is not None and rev_positive) else None)

        # Cash-flow scalars: a structurally-absent row stays 0.0. dcf_seed's
        # _median_ratio treats an all-zero row as "missing" and falls back to
        # industry medians, so 0.0 is the correct fill (not a fabricated value).
        ocf_list.append(_safe_float(data.get("operating_cash_flow")) or 0.0)
        icf_list.append(_safe_float(data.get("investing_cash_flow")) or 0.0)
        fcf_list.append(_safe_float(data.get("financing_cash_flow")) or 0.0)
        # D&A is reported positive; CapEx is already a positive magnitude
        # (providers sign-flip the cash outflow) — both feed the FCF formula's
        # "+ D&A - CapEx" convention as positive numbers.
        da_list.append(_safe_float(data.get("depreciation_amortization")) or 0.0)
        capex_list.append(_safe_float(data.get("capital_expenditure")) or 0.0)
        nwc_change_list.append(_safe_float(data.get("change_in_working_capital")) or 0.0)

    # YoY revenue growth (None for the oldest year and across any 0-fill gaps).
    revenue_growth: list[float | None] = []
    for i, rev in enumerate(revenue_list):
        if i == 0:
            revenue_growth.append(None)
            continue
        prev = revenue_list[i - 1]
        revenue_growth.append((rev - prev) / prev if prev > 0 and rev > 0 else None)

    n = len(years_list)
    cagr = calculate_cagr(revenue_list[0], revenue_list[-1], n - 1) if n >= 2 else None

    # Trailing P/E only on the most-recent year (historical P/E needs per-year
    # price, which the financials feed doesn't carry); keeps EpsPeChart honest.
    pe_list: list[float | None] = [None] * n
    if trailing_pe is not None and n > 0:
        pe_list[-1] = trailing_pe

    return HistoricalMetrics(
        years=years_list,
        revenue=revenue_list,
        revenue_growth_yoy=revenue_growth,
        cogs=cogs_list,
        gross_profit=gp_list,
        gross_margin=gross_margin_list,
        sga=sga_list,
        sga_ratio=sga_ratio_list,
        ebitda=ebitda_list,
        ebitda_margin=ebitda_margin_list,
        operating_income=oi_list,
        operating_margin=operating_margin_list,
        net_income=ni_list,
        eps=eps_list,
        pe_ratio=pe_list,
        cagr_revenue=cagr,
        ticker=ticker,
        price_data_available=trailing_pe is not None,
        operating_cash_flow=ocf_list,
        investing_cash_flow=icf_list,
        financing_cash_flow=fcf_list,
        depreciation_amortization=da_list,
        capital_expenditure=capex_list,
        change_in_working_capital=nwc_change_list,
    )


def _empty_metrics(ticker: str) -> HistoricalMetrics:
    """Minimal placeholder when no usable history exists.

    Cash-flow / DCF list fields default to [] via the model; dcf_seed detects
    emptiness and falls back to industry medians.
    """
    return HistoricalMetrics(
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


def _safe_float(value: object) -> float | None:
    """Convert a scalar to float; return None on any error or NaN.

    NaN is treated as missing — not a legitimate 0 — so a row that exists but is
    empty doesn't masquerade as a real zero in the derived ratios.
    """
    if value is None:
        return None
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if math.isnan(result) else result


def _year_of(raw: object) -> int | None:
    """Extract the 4-digit fiscal year from a 'YYYY-MM-DD' (or 'YYYY') value."""
    if raw is None:
        return None
    text = str(raw)
    try:
        return int(text[:4])
    except ValueError:
        return None
