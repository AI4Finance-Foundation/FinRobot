"""FX rate provider for cross-currency peer-comps normalization.

yfinance exposes spot FX rates via tickers in the ``{FROM}{TO}=X`` form
(e.g. ``EURUSD=X`` for EUR→USD, ``TWDUSD=X`` for TWD→USD). We use
``fast_info.last_price`` for today's spot — the same source ``yfinance`` uses
for equity quotes, so the FX read path is cached / rate-limited by the same
infrastructure.

**MVP scope** (this module, current shape): single ``today's spot`` rate per
currency pair. The "correct" rate-per-line-item story per IAS 21 / ASC 830
(IS uses fiscal-period average rate, BS uses period-end spot) is on the
roadmap. The MVP rate is accurate to ~2-3% for major-currency peers (EUR /
JPY / TWD / GBP / KRW) in normal volatility regimes, which is well inside
the noise floor of peer EV/EBITDA comparisons (typical spread 5-15x). The
mismatch becomes material only for hyperinflationary or recently-pegged
currencies — none of which appear in FinRobot's current peer universes.
"""

from __future__ import annotations

import asyncio

import yfinance as yf
from yfinance.exceptions import YFException

from finrobot.engine.data.interface import ProviderError


_FX_TICKER_SUFFIX = "=X"


def _fx_ticker(from_ccy: str, to_ccy: str) -> str:
    """Build the yfinance FX ticker symbol for a currency pair.

    Examples: TWD→USD → ``TWDUSD=X``; EUR→USD → ``EURUSD=X``.
    """
    return f"{from_ccy.upper()}{to_ccy.upper()}{_FX_TICKER_SUFFIX}"


async def fetch_fx_rate_to_usd(from_ccy: str) -> float:
    """Fetch today's spot FX rate to convert ``from_ccy`` → USD.

    Returns 1.0 when ``from_ccy`` is already USD (no-op fast path). Raises
    :class:`ProviderError` when yfinance returns no usable quote — the
    caller is expected to drop the affected peer from the comp set rather
    than fall back to ``1.0`` and silently mis-state the multiples.
    """
    src = from_ccy.upper()
    if src == "USD":
        return 1.0

    ticker = _fx_ticker(src, "USD")

    def _get_spot() -> float | None:
        t = yf.Ticker(ticker)
        try:
            price = t.fast_info.last_price
        except (YFException, AttributeError, KeyError):
            return None
        if price is None:
            return None
        try:
            value = float(price)
        except (TypeError, ValueError):
            return None
        if value <= 0 or value != value:  # NaN guard
            return None
        return value

    rate = await asyncio.to_thread(_get_spot)
    if rate is None:
        raise ProviderError(
            f"yfinance returned no spot FX quote for {ticker} "
            f"(needed to normalize {src} financials to USD)"
        )
    return rate
