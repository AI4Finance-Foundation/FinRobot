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
from finrobot.engine.data.quote_cache import QuoteCache, QuoteFetchRateLimited

if TYPE_CHECKING:
    from finrobot.engine.data.layer import DataLayer

__all__ = [
    "QuoteFetchRateLimited",  # re-exported so callers can still import from here
    "close_quote_cache_singleton",
    "fetch_quotes_batch_cached",
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


async def fetch_quotes_batch_cached(
    tickers: Iterable[str],
    data_layer: DataLayer,
) -> dict[str, float | None]:
    """Async, two-layer cached batch quotes via the DataLayer QUOTE path.

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

    async def fetcher(missing: list[str]) -> dict[str, float | None]:
        async def one(sym: str) -> float | None:
            try:
                result = await data_layer.fetch_quote(sym)
            except ProviderError as exc:
                if is_rate_limit_error(exc):
                    # Propagate so QuoteCache preserves stale + opens cooldown.
                    raise QuoteFetchRateLimited(
                        f"DataLayer QUOTE rate-limited for {sym}"
                    ) from exc
                logger.info("Quote fetch failed for %s: %s", sym, exc)
                return None
            data = result.data if isinstance(result.data, dict) else {}
            return _coerce_price(data.get("price"))

        results = await asyncio.gather(*(one(sym) for sym in missing))
        return dict(zip(missing, results, strict=True))

    return await cache.get_batch(syms, fetcher=fetcher)
