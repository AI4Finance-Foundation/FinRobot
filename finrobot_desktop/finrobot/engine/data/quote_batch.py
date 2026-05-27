"""Batched live-quote helpers.

Two entry points:
  fetch_quotes_batch(tickers)        — synchronous, NO cache, direct yfinance.
                                        Kept for legacy callers wrapped in
                                        asyncio.to_thread; do not introduce new
                                        usage.
  fetch_quotes_batch_cached(tickers) — async, two-layer cached (in-memory +
                                        SQLite). Preferred entry point for
                                        routes and pipelines.

The async path consults a process-wide :class:`QuoteCache` singleton with a
60s TTL. Per-ticker failures (delisted, fast_info miss) get cached as
``None`` so we don't beat yfinance on every refresh for a dead symbol.

Leaf-layer rules: no imports from routes / pipelines / agents.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

from finrobot.engine.data.quote_cache import QuoteCache

logger = logging.getLogger(__name__)


_GLOBAL_QUOTE_CACHE: QuoteCache | None = None


def reset_quote_cache_singleton() -> None:
    """Drop the process-wide QuoteCache reference. Test-only helper.

    Lets tests rebind ``QUOTES_DB`` (e.g. via ``monkeypatch.setenv('HOME', ...)``)
    and start with a clean L1. Note: this does NOT close the underlying
    aiosqlite connection — call ``close_quote_cache_singleton`` first (from an
    async context) if the existing singleton owns a live worker thread, or
    rely on the conftest autouse close fixture.
    """
    global _GLOBAL_QUOTE_CACHE
    _GLOBAL_QUOTE_CACHE = None


async def close_quote_cache_singleton() -> None:
    """Close the process-wide QuoteCache aiosqlite connection.

    Called from the server lifespan on shutdown so the aiosqlite worker
    thread stops cleanly and WAL gets checkpointed instead of racing the
    asyncio loop teardown.
    """
    global _GLOBAL_QUOTE_CACHE
    if _GLOBAL_QUOTE_CACHE is not None:
        await _GLOBAL_QUOTE_CACHE.close()
        _GLOBAL_QUOTE_CACHE = None


def _get_singleton() -> QuoteCache:
    global _GLOBAL_QUOTE_CACHE
    if _GLOBAL_QUOTE_CACHE is None:
        _GLOBAL_QUOTE_CACHE = QuoteCache()
    return _GLOBAL_QUOTE_CACHE


def _fetch_via_yfinance(tickers: list[str]) -> dict[str, float | None]:
    """Synchronous yfinance call — wrap in :func:`asyncio.to_thread` from async."""
    if not tickers:
        return {}
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance unavailable — returning all-None quote batch")
        return dict.fromkeys(tickers)

    try:
        container = yf.Tickers(" ".join(tickers))
    except (ValueError, OSError) as exc:
        logger.warning("yf.Tickers init failed (%s) — falling back to per-ticker", exc)
        return {sym: _fetch_one(sym) for sym in tickers}

    out: dict[str, float | None] = {}
    for sym in tickers:
        try:
            t = container.tickers.get(sym) or container.tickers.get(sym.upper())
            if t is None:
                out[sym] = None
                continue
            info = t.fast_info
            price = getattr(info, "last_price", None)
            if price is None:
                price = getattr(info, "lastPrice", None)
            out[sym] = float(price) if price is not None else None
        except (AttributeError, ValueError, TypeError, OSError):
            logger.exception("Quote fetch failed for %s", sym)
            out[sym] = None
    return out


def _fetch_one(symbol: str) -> float | None:
    """Single-ticker fallback used when the batch init itself errors."""
    try:
        import yfinance as yf

        info = yf.Ticker(symbol).fast_info
        price = getattr(info, "last_price", None)
        if price is None:
            price = getattr(info, "lastPrice", None)
        return float(price) if price is not None else None
    except (ImportError, AttributeError, ValueError, TypeError, OSError):
        logger.exception("Single-ticker fallback failed for %s", symbol)
        return None


def fetch_quotes_batch(tickers: Iterable[str]) -> dict[str, float | None]:
    """Synchronous, no-cache. Direct yfinance.

    Kept for backwards compatibility with legacy callers that wrap this in
    ``asyncio.to_thread``. New code should prefer
    :func:`fetch_quotes_batch_cached`.
    """
    return _fetch_via_yfinance([t.strip().upper() for t in tickers if t and t.strip()])


async def fetch_quotes_batch_cached(
    tickers: Iterable[str],
) -> dict[str, float | None]:
    """Async, two-layer cached. Preferred entry point for routes + pipelines.

    L1 hit ⇒ pure dict lookup, sub-millisecond.
    L2 hit ⇒ single SELECT against indexed PK, ~1ms.
    Cold ⇒ one fan-out fetch shared across all callers within the 60s TTL.

    The cold path runs ``_fetch_one`` per ticker concurrently via
    ``asyncio.gather`` + ``asyncio.to_thread``. yfinance's ``fast_info`` is
    a blocking HTTPS round-trip per ticker; the legacy ``yf.Tickers(...)``
    batch container loops sequentially over them at ~1.5s/ticker, which
    dominated landing cold-start. Per-ticker concurrency drops a 4-ticker
    warmup from ~6s to ~2s (network-bound, not thread-overhead-bound).
    """
    syms = [t.strip().upper() for t in tickers if t and t.strip()]
    if not syms:
        return {}
    cache = _get_singleton()

    async def yf_async(missing: list[str]) -> dict[str, float | None]:
        results = await asyncio.gather(
            *(asyncio.to_thread(_fetch_one, sym) for sym in missing),
            return_exceptions=False,
        )
        return dict(zip(missing, results, strict=True))

    return await cache.get_batch(syms, fetcher=yf_async)
