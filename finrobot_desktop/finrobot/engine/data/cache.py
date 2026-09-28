import asyncio
import logging
import sqlite3
import weakref
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite
from pydantic import BaseModel, ValidationError

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


def canonical_key(data_type: str | DataType, provider: str | None = None) -> str:
    """Cache slot for a normalized (canonical) payload.

    Isolated from the raw provider slot (same table, different ``data_type``
    key) so raw and canonical entries for one ticker never collide, and
    version-tagged so a ``CANONICAL_CONTRACT_VERSION`` bump auto-invalidates
    stale canonical entries with no migration (ADR-0006 decision C1). Defined
    here, once — callers must never hand-assemble the suffix.

    ``provider`` folds the WINNING provider's identity into the slot
    (``…:canonical:v6:provider=<name>``) so a silent provider swap — FMP
    rate-limited → yfinance fallback wins that run — can no longer overwrite a
    DIFFERENT-caliber snapshot (period_basis / ttm_quarter_ends /
    reporting_currency) under one shared ``…/<ticker>`` slot, nor serve it to a
    later read that assumes the prior caliber. The DataLayer resolves it from the
    provider chain: the WRITE keys on the provider that actually won
    (``provenance.provider``), the READ on the preferred capable+healthy provider
    (the one that will win the next walk), so a stable single-provider steady
    state still hits its own slot and never thrashes. ``None`` → the bare,
    unqualified slot (back-compat for callers that don't track provider).
    """
    base = f"{_normalize_data_type(data_type)}:canonical:v{CANONICAL_CONTRACT_VERSION}"
    return f"{base}:provider={provider}" if provider else base


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
#   sentiment v2 — 2026-06-10: source_alignment switched from free English
#   phrases ('Wide divergence' …) to stable enum tokens; the route schema now
#   validates against the AlignmentToken Literal, so pre-token rows must miss.
#   forward_estimates v2 — 2026-06-11: FMP v3→stable migration renamed every
#   estimate figure (estimatedRevenueAvg → revenueAvg, estimatedEpsAvg →
#   epsAvg, …); the operator reads stable names only, so legacy-named cached
#   rows would parse as "no estimates" until TTL expiry.
#   financials v2 — 2026-06-14: the FMP financials payload now carries
#   book_value_per_share ((totalStockholdersEquity − preferred) ÷ shares); legacy
#   rows omit it, so a cyclical's comps_pb (book-value primary multiple) can never
#   revive from a cached row — old rows must miss + refetch. Pairs with the
#   CANONICAL_CONTRACT_VERSION v7 bump, which invalidates the normalized slot that
#   is read ahead of this raw slot.
#   financials v3 — 2026-06-22: the FMP financials payload now carries
#   dividend_per_share / payout_ratio / dividend_yield (/ratios-ttm) and
#   return_on_equity (/key-metrics-ttm). Legacy rows omit them, so the DDM seed
#   can never recover a dividend on an FMP-primary ticker (raises "no dividend").
#   Pairs with the CANONICAL_CONTRACT_VERSION v8 bump.
#   price v3 — 2026-07-01: full PRICE provider payloads now carry quote_currency.
#   Legacy PRICE rows omit it and would normalize to UNKNOWN (or, pre-v9, USD),
#   so they must miss and refetch instead of feeding mixed-currency comparisons.
#   financials v4 — 2026-07-06: the TTM aggregation window is now cadence-aware
#   (semi-annual filers sum 2 six-month rows, not 4). Legacy raw rows cached the
#   doubled sum-of-4 aggregate (UL revenue ~127B vs a ~50B year), so they must miss
#   and re-aggregate. Pairs with the CANONICAL_CONTRACT_VERSION v10 bump (the
#   normalized slot, read ahead of this raw slot).
#   peer_candidates v3 — 2026-07-07: the payload now carries a top-level ``active``
#   map (isActivelyTrading per candidate) so the peer screen can drop a delisted /
#   renamed listing (VMware VMW, old Block SQ). Legacy v2 rows have no ``active`` key,
#   so every candidate reads as UNKNOWN and a dead ticker keeps shipping until the 1h
#   TTL — they must miss + refetch to pick up the liveness signal. PEER_CANDIDATES is
#   a RAW-only type (never fetched via fetch_canonical, see layer._CANONICAL_TYPES), so
#   this is the ONLY layer to bump — CANONICAL_CONTRACT_VERSION must NOT move.
_RAW_SLOT_VERSION: dict[str, int] = {
    DataType.PRICE.value: 3,
    DataType.PROXY_STATEMENT.value: 2,
    DataType.PEER_CANDIDATES.value: 3,
    DataType.SENTIMENT.value: 2,
    DataType.FORWARD_ESTIMATES.value: 2,
    DataType.FINANCIALS.value: 4,
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
    DataType.DIVIDENDS: 604800,  # 7 days — declared dividend history changes at most quarterly
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
    # SOX-302 CEO cert: tracks the latest 10-Q/10-K, so a new quarter (or a
    # mid-quarter succession 8-K + next periodic filing) must surface within a
    # day — match the 10-Q cadence rather than the 7-day proxy window.
    DataType.CEO_CERTIFICATION: 86400,
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

        A row whose ``cached_at`` won't parse is corrupt: it is deleted and
        treated as a miss (self-heal, BUG: a raised ValueError here fires
        BEFORE the DataLayer's provider loop, so the slot would stay broken
        until the 30-day evict — see ``get`` for the payload-side twin).
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
        try:
            cached_at = datetime.fromisoformat(cached_at_str)
        except ValueError:
            logger.warning(
                "Corrupt cache row (unparseable cached_at) for %s/%s — deleting (self-heal)",
                slot_key,
                ticker,
            )
            await self._delete_slot(slot_key, ticker)
            return None
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)
        age_seconds = (datetime.now(tz=timezone.utc) - cached_at).total_seconds()
        if max_age_hours is not None:
            is_stale = age_seconds > max_age_hours * 3600
        else:
            is_stale = age_seconds > _get_ttl_seconds(ttl_data_type)
        return payload_json, cached_at, is_stale

    async def _delete_slot(self, slot_key: str, ticker: str) -> None:
        """Physically remove one cache row — the corrupt-row self-heal path.

        A row that no longer parses (broken JSON, schema drift without a
        version bump, mangled timestamp) must be deleted, not just skipped:
        every read happens BEFORE the DataLayer's provider loop, and a fresh
        fetch only overwrites the row on success — so a merely-skipped corrupt
        row would keep poisoning reads until the 30-day evict.
        """
        conn = await self._ensure_connection()
        try:
            await conn.execute(
                "DELETE FROM cache WHERE data_type = ? AND ticker = ?",
                (slot_key, ticker),
            )
            await conn.commit()
        except sqlite3.Error as exc:
            # Best-effort, same contract as _set_slot: this runs inside a READ's
            # corrupt-row self-heal, so a write failure (disk full, I/O error)
            # must not turn a cache read into a 500 — the read already treats the
            # row as a miss and refetches.
            logger.warning(
                "data_cache delete failed for %s/%s (non-fatal): %s", slot_key, ticker, exc
            )

    async def _set_slot(self, slot_key: str, ticker: str, payload_json: str) -> None:
        cached_at = datetime.now(tz=timezone.utc).isoformat()
        conn = await self._ensure_connection()
        try:
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
        except sqlite3.Error as exc:
            # A cache WRITE is an optimization, not the deliverable: never let its
            # failure (disk full / SQLITE_FULL, I/O error) propagate and turn a
            # SUCCESSFUL provider fetch into a 500 — DataLayer.fetch writes the row
            # only AFTER it already holds real data. Log + swallow; the next write
            # retries. (QuoteCache armors its L2 write the same way.) The
            # connection stays healthy for a disk-full, so it is reused as-is.
            logger.warning(
                "data_cache write failed for %s/%s (non-fatal, data still served): %s",
                slot_key,
                ticker,
                exc,
            )

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

        A row whose payload no longer validates as ``DataResult`` (corrupt
        JSON, schema drift without a raw-slot version bump) is deleted and
        treated as a miss (self-heal): ``DataLayer.fetch`` reads the cache as
        its FIRST step, so a raised ValidationError would never reach the
        provider loop and the slot could only recover via the 30-day evict.
        """
        slot = await self._get_slot(raw_slot_key(data_type), ticker, data_type, max_age_hours)
        if slot is None:
            return None
        payload_json, cached_at, is_stale = slot
        try:
            data = DataResult.model_validate_json(payload_json)
        except ValidationError:
            logger.warning(
                "Corrupt raw cache payload for %s/%s — deleting (self-heal)",
                raw_slot_key(data_type),
                ticker,
            )
            await self._delete_slot(raw_slot_key(data_type), ticker)
            return None
        return CachedResult(
            data=data,
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
        *,
        provider: str | None = None,
    ) -> CachedCanonical | None:
        """Retrieve a normalized payload from the versioned canonical slot.

        Staleness uses the BASE data_type's TTL (the canonical key itself isn't
        in ``_TTL_SECONDS``). Returns the JSON string; the DataLayer validates
        it into ``NormalizedPrice`` / ``NormalizedFinancials`` — and on a
        ValidationError calls :meth:`delete_canonical` so the corrupt row
        self-heals instead of blocking the slot (the cache stays model-agnostic,
        so the payload twin of ``get``'s self-heal lives at the validation site).

        ``provider`` selects the provider-qualified slot (see ``canonical_key``):
        the DataLayer passes the preferred capable provider so the read targets
        the slot the next write would land in.
        """
        slot = await self._get_slot(
            canonical_key(data_type, provider), ticker, data_type, max_age_hours
        )
        if slot is None:
            return None
        payload_json, cached_at, is_stale = slot
        return CachedCanonical(payload_json=payload_json, is_stale=is_stale, cached_at=cached_at)

    async def get_canonical_latest(
        self,
        data_type: str | DataType,
        ticker: str,
        max_age_hours: int | None = None,
    ) -> tuple[CachedCanonical, str | None] | None:
        """Freshest canonical row across ALL provider-qualified slots for one
        ``(data_type, ticker)`` — returns ``(CachedCanonical, provider)`` or None.

        The provider-agnostic READ for the stale-while-revalidate paint
        (``read_canonical_cached``): after a provider swap the preferred provider's
        slot may be empty (a fallback provider wrote its own slot), so a strict
        provider-keyed read would go cold and the desk would blank a row it has a
        perfectly good (if stale, differently-calibered) last-known snapshot for.
        This scans every ``…:canonical:v<N>:provider=*`` slot (plus the bare slot)
        for the ticker and returns the most-recently cached one, tagged with its
        provider so the caller surfaces the honest caliber. It NEVER lets a
        fallback slot masquerade as the primary's: the freshness clock and the
        ``provider`` tag travel with the row. ``fetch_canonical`` deliberately does
        NOT use this — its refresh decision reads only the preferred slot so a
        fallback caliber is never served as a fresh primary hit.
        """
        prefix = canonical_key(data_type)  # versioned base, no provider suffix
        conn = await self._ensure_connection()
        async with conn.execute(
            "SELECT data_type, data, cached_at FROM cache "
            "WHERE ticker = ? AND (data_type = ? OR data_type LIKE ?) "
            "ORDER BY cached_at DESC LIMIT 1",
            (ticker, prefix, f"{prefix}:provider=%"),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        slot_key, payload_json, cached_at_str = row
        try:
            cached_at = datetime.fromisoformat(cached_at_str)
        except ValueError:
            logger.warning(
                "Corrupt cache row (unparseable cached_at) for %s/%s — deleting (self-heal)",
                slot_key,
                ticker,
            )
            await self._delete_slot(slot_key, ticker)
            return None
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)
        age_seconds = (datetime.now(tz=timezone.utc) - cached_at).total_seconds()
        if max_age_hours is not None:
            is_stale = age_seconds > max_age_hours * 3600
        else:
            is_stale = age_seconds > _get_ttl_seconds(data_type)
        provider = slot_key.split(":provider=", 1)[1] if ":provider=" in slot_key else None
        return (
            CachedCanonical(payload_json=payload_json, is_stale=is_stale, cached_at=cached_at),
            provider,
        )

    async def set_canonical(
        self,
        data_type: str | DataType,
        ticker: str,
        payload_json: str,
        *,
        provider: str | None = None,
    ) -> None:
        """Store a normalized payload (``Normalized*.model_dump_json()``) in the
        versioned canonical slot, isolated from the raw slot.

        ``provider`` keys on the WINNING provider so a fallback-provider snapshot
        of a different caliber lands in its OWN slot rather than overwriting the
        primary provider's (see ``canonical_key``)."""
        await self._set_slot(canonical_key(data_type, provider), ticker, payload_json)

    async def delete_canonical(
        self, data_type: str | DataType, ticker: str, *, provider: str | None = None
    ) -> None:
        """Drop one canonical row — the DataLayer's self-heal hook for a payload
        that no longer validates as its ``Normalized*`` contract (see
        ``get_canonical``). ``provider`` must match the slot that was read."""
        await self._delete_slot(canonical_key(data_type, provider), ticker)

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
        try:
            cur = await conn.execute("DELETE FROM cache WHERE cached_at < ?", (cutoff_iso,))
            deleted = cur.rowcount
            await conn.commit()
        except sqlite3.Error as exc:
            # Best-effort housekeeping: a write failure (disk full — ironically
            # when eviction is most needed) must not crash the background pass.
            # Log + report 0 deleted; the next scheduled pass retries.
            logger.warning("data_cache evict_expired DELETE failed (non-fatal): %s", exc)
            return 0
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
    should_cache: Callable[[dict[str, Any]], bool] | None = None,
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

        # A transient degraded result (e.g. a historical band with all-None percentiles
        # from a steady-state provider outage) must NOT land in the long-TTL cache, or the
        # outage persists for the full TTL after recovery (non-self-healing). ``should_cache``
        # lets a caller veto caching such results; default None caches everything — unchanged
        # for the /price /historical /quarterly callers. Bug-4, 2026-06-24.
        if should_cache is None or should_cache(data):
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
