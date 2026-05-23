import asyncio
import weakref
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import aiosqlite
from pydantic import BaseModel

from finagent.engine.data.interface import DataResult
from finagent.engine.data.types import DataType

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS cache (
    data_type TEXT NOT NULL,
    ticker    TEXT NOT NULL,
    data      TEXT NOT NULL,
    cached_at TIMESTAMP NOT NULL,
    PRIMARY KEY (data_type, ticker)
)
"""

# TTL (in seconds) per data type. Different financial data types have
# fundamentally different freshness requirements:
# - price: changes every trading second, 15 min is a reasonable compromise
# - news: semi-fresh, 30 min keeps context relevant without hammering APIs
# - financials: quarterly updates, 24h is plenty fresh
# - earnings_transcript: transcripts are immutable once published
# - default: 1 hour for anything not explicitly listed
_TTL_SECONDS: dict[str, int] = {
    DataType.PRICE: 900,  # 15 minutes
    DataType.NEWS: 1800,  # 30 minutes
    DataType.FINANCIALS: 86400,  # 24 hours
    DataType.EARNINGS: 86400,  # 24 hours (quarterly data)
    DataType.EARNINGS_TRANSCRIPT: 604800,  # 7 days
    DataType.FILINGS: 604800,  # 7 days (SEC filings don't change)
    DataType.RAG_10K: 604800,  # 7 days
    DataType.PROFILE: 86400,  # 24 hours
    # Route-level cache for yfinance-only deep financial data. Update cadence
    # is quarterly so a 24h freshness window is ample.
    DataType.HISTORICAL: 86400,
    DataType.QUARTERLY: 86400,
    # v5 §6.6 historical valuation bands — recomputing them is expensive
    # (price + financial fan-out) but underlying numbers move ≤ daily, so a
    # 12h TTL hits the sweet spot between freshness and load.
    DataType.HISTORICAL_BANDS: 43200,
}
_DEFAULT_TTL_SECONDS: int = 3600  # 1 hour


def _get_ttl_seconds(data_type: str | DataType) -> int:
    """Return the TTL in seconds for a given data type."""
    return _TTL_SECONDS.get(str(data_type), _DEFAULT_TTL_SECONDS)


class CachedResult(BaseModel):
    data: DataResult
    is_stale: bool
    cached_at: datetime


class DataCache:
    def __init__(self, db_path: str = "") -> None:
        if not db_path:
            from finagent.paths import default_data_cache_db_path

            db_path = default_data_cache_db_path()
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._conn_lock = asyncio.Lock()

    async def _ensure_connection(self) -> aiosqlite.Connection:
        """Lazily create connection and table on first use, then reuse.

        Hot path skips the lock entirely once the connection exists; the
        lock only guards the first-init race (TOCTOU when multiple
        coroutines call this simultaneously before the connection is set).
        WAL mode is enabled on first open so concurrent set() calls don't SQLITE_BUSY.
        """
        if self._conn is not None:
            return self._conn
        async with self._conn_lock:
            if self._conn is None:
                self._conn = await aiosqlite.connect(self._db_path)
                await self._conn.execute("PRAGMA journal_mode=WAL")
                await self._conn.execute("PRAGMA synchronous=NORMAL")
                await self._conn.execute(_CREATE_TABLE)
                await self._conn.commit()
        return self._conn

    async def get(
        self,
        data_type: str | DataType,
        ticker: str,
        max_age_hours: int | None = None,
    ) -> CachedResult | None:
        """Retrieve cached data, marking it stale if older than the TTL.

        TTL is determined automatically from the data_type (see ``_TTL_SECONDS``).
        The ``max_age_hours`` parameter is kept for backwards compatibility and
        test convenience: when provided it overrides the data-type TTL.
        """
        conn = await self._ensure_connection()
        async with conn.execute(
            "SELECT data, cached_at FROM cache WHERE data_type = ? AND ticker = ?",
            (data_type, ticker),
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:
            return None

        raw_data, cached_at_str = row
        cached_at = datetime.fromisoformat(cached_at_str)
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)

        now = datetime.now(tz=timezone.utc)
        age_seconds = (now - cached_at).total_seconds()

        if max_age_hours is not None:
            # Explicit override — convert hours to seconds for comparison
            is_stale = age_seconds > max_age_hours * 3600
        else:
            # Use per-data-type TTL
            ttl = _get_ttl_seconds(data_type)
            is_stale = age_seconds > ttl

        result = DataResult.model_validate_json(raw_data)
        return CachedResult(data=result, is_stale=is_stale, cached_at=cached_at)

    async def set(self, data_type: str | DataType, ticker: str, result: DataResult) -> None:
        cached_at = datetime.now(tz=timezone.utc).isoformat()
        conn = await self._ensure_connection()
        await conn.execute(
            """
            INSERT INTO cache (data_type, ticker, data, cached_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(data_type, ticker) DO UPDATE SET
                data = excluded.data,
                cached_at = excluded.cached_at
            """,
            (data_type, ticker, result.model_dump_json(), cached_at),
        )
        await conn.commit()

    async def clear(self, ticker: str | None = None) -> None:
        conn = await self._ensure_connection()
        if ticker is None:
            await conn.execute("DELETE FROM cache")
        else:
            await conn.execute("DELETE FROM cache WHERE ticker = ?", (ticker,))
        await conn.commit()

    async def close(self) -> None:
        """Close the connection. Call during shutdown."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None


# Per-(data_type, cache_key) locks used to collapse concurrent cache-miss
# fetches into a single upstream call. Without this, N parallel requests for
# the same ticker on a cold cache each hit the provider — a classic
# cache-stampede that can rate-limit FMP/Finnhub or DoS yfinance.
#
# WeakValueDictionary so each lock GCs once no `async with` block still
# holds a strong reference. A plain dict[...] would leak one lock per
# (data_type, ticker) the server has ever seen — fine for a desktop user
# but unbounded under team-share deployments where each studied ticker
# would leave a permanent entry.
_INFLIGHT_LOCKS: weakref.WeakValueDictionary[tuple[str, str], asyncio.Lock] = (
    weakref.WeakValueDictionary()
)
_INFLIGHT_LOCKS_GUARD = asyncio.Lock()


async def _get_inflight_lock(data_type: str | DataType, cache_key: str) -> asyncio.Lock:
    """Return the asyncio.Lock guarding fetches for this (data_type, key).

    The caller MUST keep a strong reference to the returned lock for the
    whole `async with` block (the normal idiom does this via a local var
    + `async with lock:`). Without that, the WeakValueDictionary would
    drop the entry mid-fetch, breaking the stampede guarantee — but no
    consumer pattern in this codebase violates that.
    """
    composite_key = (str(data_type), cache_key)
    # Fast path: lock already exists and is still referenced somewhere.
    lock = _INFLIGHT_LOCKS.get(composite_key)
    if lock is not None:
        return lock
    # Slow path: create it. The guard lock prevents two coroutines from
    # creating duplicate locks for the same key in the same tick.
    async with _INFLIGHT_LOCKS_GUARD:
        lock = _INFLIGHT_LOCKS.get(composite_key)
        if lock is None:
            lock = asyncio.Lock()
            _INFLIGHT_LOCKS[composite_key] = lock
        return lock


async def cached_fetch(
    cache: DataCache,
    data_type: DataType,
    ticker: str,
    fetcher: Callable[[], Awaitable[dict[str, Any]]],
    cache_key_suffix: str = "",
) -> dict[str, Any]:
    """Generic cache wrapper for raw-dict endpoints not backed by a Provider.

    Routes like /price, /historical, /quarterly call yfinance directly (no
    provider chain), but still deserve the same SQLite cache as Provider-backed
    types. This helper checks cache, calls the fetcher on miss, then writes
    the result back wrapped in a DataResult envelope.

    The ``cache_key_suffix`` lets callers vary the cache slot per parameter
    combination (e.g. ``f":{period}"`` for /price where 1y vs 5d are different
    payloads).

    Returns the raw dict — callers don't need to unwrap DataResult.

    Stampede protection: concurrent requests for the same (data_type, key)
    are serialized on a per-key asyncio.Lock. The first caller fetches; the
    rest wait, then read the populated cache.
    """
    cache_key = f"{ticker}{cache_key_suffix}"

    cached = await cache.get(data_type, cache_key)
    if cached is not None and not cached.is_stale:
        return cached.data.data

    lock = await _get_inflight_lock(data_type, cache_key)
    async with lock:
        # Re-check after acquiring the lock: a sibling request may have just
        # populated the cache while we were waiting.
        cached = await cache.get(data_type, cache_key)
        if cached is not None and not cached.is_stale:
            return cached.data.data

        data = await fetcher()

        envelope = DataResult(
            data=data,
            provider="route-direct",
            ticker=cache_key,
            data_type=data_type,
            timestamp=datetime.now(tz=timezone.utc),
            warnings=list(data.get("warnings", [])) if isinstance(data, dict) else [],
        )
        await cache.set(data_type, cache_key, envelope)
        return data
