"""Market data service -- fetches price history, quarterly data, performance.

This module owns all direct yfinance interactions for the routes layer.
Route handlers should call these functions instead of importing yfinance
themselves, keeping the routes thin (parse params -> call service -> return).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd
import yfinance as yf


async def fetch_price_history(ticker: str, period: str = "1y") -> dict[str, Any]:
    """Fetch historical OHLCV price data from yfinance.

    Args:
        ticker: Stock ticker symbol (e.g. "AAPL").
        period: yfinance period string (e.g. "1y", "6mo", "5d").

    Returns:
        Dict with current_price, history list, data_source, and warnings.

    Raises:
        ValueError: If no price data is available for the ticker.
    """

    def _fetch() -> dict[str, Any]:
        t = yf.Ticker(ticker)
        hist = t.history(period=period)
        info = t.info or {}
        history = []
        for date, row in hist.iterrows():
            history.append(
                {
                    "date": date.strftime("%Y-%m-%d"),
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": int(row["Volume"]),
                }
            )
        return {
            "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "history": history,
            "data_source": "yfinance",
            "warnings": [],
        }

    return await asyncio.to_thread(_fetch)


async def fetch_quarterly_data(ticker: str) -> dict[str, Any]:
    """Fetch quarterly income statement and cash flow data from yfinance.

    Args:
        ticker: Stock ticker symbol.

    Returns:
        Dict with ticker and quarters list (up to 8 most recent).

    Raises:
        ValueError: If no quarterly data is available.
    """

    def _fetch() -> dict[str, Any]:
        t = yf.Ticker(ticker)
        income = t.quarterly_income_stmt
        cashflow = t.quarterly_cashflow

        if income is None or income.empty:
            raise ValueError(f"No quarterly data available for {ticker}")

        quarters = []
        for col in income.columns[:8]:  # Last 8 quarters
            year = col.year
            quarter = (col.month - 1) // 3 + 1
            quarter_label = f"{year}-Q{quarter}"

            revenue = _safe_get(income, col, ["Total Revenue", "Revenue"])
            op_income = _safe_get(
                income, col, ["Operating Income", "Total Operating Profit Loss"]
            )
            net_income = _safe_get(
                income, col, ["Net Income", "Net Income Common Stockholders"]
            )

            op_cf = None
            if cashflow is not None and not cashflow.empty and col in cashflow.columns:
                op_cf = _safe_get(
                    cashflow,
                    col,
                    [
                        "Operating Cash Flow",
                        "Cash Flow From Continuing Operating Activities",
                    ],
                )

            if revenue is not None:
                quarters.append(
                    {
                        "quarter": quarter_label,
                        "revenue": revenue,
                        "operating_income": op_income,
                        "net_income": net_income,
                        "operating_cash_flow": op_cf,
                    }
                )

        return {"ticker": ticker, "quarters": quarters}

    return await asyncio.to_thread(_fetch)


async def fetch_performance_data(
    tickers: list[str], benchmark: str, period: str
) -> dict[str, Any]:
    """Fetch and normalize multi-ticker price performance.

    Downloads price data for all tickers + benchmark, normalizes to base 100,
    and returns series suitable for charting.

    Args:
        tickers: List of ticker symbols to compare.
        benchmark: Benchmark ticker (e.g. "SPY").
        period: yfinance period string.

    Returns:
        Dict with series list, each containing ticker, label, and data points.

    Raises:
        ValueError: If no price data is available.
    """
    all_tickers = [*tickers, benchmark]

    def _fetch() -> dict[str, Any]:
        df = yf.download(all_tickers, period=period, progress=False)
        if df.empty:
            raise ValueError(f"No price data for {all_tickers}")

        close = (
            df["Close"]
            if len(all_tickers) > 1
            else df[["Close"]].rename(columns={"Close": all_tickers[0]})
        )

        series = []
        for t in all_tickers:
            if t not in close.columns:
                continue
            col = close[t].dropna()
            if col.empty:
                continue
            base = col.iloc[0]
            normalized = (col / base * 100).round(2)
            data = [
                {"date": d.strftime("%Y-%m-%d"), "value": float(v)}
                for d, v in normalized.items()
            ]
            label = "S&P 500" if t == benchmark else t
            series.append({"ticker": t, "label": label, "data": data})

        return {"series": series}

    return await asyncio.to_thread(_fetch)


def _safe_get(df: pd.DataFrame, col: Any, row_names: list[str]) -> float | None:
    """Try multiple row names for a DataFrame column, return first found."""
    for name in row_names:
        if name in df.index:
            val = df.loc[name, col]
            if val is not None and not pd.isna(val):
                return float(val)
    return None
