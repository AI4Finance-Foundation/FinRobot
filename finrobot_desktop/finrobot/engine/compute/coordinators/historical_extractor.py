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

from finrobot.engine.compute.operators.data_processor import calculate_cagr
from finrobot.engine.data.historical_loaders import resolve_historical_fx
from finrobot.engine.data.interface import DataResult, ProviderError
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.data.types import DataType
from finrobot.engine.models.financial import HistoricalMetrics
from finrobot.engine.primitives.industry import is_commodity_cyclical

# Default trailing window for non-cyclicals: equity-research convention seeds the
# DCF off the trailing ~5y (sliced to ~3y for the median inside dcf_seed).
_DEFAULT_HISTORY_YEARS: int = 5

# Cyclical / commodity names need a window that spans a FULL business cycle plus
# the current regime (peak→trough→recovery), so the through-cycle median isn't
# computed on a truncated half-cycle. Memory was peak FY2018 → trough FY2023 →
# AI super-cycle FY2024-2026 (SEC-verified), ≈9 fiscal years end-to-end; pull 10
# so the whole cycle is in-window. Lands in its own cache slot (the cache key
# folds in ``years``, so 10 never collides with the 5-year slot — T6#2).
_CYCLICAL_HISTORY_YEARS: int = 10

# A cyclical whose chain fetch (FMP / yfinance) yields fewer usable years than this
# is missing peak/trough phases — augment with SEC companyfacts deep history. The
# memory cycle spans ~9 fiscal years (FY2018 peak → FY2023 trough → FY2025
# recovery); 6 is the floor below which the trailing window can't straddle a full
# peak→trough (it would catch only the current regime + one turn). FMP/yfinance
# empirically field ~4, so this fires for every memory/storage name on the default
# chain while never second-guessing a chain that already returned deep enough.
_MIN_THROUGH_CYCLE_YEARS: int = 6


async def fetch_historical_metrics(
    data_layer: DataLayer,
    ticker: str,
    years: int | None = None,
    *,
    industry: str | None = None,
    sector: str | None = None,
) -> HistoricalMetrics:
    """Fetch multi-year financials via the DataLayer and build HistoricalMetrics.

    Args:
        data_layer: The shared DataLayer (provider chain FMP → yfinance).
        ticker: Upper-case stock ticker symbol (e.g. "AAPL").
        years: Maximum number of annual periods to include. ``None`` (the default)
            means AUTO: 5 for a normal name, 10 for a commodity-cyclical so the
            through-cycle median sees a full peak→trough→recovery window. Pass an
            explicit int only to override (e.g. the /historical route's UI window).
        industry: Provider industry label, when the caller already has the
            snapshot. Lets a non-memory cyclical (steel/oil/shipping) also get the
            extended window. None is fine — memory/storage names still extend via
            the curated ticker anchor inside ``is_commodity_cyclical``.
        sector: Provider sector label (reserved; industry tag is decisive).

    Returns:
        Fully populated HistoricalMetrics, sorted oldest-first. Returns a minimal
        placeholder (empty lists) when no usable historical data is available, so
        callers/dcf_seed degrade gracefully to industry medians rather than crash.

    Currency: a foreign issuer's yearly statements arrive in the native
    reporting currency (TSM: TWD) while the snapshot FinancialData in the same
    report is FX-normalized to the quote currency — the multi-year revenue/EPS
    charts and LLM narrative were silently mixing the two. Absolute monetary
    fields are converted at today's spot via the same chokepoint the band
    loader uses (resolve_historical_fx); ratios/margins/CAGR are
    currency-invariant. When FX is unavailable the figures stay native and the
    ``currency`` tag discloses it (the metrics still serve dcf_seed's
    currency-invariant ratio medians, so dropping them would be overkill).
    """
    # AUTO window: extend for commodity-cyclicals so the through-cycle median has a
    # full cycle in-window. The ticker anchor covers memory/storage on every call
    # site (none of which carries a description); industry covers the rest when the
    # caller has it. An explicit ``years`` always wins (the UI /historical window).
    cyclical = False
    if years is None:
        cyclical = is_commodity_cyclical(industry=industry, sector=sector, ticker=ticker)
        years = _CYCLICAL_HISTORY_YEARS if cyclical else _DEFAULT_HISTORY_YEARS
    results = await data_layer.fetch_historical(DataType.FINANCIALS, ticker, years=years)
    # Deep-history augmentation: FMP / yfinance only field ~4 annual periods, which
    # truncates a commodity-cyclical's through-cycle window (the MU FY2018 peak +
    # FY2018-22 downturn fall off-window, so the trailing median misprices). When a
    # cyclical's chain fetch is shallower than the window needs, pull the full SEC
    # companyfacts history (≥9y, no API key) and use it when it is genuinely deeper.
    # Non-cyclicals never touch SEC — their FMP/yfinance window stays byte-identical.
    if cyclical and _usable_year_count(results) < _MIN_THROUGH_CYCLE_YEARS:
        sec_results = await data_layer.fetch_deep_history(ticker, years)
        if sec_results is not None and _usable_year_count(sec_results) > _usable_year_count(
            results
        ):
            results = sec_results
    fx = await resolve_historical_fx(results, data_layer, ticker)
    # Trailing P/E + price_data_available come from the current-snapshot
    # financials (yfinance's info.trailingPE). Best-effort and normally a cache
    # hit — most callers fetched the snapshot moments earlier.
    trailing_pe = await _fetch_trailing_pe(data_layer, ticker)
    return _build_from_yearly(
        ticker,
        results,
        years,
        trailing_pe,
        fx_rate=fx.rate if fx.rate is not None else 1.0,
        currency=fx.currency_of_figures,
        data_source=_aggregate_provider(results),
    )


def _aggregate_provider(results: list[DataResult]) -> str | None:
    """Collapse per-year provider tags into one provenance string.

    One fetch normally serves every year from the same provider, but the
    contract doesn't promise it — an honest "mixed:a+b" beats silently
    reporting whichever year came last. None when there are no rows.
    """
    providers = sorted({r.provider for r in results if r.provider})
    if not providers:
        return None
    if len(providers) == 1:
        return providers[0]
    return "mixed:" + "+".join(providers)


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
    fx_rate: float = 1.0,
    currency: str | None = None,
    data_source: str | None = None,
) -> HistoricalMetrics:
    """Pure function: assemble HistoricalMetrics from normalized per-year dicts.

    Kept separate from the async wrapper so it can be tested synchronously.
    ``fx_rate`` scales every absolute monetary field (financial→quote spot);
    ``currency`` is the tag for the figures AFTER scaling. Ratios computed
    below are invariant (numerator and denominator scale together).
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
    gp_list: list[float | None] = []
    gross_margin_list: list[float | None] = []
    cogs_list: list[float | None] = []
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
    financing_cf_list: list[float] = []
    da_list: list[float] = []
    capex_list: list[float] = []
    nwc_change_list: list[float] = []
    equity_list: list[float | None] = []

    for _fy_str, year, data in rows:
        # Raw (None when the provider omitted the row) drives the margins below
        # so a *missing* numerator yields a None margin, not a fabricated 0%.
        # The absolute line-item lists keep the 0.0 fill — downstream consumers
        # (dcf_seed._median_ratio, shares-from-EPS) already treat all-zero rows
        # as "missing", so 0.0 there is the established convention.
        raw_gp = _fx(_safe_float(data.get("gross_profit")), fx_rate)
        raw_ebitda = _fx(_safe_float(data.get("ebitda")), fx_rate)
        raw_oi = _fx(_safe_float(data.get("operating_income")), fx_rate)
        raw_sga = _fx(_safe_float(data.get("sga_expense")), fx_rate)
        rev = (_safe_float(data.get("revenue")) or 0.0) * fx_rate
        ebitda = raw_ebitda or 0.0
        oi = raw_oi or 0.0
        ni = (_safe_float(data.get("net_income")) or 0.0) * fx_rate
        eps = (_safe_float(data.get("eps")) or 0.0) * fx_rate
        sga = raw_sga or 0.0

        rev_positive = rev > 0
        years_list.append(year)
        revenue_list.append(rev)
        # cogs / gross_profit propagate None when the provider omits gross_profit
        # (no-COGS businesses like banks) — never fabricate cogs = revenue − 0,
        # which would render a bank's COGS as its full revenue.
        gp_list.append(raw_gp)
        gross_margin_list.append(raw_gp / rev if (raw_gp is not None and rev_positive) else None)
        cogs_list.append(rev - raw_gp if raw_gp is not None else None)
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
        ocf_list.append((_safe_float(data.get("operating_cash_flow")) or 0.0) * fx_rate)
        icf_list.append((_safe_float(data.get("investing_cash_flow")) or 0.0) * fx_rate)
        financing_cf_list.append((_safe_float(data.get("financing_cash_flow")) or 0.0) * fx_rate)
        # D&A is reported positive; CapEx is already a positive magnitude
        # (providers sign-flip the cash outflow) — both feed the FCF formula's
        # "+ D&A - CapEx" convention as positive numbers.
        da_list.append((_safe_float(data.get("depreciation_amortization")) or 0.0) * fx_rate)
        capex_list.append((_safe_float(data.get("capital_expenditure")) or 0.0) * fx_rate)
        nwc_change_list.append(
            (_safe_float(data.get("change_in_working_capital")) or 0.0) * fx_rate
        )
        # Per-year parent equity (None when omitted). FX-scaled like net_income so the
        # net_income/equity through-cycle ROE ratio is currency-invariant either way.
        equity_list.append(_fx(_safe_float(data.get("total_equity")), fx_rate))

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
        currency=currency,
        data_source=data_source,
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
        financing_cash_flow=financing_cf_list,
        depreciation_amortization=da_list,
        capital_expenditure=capex_list,
        change_in_working_capital=nwc_change_list,
        shareholders_equity=equity_list,
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


def _fx(value: float | None, rate: float) -> float | None:
    """Scale an optional monetary value by the FX rate, preserving None."""
    return value * rate if value is not None else None


def _usable_year_count(results: list[DataResult]) -> int:
    """How many rows carry a usable (positive, finite) revenue.

    Mirrors the row filter in ``_build_from_yearly`` so the deep-history decision
    counts the SAME years that will actually feed the medians — a DataResult list
    whose rows are all revenue-less (an error/empty fetch) reads as 0, never as its
    nominal length, so a shallow-but-nonempty chain result can't block the SEC
    augmentation.
    """
    count = 0
    for result in results:
        data = result.data if isinstance(result.data, dict) else {}
        rev = _safe_float(data.get("revenue"))
        if rev is not None and rev > 0:
            count += 1
    return count


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
