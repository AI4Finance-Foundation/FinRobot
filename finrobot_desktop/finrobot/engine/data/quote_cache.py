"""Two-layer quote cache: L1 in-memory + L2 SQLite.

Why this exists:
  yfinance's ``Tickers(...).fast_info`` is synchronous and ~1-2s per ticker.
  The landing-page dashboard endpoints (hit-rate, recent-research) each
  fan out to every studied ticker — without a shared cache that's 7-8s on
  cold load. This module collapses every caller within a single TTL
  window down to one upstream fetch per ticker.

Lookup flow for ``get_batch(tickers, fetcher)``:
  1. For each ticker, check L1 dict; if fresh, take from L1
  2. For remaining, single ``SELECT`` against the SQLite ``quotes_cache``
     table; if fresh, promote to L1 and take
  3. For remaining (still missing or stale), call ``fetcher(missing)``
     ONCE, write results into both L1 and L2

Terminal failures (delisted, ticker-not-found, network reset) land as
``None`` in both layers — same TTL applies, so we don't loop-hammer
yfinance for a dead symbol.

Rate-limit failures take a different path. When the fetcher raises
:class:`QuoteFetchRateLimited`, every previously cached value (even
TTL-expired) is returned as-is and NO write happens. Without this
distinction a Yahoo 429 burst overwrote every studied ticker with
``None`` for the full TTL, taking the landing dashboard cold for
60 seconds even after the upstream recovered.

On top of that, a rate-limit opens a short *cooldown* window
(``rate_limit_cooldown_seconds``): while it's active, ``get_batch``
serves stale rows WITHOUT calling the fetcher again. This is what stops
a throttled Yahoo from turning every dashboard refresh into another
doomed round-trip (the "laptop runs hot / fan spins" symptom). It is
orthogonal to stale-preservation: that decides WHAT price to show, the
cooldown decides whether to bother ASKING the upstream at all. Because
this cache's only fetcher is the yfinance batch path, the cooldown is
effectively per-provider ("yfinance is throttled"), not per-ticker — it
never blocks a different provider from serving a real price.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

from finrobot import paths as _paths

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Quote:
    """A live quote carrying BOTH its price and the currency that price is in.

    The price alone is ambiguous: a foreign LOCAL listing (2330.TW) quotes in TWD,
    a US issuer / ADR in USD, and a downstream signal compares the live price
    against canonical-USD entry/target. Carrying ``currency`` with the price (its
    own source — yfinance ``fast_info.currency`` / FMP ``/profile.currency``) lets
    the consumer convert to USD or correctly abstain, instead of having to guess
    the currency from a second, independently-cached source (the strip's old
    quote-batch-warm + canonical-cold mis-lit-lamp bug). ``currency`` is None when
    the source could not resolve it (then the consumer abstains, never assumes USD).
    """

    price: float | None
    currency: str | None = None


class QuoteFetchRateLimited(RuntimeError):
    """Fetcher signalled the upstream quote source rate-limited us.

    The cache layer treats this distinctly from generic fetcher
    failures: existing rows are preserved (even past TTL) and no
    ``None`` tombstone is written. Other failure modes (delisted
    ticker, network reset) still tomb-stone for the full TTL so we
    don't loop-hammer yfinance for a dead symbol.
    """


# Schema v2 (2026-06-17): the cached value gained a ``currency`` column so a
# foreign-listing quote carries its currency with the price (the strip mis-lit-lamp
# root fix). The value SHAPE changed, so the table is versioned — the old v1
# ``quotes_cache`` (price-only) rows are simply never read by this code, so a stale
# v1 row can't deserialize-crash or be mistaken for a USD quote. v1 is dropped on
# first connect to reclaim its space; a fresh v2 fill repopulates within one TTL.
_QUOTES_TABLE = "quotes_cache_v2"
_CREATE_TABLE = f"""
CREATE TABLE IF NOT EXISTS {_QUOTES_TABLE} (
    ticker     TEXT PRIMARY KEY,
    last_price REAL,
    currency   TEXT,
    fetched_at REAL NOT NULL
)
"""
_DROP_LEGACY_TABLE = "DROP TABLE IF EXISTS quotes_cache"


FetcherType = Callable[[list[str]], Awaitable[dict[str, "Quote | None"]]]


class QuoteCache:
    """Process-wide TTL cache for live quotes."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        ttl_seconds: float = 60.0,
        rate_limit_cooldown_seconds: float = 30.0,
    ) -> None:
        if db_path is None:
            _paths.ensure_home()
            db_path = _paths.QUOTES_DB
        self._db_path = str(db_path)
        self._ttl = float(ttl_seconds)
        self._rate_limit_cooldown = float(rate_limit_cooldown_seconds)
        # monotonic deadline; while time.monotonic() < this, the upstream is
        # considered throttled and get_batch serves stale rows without fetching.
        self._rate_limit_until = 0.0
        self._l1: dict[str, tuple[Quote | None, float]] = {}
        self._l1_lock = asyncio.Lock()
        self._conn: aiosqlite.Connection | None = None
        self._conn_lock = asyncio.Lock()

    async def _conn_ready(self) -> aiosqlite.Connection:
        if self._conn is not None:
            return self._conn
        async with self._conn_lock:
            if self._conn is None:
                Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
                conn = await aiosqlite.connect(self._db_path)
                try:
                    await _paths.configure_connection(conn)
                    await conn.execute(_CREATE_TABLE)
                    # Reclaim the v1 price-only table (schema bump); never read again.
                    await conn.execute(_DROP_LEGACY_TABLE)
                    await conn.commit()
                except BaseException:
                    await conn.close()
                    raise
                self._conn = conn
        return self._conn

    async def _drop_conn(self) -> None:
        """Discard the cached aiosqlite connection so the next call rebuilds.

        Long-running desktop sessions occasionally end up with a wedged
        connection (event-loop swap, sqlite worker thread died, WAL race).
        When SQL raises ``sqlite3.Error`` we close + null the handle so the
        very next ``_conn_ready`` call opens a fresh one — without this the
        singleton would refuse to serve any caller for the rest of the
        process lifetime, taking the entire landing page down with it.
        """
        async with self._conn_lock:
            conn = self._conn
            self._conn = None
        if conn is not None:
            try:
                await conn.close()
            except (sqlite3.Error, OSError, RuntimeError):
                logger.exception("QuoteCache stale-conn close failed (non-fatal)")

    async def _fill_from_stale(self, missing: list[str], result: dict[str, Quote | None]) -> None:
        """Populate ``result`` from L2 rows ignoring TTL.

        Used when the upstream is rate-limited or in cooldown: we serve the
        last known price rather than re-hitting a throttled source. Tickers
        with no row anywhere land as ``None`` so callers treat them like any
        cold miss. A wedged sqlite conn is dropped (non-fatal) — the caller
        still gets None rather than an exception.
        """
        if not missing:
            return
        try:
            conn = await self._conn_ready()
            placeholders = ",".join("?" * len(missing))
            async with conn.execute(
                f"SELECT ticker, last_price, currency FROM {_QUOTES_TABLE} "
                f"WHERE ticker IN ({placeholders})",
                missing,
            ) as cur:
                stale_rows = await cur.fetchall()
            for ticker, last_price, currency in stale_rows:
                result[ticker] = Quote(price=last_price, currency=currency)
        except sqlite3.Error:
            logger.exception("QuoteCache stale read failed for %s — dropping conn", missing)
            await self._drop_conn()
        for sym in missing:
            result.setdefault(sym, None)

    async def get_batch(
        self,
        tickers: list[str],
        fetcher: FetcherType,
    ) -> dict[str, Quote | None]:
        syms = [t.strip().upper() for t in tickers if t and t.strip()]
        if not syms:
            return {}

        now = time.time()
        result: dict[str, Quote | None] = {}
        missing: list[str] = []

        # L1
        async with self._l1_lock:
            for sym in syms:
                hit = self._l1.get(sym)
                if hit is not None and now - hit[1] < self._ttl:
                    result[sym] = hit[0]
                else:
                    missing.append(sym)

        # L2 — sqlite3 errors here are *non-fatal*: drop the wedged
        # connection so the next request rebuilds, then fall through to the
        # origin fetcher as if L2 were cold. The whole landing page
        # depends on this cache; a dead conn must not become a 30-hour
        # 500 spree.
        l2_fresh: dict[str, Quote | None] = {}
        if missing:
            try:
                conn = await self._conn_ready()
                placeholders = ",".join("?" * len(missing))
                async with conn.execute(
                    f"SELECT ticker, last_price, currency, fetched_at FROM {_QUOTES_TABLE} "
                    f"WHERE ticker IN ({placeholders})",
                    missing,
                ) as cur:
                    rows = await cur.fetchall()
                for ticker, last_price, currency, fetched_at in rows:
                    if now - float(fetched_at) < self._ttl:
                        l2_fresh[ticker] = Quote(price=last_price, currency=currency)
            except sqlite3.Error:
                logger.exception("QuoteCache L2 read failed for %s — dropping conn", missing)
                await self._drop_conn()
                # l2_fresh stays empty; fetcher handles everything

            if l2_fresh:
                async with self._l1_lock:
                    for ticker, price in l2_fresh.items():
                        self._l1[ticker] = (price, now)
                        result[ticker] = price
                missing = [m for m in missing if m not in l2_fresh]

        # Cooldown gate: the upstream was rate-limited within the last
        # _rate_limit_cooldown seconds. Don't re-hit it — serve stale rows
        # only. This is the heat fix: without it every dashboard refresh
        # during a Yahoo 429 storm fires another doomed round-trip.
        if missing and time.monotonic() < self._rate_limit_until:
            await self._fill_from_stale(missing, result)
            return result

        # Origin
        if missing:
            rate_limited = False
            try:
                fetched = await fetcher(missing)
            except QuoteFetchRateLimited as exc:
                # Upstream 429: keep whatever stale price the cache has
                # rather than tomb-stoning the ticker with None for 60s.
                # The freshness pill will already classify these as
                # stale/delayed by their fetched_at age (>5min cyan,
                # >30min red), so the user sees the truth without losing
                # the price entirely.
                logger.warning(
                    "Quote fetcher rate-limited for %s — preserving stale cache: %s",
                    missing,
                    exc,
                )
                rate_limited = True
                fetched = {}
            except (OSError, ValueError, TypeError, RuntimeError) as exc:
                logger.warning("Quote fetcher failed for %s: %s", missing, exc)
                fetched = dict.fromkeys(missing)
            now = time.time()
            if rate_limited:
                # Open the cooldown window so subsequent batches skip the
                # fetcher entirely (see the cooldown gate above). Then don't
                # touch L2/L1 — serve whatever stale row L2 holds, even past
                # TTL; tickers with nothing land as None like any cold miss.
                self._rate_limit_until = time.monotonic() + self._rate_limit_cooldown
                await self._fill_from_stale(missing, result)
                return result

            # L2 write is best-effort. Same reasoning as the L2 read: a
            # broken conn must not poison L1 promotion or the response.
            try:
                conn = await self._conn_ready()
                for sym in missing:
                    q = fetched.get(sym)
                    await conn.execute(
                        f"""
                        INSERT INTO {_QUOTES_TABLE} (ticker, last_price, currency, fetched_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(ticker) DO UPDATE SET
                            last_price = excluded.last_price,
                            currency = excluded.currency,
                            fetched_at = excluded.fetched_at
                        """,
                        (sym, q.price if q else None, q.currency if q else None, now),
                    )
                await conn.commit()
            except sqlite3.Error:
                logger.exception("QuoteCache L2 write failed for %s — dropping conn", missing)
                await self._drop_conn()
            async with self._l1_lock:
                for sym in missing:
                    q = fetched.get(sym)
                    self._l1[sym] = (q, now)
                    result[sym] = q

        return result

    async def peek_batch(self, tickers: list[str]) -> dict[str, Quote | None]:
        """Read-only batch lookup — serves only *fresh* L1/L2 rows, never writes.

        Unlike :meth:`get_batch` this NEVER invokes a fetcher and NEVER writes
        to L1/L2. Fresh L1 hits and fresh L2 hits return their price; every
        other ticker — cold, or stale (past TTL) — comes back ``None``.

        Crucially a miss is NOT tomb-stoned. The cache-only landing path used to
        borrow ``get_batch`` with a no-op fetcher, whose ``None`` result was then
        written into L1+L2 as a *fresh* value — destroying the
        stale-while-revalidate price and blocking the next real fetch within the
        TTL (W2 探针毒化). A pure peek leaves the cache untouched, so the next
        ``get_batch`` still refetches stale tickers and ``_fill_from_stale``
        still recovers the last known price.
        """
        syms = [t.strip().upper() for t in tickers if t and t.strip()]
        if not syms:
            return {}

        now = time.time()
        result: dict[str, Quote | None] = {}
        missing: list[str] = []

        # L1 (fresh only) — read, never write.
        async with self._l1_lock:
            for sym in syms:
                hit = self._l1.get(sym)
                if hit is not None and now - hit[1] < self._ttl:
                    result[sym] = hit[0]
                else:
                    missing.append(sym)

        # L2 (fresh only) — read, never write back. No tombstone, no promotion.
        # A wedged conn is dropped (non-fatal); those tickers fall to None below.
        if missing:
            try:
                conn = await self._conn_ready()
                placeholders = ",".join("?" * len(missing))
                async with conn.execute(
                    f"SELECT ticker, last_price, currency, fetched_at FROM {_QUOTES_TABLE} "
                    f"WHERE ticker IN ({placeholders})",
                    missing,
                ) as cur:
                    rows = await cur.fetchall()
                for ticker, last_price, currency, fetched_at in rows:
                    if now - float(fetched_at) < self._ttl:
                        result[ticker] = Quote(price=last_price, currency=currency)
            except sqlite3.Error:
                logger.exception("QuoteCache peek L2 read failed for %s — dropping conn", missing)
                await self._drop_conn()

        # Cold or stale → None, WITHOUT writing back (the 探针毒化 fix).
        for sym in syms:
            result.setdefault(sym, None)

        return result

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
