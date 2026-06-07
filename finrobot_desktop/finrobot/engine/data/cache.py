import asyncio
import logging
import weakref
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite
from pydantic import BaseModel

from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.normalize.contracts import CANONICAL_CONTRACT_VERSION
from finrobot.engine.data.types import DataType
from finrobot.paths import configure_connection

logger = logging.getLogger(__name__)

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
# Alias map for backward-compat DataType keys. The cache layer normalises
# every read/write through ``_normalize_data_type`` so old code passing
# ``DataType.FILINGS`` shares cache slots with new code passing
# ``DataType.FILINGS_10K`` — no 60s-TTL double-fetch from SEC across the
# deprecation window. Sealed by tests/unit/test_datatype_alias.py.
_DATA_TYPE_ALIASES: dict[str, str] = {
    DataType.FILINGS.value: DataType.FILINGS_10K.value,
}


def _normalize_data_type(data_type: str | DataType) -> str:
    raw = str(data_type)
    return _DATA_TYPE_ALIASES.get(raw, raw)


def canonical_key(data_type: str | DataType) -> str:
    """Cache slot for a normalized (canonical) payload.

    Isolated from the raw provider slot (same table, different ``data_type``
    key) so raw and canonical entries for one ticker never collide, and
    version-tagged so a ``CANONICAL_CONTRACT_VERSION`` bump auto-invalidates
    stale canonical entries with no migration (ADR-0006 decision C1). Defined
    here, once — callers must never hand-assemble the suffix.
    """
    return f"{_normalize_data_type(data_type)}:canonical:v{CANONICAL_CONTRACT_VERSION}"


# Raw provider-slot format versions. Bump when a provider's cached RAW payload
# SHAPE changes incompatibly, so old entries are ignored (treated as a miss)
# and refetched, instead of feeding a stale format into the compute layer.
# Without this a long-TTL type silently serves the old shape until expiry.
#   proxy_statement v2 — 2026-06-02: the DEF 14A text slice was re-anchored on
#   the real Summary Compensation Table; pre-v2 slices miss the SCT + pay-ratio
#   for large issuers, so the comp parser can't recover from them (7-day TTL).
#   peer_candidates v2 — 2026-06-05: candidate profiles were added so the
#   deterministic peer screen can reject value-chain partners (foundry /
#   equipment) before comps math consumes them.
#   price v2 — 2026-06-07: canonical PRICE now relies on the validated
#   fetch_price() path. Old raw PRICE rows may have been written by bare fetch()
#   without cross-source quote validation, so they must not seed the canonical
#   slot.
_RAW_SLOT_VERSION: dict[str, int] = {
    DataType.PRICE.value: 2,
    DataType.PROXY_STATEMENT.value: 2,
    DataType.PEER_CANDIDATES.value: 2,
}


def raw_slot_key(data_type: str | DataType) -> str:
    """Cache slot for RAW provider data, version-tagged per ``_RAW_SLOT_VERSION``.

    Unversioned types return their bare normalized key (back-compat); a bumped
    type returns ``<type>:vN`` so old entries become unreachable. TTL lookup
    still uses the BASE data_type, so freshness budgets are unaffected.
    """
    base = _normalize_data_type(data_type)
    version = _RAW_SLOT_VERSION.get(base)
    return f"{base}:v{version}" if version else base


_TTL_SECONDS: dict[str, int] = {
    DataType.PRICE: 900,  # 15 minutes
    DataType.QUOTE: 60,  # 1 minute — aligns with the QuoteCache batch TTL
    DataType.NEWS: 1800,  # 30 minutes
    # Catalysts derive from NEWS via an LLM classify pass — align the TTL with
    # NEWS (30 min) so the calendar refreshes on the same cadence as its source.
    DataType.CATALYST: 1800,  # 30 minutes
    DataType.FINANCIALS: 86400,  # 24 hours
    DataType.EARNINGS: 86400,  # 24 hours (quarterly data)
    DataType.EARNINGS_TRANSCRIPT: 604800,  # 7 days
    # FILINGS_10K is canonical; FILINGS aliases to it via _DATA_TYPE_ALIASES
    DataType.FILINGS_10K: 604800,  # 7 days (SEC filings don't change)
    DataType.FILINGS_10Q: 86400,  # 24 hours (quarterly cadence)
    DataType.FILINGS_8K: 1800,  # 30 min (8-K are time-sensitive)
    DataType.RAG_10K: 604800,  # 7 days
    DataType.PROFILE: 86400,  # 24 hours
    # XBRL: standardized financial concepts; quarterly refresh
    DataType.XBRL_FACTS: 86400,
    # Form 4: insider trades file within 48h; 30 min lets fresh trades surface
    DataType.INSIDER_TRADES: 1800,
    # 13F: filed within 45 days of quarter end; once cached locally, refresh
    # is the background job's responsibility — route-level TTL is generous
    DataType.INSTITUTIONAL_HOLDINGS: 86400,
    # DEF 14A: annual; 7 days
    DataType.PROXY_STATEMENT: 604800,
    # Route-level cache for yfinance-only deep financial data. Update cadence
    # is quarterly so a 24h freshness window is ample.
    DataType.HISTORICAL: 86400,
    DataType.QUARTERLY: 86400,
    # Arbitrary-range daily OHLCV: a historical window's bars are effectively
    # immutable (only a future split re-adjusts them, rare), so a 24h TTL is
    # generous — the (ticker,start,end,interval) cache key already isolates ranges.
    DataType.PRICE_RANGE: 86400,
    # v5 §6.6 historical valuation bands — recomputing them is expensive
    # (price + financial fan-out) but underlying numbers move ≤ daily, so a
    # 12h TTL hits the sweet spot between freshness and load.
    DataType.HISTORICAL_BANDS: 43200,
    # Analyst consensus estimates revise over days/weeks, not intraday — 24h
    # matches FINANCIALS and keeps the forward-multiple fetch cheap.
    DataType.FORWARD_ESTIMATES: 86400,
    # Candidate quotes move intraday and P/E gates depend on them. Profiles are
    # slower-moving, but the mixed payload should refresh on the quote cadence.
    DataType.PEER_CANDIDATES: 3600,
}
_DEFAULT_TTL_SECONDS: int = 3600  # 1 hour

# Coarse absolute age (days) past which a cache row is physically deleted by
# evict_expired(). This is NOT the freshness TTL — reads already mark anything
# past its per-type TTL as stale and refetch. This is the housekeeping cutoff
# that stops the table growing unbounded as research fans out across hundreds
# of tickers × data types × raw/canonical/period slots (BUG-049). It is set
# well above the largest per-type TTL (7 days for SEC filings / transcripts) so
# evict_expired never reaps a row a read would still consider fresh — the
# raw/canonical/period suffixes baked into the data_type column make exact
# per-type TTL reverse-lookup messy, so a single conservative absolute cutoff
# is the robust choice.
_EVICT_AFTER_DAYS: int = 30


def _get_ttl_seconds(data_type: str | DataType) -> int:  # noqa: D401
    data_type = _normalize_data_type(data_type)  # FILINGS → FILINGS_10K etc.
    """Return the TTL in seconds for a given data type."""
    return _TTL_SECONDS.get(str(data_type), _DEFAULT_TTL_SECONDS)


class CachedResult(BaseModel):
    data: DataResult
    is_stale: bool
    cached_at: datetime


class CachedCanonical(BaseModel):
    """A canonical-slot cache hit. ``payload_json`` is the raw
    ``Normalized*.model_dump_json()`` string — the DataLayer validates it into
    the right model, keeping the cache layer model-agnostic."""

    payload_json: str
    is_stale: bool
    cached_at: datetime


class DataCache:
    def __init__(self, db_path: str = "") -> None:
        if not db_path:
            from finrobot.paths import default_data_cache_db_path

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
                await configure_connection(self._conn)
                await self._conn.execute(_CREATE_TABLE)
                await self._conn.commit()
        return self._conn

    async def _get_slot(
        self,
        slot_key: str,
        ticker: str,
        ttl_data_type: str | DataType,
        max_age_hours: int | None,
    ) -> tuple[str, datetime, bool] | None:
        """Fetch one cache row by exact slot key; compute staleness.

        ``slot_key`` is the literal ``data_type`` column value (raw or
        canonical). ``ttl_data_type`` is the base type used for the TTL lookup
        (a canonical slot still ages on its base type's freshness budget).
        Returns ``(payload_json, cached_at, is_stale)`` or None on miss.
        """
        conn = await self._ensure_connection()
        async with conn.execute(
            "SELECT data, cached_at FROM cache WHERE data_type = ? AND ticker = ?",
            (slot_key, ticker),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        payload_json, cached_at_str = row
        cached_at = datetime.fromisoformat(cached_at_str)
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)
        age_seconds = (datetime.now(tz=timezone.utc) - cached_at).total_seconds()
        if max_age_hours is not None:
            is_stale = age_seconds > max_age_hours * 3600
        else:
            is_stale = age_seconds > _get_ttl_seconds(ttl_data_type)
        return payload_json, cached_at, is_stale

    async def _set_slot(self, slot_key: str, ticker: str, payload_json: str) -> None:
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
            (slot_key, ticker, payload_json, cached_at),
        )
        await conn.commit()

    async def get(
        self,
        data_type: str | DataType,
        ticker: str,
        max_age_hours: int | None = None,
    ) -> CachedResult | None:
        """Retrieve cached RAW provider data, marking it stale past the TTL.

        TTL is determined automatically from the data_type (see ``_TTL_SECONDS``).
        The ``max_age_hours`` parameter is kept for backwards compatibility and
        test convenience: when provided it overrides the data-type TTL.
        """
        slot = await self._get_slot(raw_slot_key(data_type), ticker, data_type, max_age_hours)
        if slot is None:
            return None
        payload_json, cached_at, is_stale = slot
        return CachedResult(
            data=DataResult.model_validate_json(payload_json),
            is_stale=is_stale,
            cached_at=cached_at,
        )

    async def set(self, data_type: str | DataType, ticker: str, result: DataResult) -> None:
        await self._set_slot(raw_slot_key(data_type), ticker, result.model_dump_json())

    async def get_canonical(
        self,
        data_type: str | DataType,
        ticker: str,
        max_age_hours: int | None = None,
    ) -> CachedCanonical | None:
        """Retrieve a normalized payload from the versioned canonical slot.

        Staleness uses the BASE data_type's TTL (the canonical key itself isn't
        in ``_TTL_SECONDS``). Returns the JSON string; the DataLayer validates
        it into ``NormalizedPrice`` / ``NormalizedFinancials``.
        """
        slot = await self._get_slot(canonical_key(data_type), ticker, data_type, max_age_hours)
        if slot is None:
            return None
        payload_json, cached_at, is_stale = slot
        return CachedCanonical(payload_json=payload_json, is_stale=is_stale, cached_at=cached_at)

    async def set_canonical(
        self, data_type: str | DataType, ticker: str, payload_json: str
    ) -> None:
        """Store a normalized payload (``Normalized*.model_dump_json()``) in the
        versioned canonical slot, isolated from the raw slot."""
        await self._set_slot(canonical_key(data_type), ticker, payload_json)

    async def clear(self, ticker: str | None = None) -> None:
        conn = await self._ensure_connection()
        if ticker is None:
            await conn.execute("DELETE FROM cache")
        else:
            await conn.execute("DELETE FROM cache WHERE ticker = ?", (ticker,))
        await conn.commit()

    async def evict_expired(self, *, max_age_days: int = _EVICT_AFTER_DAYS) -> int:
        """Physically delete cache rows older than ``max_age_days``; reclaim file space.

        The TTL machinery only marks rows stale at read time — it never deletes,
        so the table grows monotonically with every (ticker × data_type ×
        raw/canonical × period) slot ever fetched (BUG-049). This is the
        housekeeping pass: a single coarse absolute-age DELETE (no per-type TTL
        reverse-lookup, which the raw/canonical/period suffixes would make
        fragile) followed by a VACUUM so the freed pages shrink the file rather
        than just becoming reusable slack.

        ``max_age_days`` is intentionally far above the largest per-type TTL, so
        a row this evicts is guaranteed already stale to every reader.

        Returns the number of rows deleted.
        """
        cutoff_iso = (datetime.now(tz=timezone.utc) - timedelta(days=max_age_days)).isoformat()
        conn = await self._ensure_connection()
        cur = await conn.execute("DELETE FROM cache WHERE cached_at < ?", (cutoff_iso,))
        deleted = cur.rowcount
        await conn.commit()
        if deleted:
            # Reclaim the freed pages so the .db file actually shrinks rather
            # than leaving them as reusable slack. The DB is opened with the
            # default auto_vacuum=NONE (see paths.configure_connection), so
            # incremental_vacuum is a no-op — a full VACUUM is the only thing
            # that returns space to the filesystem. It rewrites the file, but
            # this runs as a periodic background pass only when rows were
            # actually deleted, so the cost is amortised and off the hot path.
            # Best-effort: a failed reclaim must not turn a successful eviction
            # into an error (e.g. VACUUM cannot run inside a transaction or
            # with an open cursor on some platforms).
            try:
                await conn.execute("VACUUM")
                await conn.commit()
            except aiosqlite.Error:
                logger.warning("data_cache VACUUM after eviction failed — non-fatal")
        return deleted

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
