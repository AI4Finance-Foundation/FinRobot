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

Failures land as ``None`` in both layers — same TTL applies, so we don't
loop-hammer yfinance for a delisted symbol.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import aiosqlite

from finrobot import paths as _paths

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS quotes_cache (
    ticker     TEXT PRIMARY KEY,
    last_price REAL,
    fetched_at REAL NOT NULL
)
"""


FetcherType = Callable[[list[str]], Awaitable[dict[str, float | None]]]


class QuoteCache:
    """Process-wide TTL cache for live quotes."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        ttl_seconds: float = 60.0,
    ) -> None:
        if db_path is None:
            _paths.ensure_home()
            db_path = _paths.QUOTES_DB
        self._db_path = str(db_path)
        self._ttl = float(ttl_seconds)
        self._l1: dict[str, tuple[float | None, float]] = {}
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
                    await conn.execute("PRAGMA journal_mode=WAL")
                    await conn.execute("PRAGMA synchronous=NORMAL")
                    await conn.execute(_CREATE_TABLE)
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

    async def get_batch(
        self,
        tickers: list[str],
        fetcher: FetcherType,
    ) -> dict[str, float | None]:
        syms = [t.strip().upper() for t in tickers if t and t.strip()]
        if not syms:
            return {}

        now = time.time()
        result: dict[str, float | None] = {}
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
        l2_fresh: dict[str, float | None] = {}
        if missing:
            try:
                conn = await self._conn_ready()
                placeholders = ",".join("?" * len(missing))
                async with conn.execute(
                    f"SELECT ticker, last_price, fetched_at FROM quotes_cache "
                    f"WHERE ticker IN ({placeholders})",
                    missing,
                ) as cur:
                    rows = await cur.fetchall()
                for ticker, last_price, fetched_at in rows:
                    if now - float(fetched_at) < self._ttl:
                        l2_fresh[ticker] = last_price
            except sqlite3.Error:
                logger.exception(
                    "QuoteCache L2 read failed for %s — dropping conn", missing
                )
                await self._drop_conn()
                # l2_fresh stays empty; fetcher handles everything

            if l2_fresh:
                async with self._l1_lock:
                    for ticker, price in l2_fresh.items():
                        self._l1[ticker] = (price, now)
                        result[ticker] = price
                missing = [m for m in missing if m not in l2_fresh]

        # Origin
        if missing:
            try:
                fetched = await fetcher(missing)
            except (OSError, ValueError, TypeError, RuntimeError) as exc:
                logger.warning("Quote fetcher failed for %s: %s", missing, exc)
                fetched = dict.fromkeys(missing)
            now = time.time()
            # L2 write is best-effort. Same reasoning as the L2 read: a
            # broken conn must not poison L1 promotion or the response.
            try:
                conn = await self._conn_ready()
                for sym in missing:
                    await conn.execute(
                        """
                        INSERT INTO quotes_cache (ticker, last_price, fetched_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(ticker) DO UPDATE SET
                            last_price = excluded.last_price,
                            fetched_at = excluded.fetched_at
                        """,
                        (sym, fetched.get(sym), now),
                    )
                await conn.commit()
            except sqlite3.Error:
                logger.exception(
                    "QuoteCache L2 write failed for %s — dropping conn", missing
                )
                await self._drop_conn()
            async with self._l1_lock:
                for sym in missing:
                    price = fetched.get(sym)
                    self._l1[sym] = (price, now)
                    result[sym] = price

        return result

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
