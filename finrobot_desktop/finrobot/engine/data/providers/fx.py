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
import logging
import time

import httpx
import yfinance as yf
from yfinance.exceptions import YFException

from finrobot.engine.data.interface import ProviderError

logger = logging.getLogger(__name__)

_FX_TICKER_SUFFIX = "=X"

# In-process spot-FX cache. A comps fan-out converts many same-currency peers
# (10 EUR-reporting peers → one EUR→USD spot), and the FX read shares Yahoo's
# rate-limit budget — re-pulling it per peer is exactly what triggers a 429 storm
# (the very failure mode that strands foreign-listed peers). Spot moves far less
# than the ~2-3% MVP normalization noise floor intraday, so a short TTL is safe.
# Module-global because callers hit fetch_fx_rate_to_usd directly from many sites
# (extractor per-peer, ddm, valuation route, DataLayer) — no single instance to
# hang an instance cache on. Only SUCCESSES are cached (a transient 429 must not
# poison the slot). clear_fx_cache() resets it for test isolation.
_FX_CACHE_TTL_SECONDS = 900.0  # 15 min
_fx_cache: dict[str, tuple[float, float]] = {}  # ccy -> (rate_to_usd, expires_at_monotonic)
_fx_locks: dict[str, asyncio.Lock] = {}
_fx_locks_guard = asyncio.Lock()


def clear_fx_cache() -> None:
    """Reset the in-process FX cache + locks. An autouse conftest fixture calls
    this around every test so a cached rate (or a lock bound to a finished test's
    event loop) never leaks across cases."""
    _fx_cache.clear()
    _fx_locks.clear()


async def _fx_lock(ccy: str) -> asyncio.Lock:
    """Per-currency lock so concurrent identical FX misses (a peer fan-out hitting
    the cold cache at once) collapse onto a single upstream fetch."""
    lock = _fx_locks.get(ccy)
    if lock is not None:
        return lock
    async with _fx_locks_guard:
        lock = _fx_locks.get(ccy)
        if lock is None:
            lock = asyncio.Lock()
            _fx_locks[ccy] = lock
        return lock


# FMP forex fallback. yfinance is the primary FX source, but it shares Yahoo's
# rate-limit budget with every equity/peer quote — under a 429 storm the FX read
# is exactly what fails, silently dropping foreign-listed peers (observed: BIDU
# dropped on "no spot FX quote for CNYUSD=X" while FMP happily served its CNY
# financials on an independent budget). FMP quotes the same spot via
# /quote?symbol=PAIR, so it recovers the peer instead of losing it. Only
# consulted when a key is threaded through AND yfinance has already failed.
# Stable host: /api/v3 is closed to accounts registered after 2025-08-31
# (403 "Legacy Endpoint" even with a valid key).
_FMP_BASE_URL = "https://financialmodelingprep.com/stable"
_FMP_FX_TIMEOUT = 10.0


def _fx_ticker(from_ccy: str, to_ccy: str) -> str:
    """Build the yfinance FX ticker symbol for a currency pair.

    Examples: TWD→USD → ``TWDUSD=X``; EUR→USD → ``EURUSD=X``.
    """
    return f"{from_ccy.upper()}{to_ccy.upper()}{_FX_TICKER_SUFFIX}"


def _yf_spot(ticker: str) -> float | None:
    """Today's spot from yfinance ``fast_info.last_price``; None on any failure.

    Deliberately NOT typed for rate limits: a Yahoo 429 (YFRateLimitError ⊂
    YFException) collapses to None like any other failure so the caller falls
    through to the FMP leg. The aggregate raise in
    ``_fetch_fx_rate_to_usd_uncached`` covers BOTH legs and cannot attribute a
    single upstream status, and no FX consumer classifies via
    ``is_rate_limit_error`` (FX errors never enter the provider-chain /
    quote-batch paths), so a typed error here would have no consumer.
    """
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


async def _fmp_quote_price(client: httpx.AsyncClient, pair: str, api_key: str) -> float | None:
    """FMP spot ``price`` for a forex ``pair`` (e.g. ``USDCNY``); None on failure."""
    try:
        resp = await client.get(
            f"{_FMP_BASE_URL}/quote", params={"symbol": pair, "apikey": api_key}
        )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return None
    price = data[0].get("price")
    if price is None:
        return None
    try:
        value = float(price)
    except (TypeError, ValueError):
        return None
    if value <= 0 or value != value:  # NaN guard
        return None
    return value


async def _fmp_fx_rate_to_usd(from_ccy: str, api_key: str) -> float | None:
    """FMP fallback for ``from_ccy`` → USD spot. None on any failure.

    Tries the direct pair ``{FROM}USD`` first (same FROM→USD convention as
    yfinance's ``CNYUSD=X``); on miss, falls back to ``USD{FROM}`` and inverts.
    FMP quotes majors both ways but only one direction for some minors, so we
    cover both rather than assume a single convention.
    """
    src = from_ccy.upper()
    async with httpx.AsyncClient(timeout=_FMP_FX_TIMEOUT) as client:
        direct = await _fmp_quote_price(client, f"{src}USD", api_key)
        if direct is not None:
            return direct
        inverse = await _fmp_quote_price(client, f"USD{src}", api_key)
        if inverse is not None and inverse > 0:
            return 1.0 / inverse
    return None


async def fetch_fx_rate_to_usd(from_ccy: str, *, fmp_api_key: str | None = None) -> float:
    """Fetch today's spot FX rate to convert ``from_ccy`` → USD.

    Returns 1.0 when ``from_ccy`` is already USD (no-op fast path). yfinance is
    tried first; on failure (commonly a shared-budget 429 storm) FMP is consulted
    when ``fmp_api_key`` is supplied. Raises :class:`ProviderError` only when BOTH
    sources return no usable quote — the caller is expected to drop the affected
    peer from the comp set rather than fall back to ``1.0`` and silently mis-state
    the multiples.

    Backed by a short-TTL in-process cache + per-currency single-flight (see the
    module-level cache notes), so a comps fan-out reads each currency's spot once
    instead of once per peer. Only successful rates are cached; a failure re-tries
    on the next call.
    """
    src = from_ccy.upper()
    if src == "USD":
        return 1.0

    hit = _fx_cache.get(src)
    if hit is not None and hit[1] > time.monotonic():
        return hit[0]

    lock = await _fx_lock(src)
    async with lock:
        # Re-check: a sibling fetch may have populated the slot while we queued.
        hit = _fx_cache.get(src)
        if hit is not None and hit[1] > time.monotonic():
            return hit[0]
        rate = await _fetch_fx_rate_to_usd_uncached(src, fmp_api_key)
        _fx_cache[src] = (rate, time.monotonic() + _FX_CACHE_TTL_SECONDS)
        return rate


async def _fetch_fx_rate_to_usd_uncached(src: str, fmp_api_key: str | None) -> float:
    """yfinance spot → FMP fallback → raise. The network body of
    :func:`fetch_fx_rate_to_usd`, which wraps it in the TTL cache + single-flight.
    ``src`` is already upper-cased and known not to be USD."""
    ticker = _fx_ticker(src, "USD")
    rate = await asyncio.to_thread(_yf_spot, ticker)
    if rate is not None:
        return rate

    if fmp_api_key:
        fmp_rate = await _fmp_fx_rate_to_usd(src, fmp_api_key)
        if fmp_rate is not None:
            logger.info(
                "FX %s→USD via FMP fallback (yfinance %s unavailable): %.6f", src, ticker, fmp_rate
            )
            return fmp_rate

    raise ProviderError(
        f"No spot FX quote for {src}→USD from yfinance ({ticker})"
        + (" or FMP" if fmp_api_key else "")
        + f" — needed to normalize {src} financials to USD"
    )
