"""Market data service -- fetches price history, quarterly data, performance.

This module owns all direct yfinance interactions for the routes layer.
Route handlers should call these functions instead of importing yfinance
themselves, keeping the routes thin (parse params -> call service -> return).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFException

from finrobot.engine.data.interface import ProviderError

logger = logging.getLogger(__name__)

# yfinance error message keyword list — case-insensitive substring match.
# A YFException whose message contains ANY of these keywords is classified
# as upstream service down (raises ProviderError → 502). Otherwise it's
# treated as invalid ticker (raises ValueError → 422).
#
# Locked by tests/audit/test_yfinance_error_mapping.py — removing a keyword
# requires an audit-reviewer-acknowledged commit.
_YFINANCE_SERVICE_DOWN_KEYWORDS: tuple[str, ...] = (
    '429',
    'rate limit',
    'connection',
    'timeout',
    'http error 5',
    'too many requests',
)


def _is_yfinance_service_down(exc: Exception) -> bool:
    """Return True iff exception message indicates upstream yfinance failure
    (rate limit, timeout, 5xx) rather than an invalid ticker."""
    msg = str(exc).lower()
    return any(kw in msg for kw in _YFINANCE_SERVICE_DOWN_KEYWORDS)


async def fetch_price_history(ticker: str, period: str = "1y") -> dict[str, Any]:
    """Fetch historical OHLCV price data + header metadata from yfinance.

    Args:
        ticker: Stock ticker symbol (e.g. "AAPL").
        period: yfinance period string (e.g. "1y", "6mo", "5d").

    Returns:
        Dict with current_price, change, change_pct, market_cap, company_name,
        history list, data_source, warnings.

    Raises:
        ProviderError: If yfinance raises any exception or no price data is available.
    """

    def _fetch() -> dict[str, Any]:
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period=period)
            info = t.info or {}
        except YFException as e:
            if _is_yfinance_service_down(e):
                raise ProviderError(f"yfinance service down for '{ticker}': {e}") from e
            # Other YFException → invalid ticker (delisted / unknown symbol / etc.)
            raise ValueError(f"未知 ticker '{ticker}': {e}") from e
        except (KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
            raise ProviderError(f"yfinance price history failed for '{ticker}': {e}") from e

        # Invalid ticker detection: yfinance does NOT raise for unknown symbols.
        # It returns hist.empty=True AND info={'trailingPegRatio': None} or similar
        # — info dict is non-empty but holds no real price signal. Empty-dict check
        # alone misses this case. Verify by looking for actual identity/price fields.
        has_price_signal = bool(
            info.get("symbol")
            or info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("marketCap")
        )
        if hist.empty and not has_price_signal:
            raise ValueError(f"未知 ticker '{ticker}': yfinance 返回空数据")

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

        current_price = info.get("currentPrice") or info.get("regularMarketPrice")

        # Compute change/change_pct from history (last 2 closes) — more reliable
        # than info.regularMarketChange which can lag during market hours.
        change: float | None = None
        change_pct: float | None = None
        if len(hist) >= 2:
            last_close = float(hist["Close"].iloc[-1])
            prev_close = float(hist["Close"].iloc[-2])
            change = last_close - prev_close
            if prev_close != 0:
                change_pct = (change / prev_close) * 100

        return {
            "current_price": current_price,
            "change": change,
            "change_pct": change_pct,
            "market_cap": info.get("marketCap"),
            "company_name": info.get("longName") or info.get("shortName"),
            # Exchange string for the TickerHero LIVE pill — "NasdaqGS" / "NYQ" etc.
            # Stays best-effort; UI falls back to "美股" when null.
            "exchange": (
                info.get("fullExchangeName")
                or info.get("exchange")
                or info.get("exchangeShortName")
            ),
            # Next earnings date — if yfinance gives it, surface it.
            # Falls back to None so the UI hides the "下次财报" callout
            # rather than stamping "待披露" everywhere (DataSnapshot bug).
            "next_earnings_date": _format_next_earnings(info),
            "history": history,
            "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
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
        try:
            t = yf.Ticker(ticker)
            income = t.quarterly_income_stmt
            cashflow = t.quarterly_cashflow
        except YFException as e:
            if _is_yfinance_service_down(e):
                raise ProviderError(
                    f"yfinance service down for '{ticker}' (quarterly): {e}"
                ) from e
            # Non-service-down YFException → unknown / delisted ticker
            raise ValueError(f"未知 ticker '{ticker}' (quarterly): {e}") from e
        except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
            raise ProviderError(f"yfinance quarterly data failed for '{ticker}': {e}") from e

        if income is None or income.empty:
            # Quarterly completely absent → ticker not covered by yfinance
            raise ValueError(f"未知 ticker 或无 quarterly 数据: '{ticker}'")

        quarters = []
        for col in income.columns[:8]:  # Last 8 quarters
            year = col.year
            quarter = (col.month - 1) // 3 + 1
            quarter_label = f"{year}-Q{quarter}"

            revenue = _safe_get(income, col, ["Total Revenue", "Revenue"])
            op_income = _safe_get(income, col, ["Operating Income", "Total Operating Profit Loss"])
            net_income = _safe_get(income, col, ["Net Income", "Net Income Common Stockholders"])

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


async def fetch_performance_data(tickers: list[str], benchmark: str, period: str) -> dict[str, Any]:
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
        try:
            df = yf.download(all_tickers, period=period, progress=False)
        except YFException as e:
            if _is_yfinance_service_down(e):
                raise ProviderError(
                    f"yfinance service down for {all_tickers} (performance): {e}"
                ) from e
            # Non-service-down YFException → invalid ticker(s)
            raise ValueError(f"未知 ticker {all_tickers} (performance): {e}") from e
        except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
            raise ProviderError(f"yfinance download failed for {all_tickers}: {e}") from e
        if df.empty:
            raise ValueError(f"No price data for {all_tickers}: yfinance 返回空")

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
                {"date": d.strftime("%Y-%m-%d"), "value": float(v)} for d, v in normalized.items()
            ]
            label = "S&P 500" if t == benchmark else t
            series.append({"ticker": t, "label": label, "data": data})

        return {"series": series}

    return await asyncio.to_thread(_fetch)


def _format_next_earnings(info: dict[str, Any]) -> str | None:
    """Extract the next-earnings date from a yfinance info dict.

    yfinance exposes one of: earningsDate (list of timestamps),
    earningsTimestamp (single epoch), or nothing. Returns ISO date or None.
    """
    raw = info.get("earningsDate") or info.get("earningsTimestamp")
    if raw is None:
        return None
    try:
        if isinstance(raw, list) and raw:
            raw = raw[0]
        if isinstance(raw, (int, float)):
            return datetime.fromtimestamp(int(raw), tz=timezone.utc).strftime("%Y-%m-%d")
        if isinstance(raw, str):
            return raw[:10]  # yfinance sometimes returns ISO timestamp string
    except (ValueError, TypeError, OSError):
        return None
    return None


def _safe_get(df: pd.DataFrame, col: Any, row_names: list[str]) -> float | None:
    """Try multiple row names for a DataFrame column, return first found."""
    for name in row_names:
        if name in df.index:
            val = df.loc[name, col]
            if val is not None and not pd.isna(val):
                return float(val)
    return None
