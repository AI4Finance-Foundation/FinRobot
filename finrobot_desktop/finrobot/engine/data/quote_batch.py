"""Batched live-quote helper.

Single entry point:
  fetch_quotes_batch_cached(tickers, data_layer) — async, two-layer cached
  (in-memory L1 + SQLite L2 via :class:`QuoteCache`). Routes and the lifespan
  warmup call it with the shared ``DataLayer``.

The cold path fans out per missing ticker through ``DataLayer.fetch_quote``
(provider chain FMP → yfinance) concurrently via ``asyncio.gather``. A
rate-limit ``ProviderError`` (Yahoo 429 — only reached when FMP is unavailable)
maps to :class:`QuoteFetchRateLimited` so ``QuoteCache`` preserves the previous
(stale) value and opens its cooldown window rather than tomb-stoning every
ticker with ``None`` for the TTL. Other per-ticker failures (delisted,
not-found) surface as ``None`` (delisting tombstone).

All yfinance access for quotes now goes through the DataLayer (门一) — this
module owns no provider/yfinance knowledge. Leaf-layer rules: no imports from
routes / pipelines / agents.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING

from finrobot.engine.data.interface import ProviderError, is_rate_limit_error
from finrobot.engine.data.quote_cache import Quote, QuoteCache, QuoteFetchRateLimited

if TYPE_CHECKING:
    from finrobot.engine.data.layer import DataLayer

__all__ = [
    "Quote",  # re-exported: the carried (price, currency) value
    "QuoteFetchRateLimited",  # re-exported so callers can still import from here
    "close_quote_cache_singleton",
    "fetch_quotes_batch_cached",
    "fetch_quotes_cache_only",
    "reset_quote_cache_singleton",
]

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


def _coerce_price(value: object) -> float | None:
    try:
        return float(value) if value is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _quote_from_result(data: object) -> Quote:
    """Build a :class:`Quote` from a QUOTE DataResult's ``data`` dict.

    Carries both the price and the ``quote_currency`` the QUOTE provider stamped
    (yfinance ``fast_info.currency`` / FMP ``/profile.currency``) — so a foreign
    listing's price travels WITH its currency through the cache, and the signal
    consumer never has to recover the currency from a second, independently-cached
    source. ``currency`` normalised to upper-case, or None when absent."""
    d = data if isinstance(data, dict) else {}
    ccy = d.get("quote_currency")
    return Quote(
        price=_coerce_price(d.get("price")),
        currency=ccy.upper() if isinstance(ccy, str) and ccy else None,
    )


async def fetch_quotes_batch_cached(
    tickers: Iterable[str],
    data_layer: DataLayer,
) -> dict[str, Quote | None]:
    """Async, two-layer cached batch quotes via the DataLayer QUOTE path.

    Returns one :class:`Quote` (price + the currency that price is in) per ticker,
    or None for a cold/failed miss. The currency travels with the price (its own
    source: the QUOTE provider's currency stamp) so the signal consumer converts to
    USD or abstains without a second currency lookup.

    L1 hit ⇒ pure dict lookup, sub-millisecond.
    L2 hit ⇒ single SELECT against indexed PK, ~1ms.
    Cold ⇒ one fan-out (per-ticker ``DataLayer.fetch_quote`` concurrently)
    shared across all callers within the 60s TTL.

    A rate-limit ``ProviderError`` from the provider chain maps to
    ``QuoteFetchRateLimited`` so ``QuoteCache`` keeps the previous value and
    opens its cooldown — one Yahoo 429 burst no longer takes the dashboard cold
    for the full TTL. With an FMP key configured, quotes resolve from FMP and
    yfinance (and its 429s) are never reached.
    """
    syms = [t.strip().upper() for t in tickers if t and t.strip()]
    if not syms:
        return {}
    cache = _get_singleton()

    async def fetcher(missing: list[str]) -> dict[str, Quote | None]:
        async def one(sym: str) -> Quote | None:
            try:
                result = await data_layer.fetch_quote(sym)
            except ProviderError as exc:
                if is_rate_limit_error(exc):
                    # Propagate so QuoteCache preserves stale + opens cooldown.
                    raise QuoteFetchRateLimited(f"DataLayer QUOTE rate-limited for {sym}") from exc
                logger.info("Quote fetch failed for %s: %s", sym, exc)
                return None
            return _quote_from_result(result.data)

        results = await asyncio.gather(*(one(sym) for sym in missing))
        return dict(zip(missing, results, strict=True))

    return await cache.get_batch(syms, fetcher=fetcher)


async def fetch_quotes_cache_only(tickers: Iterable[str]) -> dict[str, Quote | None]:
    """Cache-only batch quotes — NEVER touches the provider chain.

    L1/L2 *fresh* hits return their :class:`Quote` (price + currency); every miss
    (cold or stale) comes back ``None`` because the fetcher is a no-op. Returns
    sub-millisecond
    to ~1ms regardless of cache state — no FMP/yfinance round-trip, no 8s
    warmup tail.

    The landing recent-research strip uses this so its DB-backed cards render
    instantly: warm tickers light their signal lamp immediately, cold ones
    come back ``None`` (lamp pending) and fill on the next refetch once the
    lifespan QuoteCache warmup has populated the cache. Live prices are a
    progressive enhancement on that strip, never a render dependency — unlike
    the hit-rate banner, whose bucket math genuinely needs warm quotes and so
    still calls :func:`fetch_quotes_batch_cached`.

    Backed by :meth:`QuoteCache.peek_batch`, a pure read: a cold/stale miss is
    NOT written back. The earlier no-op-fetcher implementation borrowed
    ``get_batch``'s write path, tomb-stoning misses as fresh ``None`` in L1+L2 —
    that poisoned the stale-while-revalidate price and starved the hit-rate
    banner's later real fetch (W2 探针毒化).
    """
    syms = [t.strip().upper() for t in tickers if t and t.strip()]
    if not syms:
        return {}
    return await _get_singleton().peek_batch(syms)
