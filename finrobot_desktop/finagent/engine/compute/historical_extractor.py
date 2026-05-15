"""Standalone yfinance-based historical financial data extractor.

What this code does that raw LLM cannot:
- Deterministically fetches and transforms yfinance DataFrames into a typed
  HistoricalMetrics Pydantic model with CFA-standard arithmetic.
- Handles yfinance's inconsistent row naming (e.g. "Operating Cash Flow" vs
  "Cash Flow From Continuing Operating Activities") via a multi-name fallback
  lookup, guaranteeing structured output even when provider schema varies.
- Computes YoY revenue growth and CAGR with auditable formulae; an LLM would
  produce plausible-but-varying numbers across invocations.
- Sorts data oldest-first so all parallel list fields are time-aligned.
"""

from __future__ import annotations

import asyncio
from typing import Sequence

import pandas as pd
import yfinance as yf

from finagent.engine.compute.data_processor import calculate_cagr
from finagent.engine.models.financial import HistoricalMetrics

# ---------------------------------------------------------------------------
# Row-name lookup tables
# yfinance uses different row labels depending on the ticker/region/version.
# Each list is tried in order; the first match wins.
# ---------------------------------------------------------------------------

_REVENUE_NAMES = ["Total Revenue", "Revenue", "Net Revenue"]
_GROSS_PROFIT_NAMES = ["Gross Profit"]
_EBITDA_NAMES = ["EBITDA", "Normalized EBITDA"]
_OPERATING_INCOME_NAMES = ["Operating Income", "Total Operating Profit Loss"]
_NET_INCOME_NAMES = [
    "Net Income",
    "Net Income Common Stockholders",
    "Net Income From Continuing And Discontinued Operation",
]
_EPS_NAMES = ["Basic EPS", "Diluted EPS", "EPS"]
_SGA_NAMES = [
    "Selling General Administrative",
    "Selling General And Administration",
    "General And Administrative Expense",
]
_OPERATING_CF_NAMES = [
    "Operating Cash Flow",
    "Cash Flow From Continuing Operating Activities",
    "Net Cash Provided By Operating Activities",
]
_INVESTING_CF_NAMES = [
    "Investing Cash Flow",
    "Cash Flow From Continuing Investing Activities",
    "Net Cash Used For Investing Activities",
    "Net Cash Provided By Investing Activities",
]
_FINANCING_CF_NAMES = [
    "Financing Cash Flow",
    "Cash Flow From Continuing Financing Activities",
    "Net Cash Used Provided By Financing Activities",
    "Net Cash Provided By Financing Activities",
]


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def _get_row(df: pd.DataFrame, names: Sequence[str]) -> pd.Series | None:  # type: ignore[type-arg]
    """Return the first matching row from *df* by trying *names* in order.

    Returns None if *df* is empty, *names* is empty, or no name matches.
    This is the single point of yfinance schema-variance handling.
    """
    if df.empty or not names:
        return None
    for name in names:
        if name in df.index:
            return df.loc[name]
    return None


def _safe_float(value: object) -> float:
    """Convert a scalar to float; return 0.0 on any error."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------


async def extract_historical_from_yfinance(ticker: str, years: int = 5) -> HistoricalMetrics:
    """Fetch and transform yfinance annual financials into a typed HistoricalMetrics.

    Uses asyncio.to_thread to call the blocking yfinance API without blocking the
    event loop. Returns data sorted oldest-first so all parallel list fields are
    time-aligned.

    Args:
        ticker: Upper-case stock ticker symbol (e.g. "AAPL").
        years: Maximum number of annual periods to include (default 5).

    Returns:
        Fully populated HistoricalMetrics including operating_cash_flow,
        investing_cash_flow, and financing_cash_flow.
    """
    income_stmt, cashflow, info = await asyncio.to_thread(_fetch_yfinance, ticker)
    return _build_historical_metrics(ticker, income_stmt, cashflow, info, years)


def _fetch_yfinance(ticker: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Blocking yfinance call — must be run in a thread."""
    t = yf.Ticker(ticker)
    return t.income_stmt, t.cashflow, t.info


def _build_historical_metrics(
    ticker: str,
    income_stmt: pd.DataFrame,
    cashflow: pd.DataFrame,
    info: dict,
    max_years: int,
) -> HistoricalMetrics:
    """Pure function: build HistoricalMetrics from raw DataFrames + info dict.

    Kept separate from the async wrapper so it can be tested synchronously.
    """
    # ---- Validate input ----
    if income_stmt is None or income_stmt.empty:
        # Return a minimal placeholder rather than crashing — caller can surface warning
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

    # ---- Sort columns oldest-first ----
    # yfinance returns columns as Timestamps, most-recent first.
    sorted_cols = sorted(income_stmt.columns)  # ascending = oldest first
    if len(sorted_cols) > max_years:
        sorted_cols = sorted_cols[-max_years:]  # take the most recent N

    # ---- Extract income statement rows ----
    rev_row = _get_row(income_stmt, _REVENUE_NAMES)
    gp_row = _get_row(income_stmt, _GROSS_PROFIT_NAMES)
    ebitda_row = _get_row(income_stmt, _EBITDA_NAMES)
    oi_row = _get_row(income_stmt, _OPERATING_INCOME_NAMES)
    ni_row = _get_row(income_stmt, _NET_INCOME_NAMES)
    eps_row = _get_row(income_stmt, _EPS_NAMES)
    sga_row = _get_row(income_stmt, _SGA_NAMES)

    # ---- Extract cash flow rows ----
    ocf_row = (
        _get_row(cashflow, _OPERATING_CF_NAMES)
        if (cashflow is not None and not cashflow.empty)
        else None
    )
    icf_row = (
        _get_row(cashflow, _INVESTING_CF_NAMES)
        if (cashflow is not None and not cashflow.empty)
        else None
    )
    fcf_row = (
        _get_row(cashflow, _FINANCING_CF_NAMES)
        if (cashflow is not None and not cashflow.empty)
        else None
    )

    # ---- Align cashflow columns to income_stmt sorted_cols ----
    # cashflow may have different column ordering; we look up each col individually
    def _cf_value(row: pd.Series | None, col: pd.Timestamp) -> float:  # type: ignore[type-arg]
        if row is None:
            return 0.0
        try:
            return _safe_float(row[col])
        except (KeyError, IndexError):
            return 0.0

    # ---- Build parallel lists ----
    years_list: list[int] = []
    revenue_list: list[float] = []
    gp_list: list[float] = []
    gross_margin_list: list[float] = []
    cogs_list: list[float] = []
    ebitda_list: list[float] = []
    ebitda_margin_list: list[float] = []
    oi_list: list[float] = []
    operating_margin_list: list[float] = []
    ni_list: list[float] = []
    eps_list: list[float] = []
    sga_list: list[float] = []
    sga_ratio_list: list[float] = []
    ocf_list: list[float] = []
    icf_list: list[float] = []
    fcf_list: list[float] = []

    for col in sorted_cols:
        rev = _safe_float(rev_row[col]) if rev_row is not None else 0.0
        gp = _safe_float(gp_row[col]) if gp_row is not None else 0.0
        ebitda = _safe_float(ebitda_row[col]) if ebitda_row is not None else 0.0
        oi = _safe_float(oi_row[col]) if oi_row is not None else 0.0
        ni = _safe_float(ni_row[col]) if ni_row is not None else 0.0
        eps = _safe_float(eps_row[col]) if eps_row is not None else 0.0
        sga = _safe_float(sga_row[col]) if sga_row is not None else 0.0

        gross_margin = gp / rev if rev > 0 else 0.0
        ebitda_margin = ebitda / rev if rev > 0 else 0.0
        op_margin = oi / rev if rev > 0 else 0.0
        cogs = rev - gp
        sga_ratio = sga / rev if rev > 0 else 0.0

        years_list.append(col.year)
        revenue_list.append(rev)
        gp_list.append(gp)
        gross_margin_list.append(gross_margin)
        cogs_list.append(cogs)
        ebitda_list.append(ebitda)
        ebitda_margin_list.append(ebitda_margin)
        oi_list.append(oi)
        operating_margin_list.append(op_margin)
        ni_list.append(ni)
        eps_list.append(eps)
        sga_list.append(sga)
        sga_ratio_list.append(sga_ratio)
        ocf_list.append(_cf_value(ocf_row, col))
        icf_list.append(_cf_value(icf_row, col))
        fcf_list.append(_cf_value(fcf_row, col))

    # ---- YoY revenue growth (None for oldest year) ----
    revenue_growth: list[float | None] = []
    for i, rev in enumerate(revenue_list):
        if i == 0:
            revenue_growth.append(None)
        else:
            prev = revenue_list[i - 1]
            if prev != 0:
                revenue_growth.append((rev - prev) / prev)
            else:
                revenue_growth.append(None)

    # ---- CAGR ----
    n = len(years_list)
    cagr = calculate_cagr(revenue_list[0], revenue_list[-1], n - 1) if n >= 2 else None

    # ---- PE ratio ----
    # Use trailingPE from info for the most-recent year; historical years get None.
    # This makes price_data_available=True so the EpsPeChart renders in the frontend.
    trailing_pe = info.get("trailingPE") if info else None
    pe_list: list[float | None] = [None] * n
    if trailing_pe is not None and n > 0:
        pe_list[-1] = float(trailing_pe)

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
    )
