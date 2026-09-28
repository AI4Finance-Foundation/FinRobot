"""13F holdings local cache — reverse index `ticker → list[holder]`.

Why this exists:
  edgartools 5.31.5 has no ticker→holders reverse API (probe 2026-05-27
  tried 5 candidate method names, all AttributeError). The forward path
  works — `get_filings(form="13F-HR").latest(N)` returns EntityFilings,
  each `.obj().holdings` is a DataFrame with ~386 rows per institutional
  manager. So we build the reverse index ourselves: download every 13F-HR
  in a quarter, normalise into rows, persist to SQLite indexed by
  (ticker, holder_cik, period_end).

Run cadence:
  13F filings are due within 45 days of quarter end. The refresh script
  ``scripts/refresh_sec_holdings.py`` accepts ``--period 2026-03-31`` or
  ``--latest`` and is safe to re-run (UPSERT keyed on PRIMARY KEY).

Lookup contract:
  ``lookup_holders_for_ticker(ticker)`` returns ``list[dict]`` (NOT typed
  ``InstitutionalHolding`` — wrap at call site for serialization). Returns
  empty list when the cache hasn't been built — caller (Chapter 12.2)
  must render a placeholder, NEVER block the request waiting for a
  refresh.

Architectural red line (sealed in spec v4 §5 ``_fetch_13f``):
  Routes / pipeline steps MUST NOT call ``get_filings(form="13F-HR")``
  at request time. Reverse lookup MUST go through this module's
  ``lookup_holders_for_ticker``. Performance + SEC rate-limit risk.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import re
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from finrobot import paths as _paths

logger = logging.getLogger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS holdings (
    ticker          TEXT,
    cusip           TEXT NOT NULL,
    name_of_issuer  TEXT NOT NULL,
    issuer_key      TEXT NOT NULL,
    title_of_class  TEXT NOT NULL DEFAULT 'COM',
    holder_name     TEXT NOT NULL,
    holder_cik      TEXT NOT NULL DEFAULT '',
    shares          INTEGER NOT NULL,
    value_usd       REAL NOT NULL,
    period_end      TEXT NOT NULL,
    filing_date     TEXT NOT NULL,
    accession_no    TEXT NOT NULL,
    PRIMARY KEY (cusip, holder_cik, period_end, title_of_class)
);
CREATE INDEX IF NOT EXISTS idx_holdings_ticker
    ON holdings(ticker, period_end DESC);
CREATE INDEX IF NOT EXISTS idx_holdings_cusip
    ON holdings(cusip, period_end DESC);
CREATE INDEX IF NOT EXISTS idx_holdings_issuer_key
    ON holdings(issuer_key, period_end DESC);
CREATE INDEX IF NOT EXISTS idx_holdings_period
    ON holdings(period_end);
CREATE TABLE IF NOT EXISTS holdings_refresh_meta (
    period_end        TEXT PRIMARY KEY,
    filings_processed INTEGER NOT NULL,
    completed_at      TEXT NOT NULL
);
"""

# Connection singleton — same pattern as QuoteCache. Async-safe init.
_GLOBAL_CONN: aiosqlite.Connection | None = None
_CONN_LOCK = asyncio.Lock()


_LEGAL_SUFFIXES = {
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
    "ltd",
    "limited",
    "plc",
    "holdings",
    "holding",
    "group",
    "class",
    "cl",
    "common",
    "stock",
    "com",
    "new",
}


def _issuer_key(value: str | None) -> str:
    """Return a stable issuer-name key for 13F rows and Company names."""
    if not value:
        return ""
    tokens = re.findall(r"[a-z0-9]+", value.lower())
    filtered = [t for t in tokens if t not in _LEGAL_SUFFIXES]
    return " ".join(filtered or tokens)


async def _open_connection() -> aiosqlite.Connection:
    """Open + configure a connection and ensure the schema. Caller owns it."""
    _paths.ensure_home()
    db = _paths.SEC_HOLDINGS_DB
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    c = await aiosqlite.connect(str(db))
    try:
        await _paths.configure_connection(c)
        # executescript not supported across all aiosqlite paths;
        # split into individual statements.
        for stmt in [s.strip() for s in _SCHEMA.split(";") if s.strip()]:
            await c.execute(stmt)
        await c.commit()
    except BaseException:
        await c.close()
        raise
    return c


async def _conn() -> aiosqlite.Connection:
    global _GLOBAL_CONN
    if _GLOBAL_CONN is not None:
        return _GLOBAL_CONN
    async with _CONN_LOCK:
        if _GLOBAL_CONN is None:
            _GLOBAL_CONN = await _open_connection()
    return _GLOBAL_CONN


@asynccontextmanager
async def ephemeral_connection() -> AsyncIterator[aiosqlite.Connection]:
    """Open-use-close connection for ``asyncio.run`` islands (BUG-082 sibling).

    The process-wide singleton is bound to the event loop that first created
    it. ``EdgarProvider._fetch_13f_sync`` runs inside ``asyncio.to_thread`` and
    spins up a BRAND-NEW loop per call via ``asyncio.run``; awaiting the
    singleton from that loop (or poisoning the singleton by creating it on a
    loop that immediately dies) deadlocks every later caller. Cross-loop
    callers must scope their I/O to this context manager; main-loop callers
    (routes/sec_holdings, sec_holdings_sync) keep the singleton's performance.
    """
    c = await _open_connection()
    try:
        yield c
    finally:
        await c.close()


async def close_singleton() -> None:
    """Close the process-wide connection. Call from lifespan shutdown."""
    global _GLOBAL_CONN
    if _GLOBAL_CONN is not None:
        await _GLOBAL_CONN.close()
        _GLOBAL_CONN = None


def reset_singleton_sync() -> None:
    """Test-only: drop the cached connection without closing (for monkeypatched paths)."""
    global _GLOBAL_CONN
    _GLOBAL_CONN = None


# 13F-HR is due within 45 days after each calendar-quarter end (SEC rule
# 13f-1(a)). The cadence math lives HERE — the module that owns the cache —
# so every consumer (EDGAR provider warning, /api/sec-holdings/status,
# Settings UI) shares one staleness definition instead of re-deriving it.
_FORM_13F_DEADLINE_DAYS = 45

_QUARTER_ENDS = ((3, 31), (6, 30), (9, 30), (12, 31))


def _previous_quarter_end(d: date) -> date:
    """Most recent calendar-quarter end strictly before ``d``."""
    year = d.year
    while True:
        for month, day in reversed(_QUARTER_ENDS):
            q = date(year, month, day)
            if q < d:
                return q
        year -= 1


def expected_latest_period_end(today: date) -> date:
    """Most recent quarter end whose 13F filing deadline has already passed.

    A quarter only becomes "expected in cache" the day AFTER its 45-day
    deadline: on the deadline day filings are still legally trickling in,
    so flagging stale then would false-positive. The statutory deadline can
    shift a business day or two when it lands on a weekend/holiday; this
    feeds a soft warning (never a throw), so the 45-day approximation only
    means the hint may appear a day early in those windows.
    """
    q_end = _previous_quarter_end(today)
    while today <= q_end + timedelta(days=_FORM_13F_DEADLINE_DAYS):
        q_end = _previous_quarter_end(q_end)
    return q_end


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def lookup_holders_for_ticker(
    ticker: str,
    issuer_name: str | None = None,
    period_end: date | None = None,
    limit: int = 20,
    *,
    conn: aiosqlite.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return list of institutions holding ``ticker`` at ``period_end``.

    When ``period_end`` is None, returns the most-recent quarter present in
    cache. Empty list when:
      - cache hasn't been built (no SEC_HOLDINGS_DB file yet)
      - no holders recorded for this ticker / period

    Caller (Chapter 12.2) MUST handle the empty-list case as "data
    unavailable — refresh job not yet run", NOT as "no institutions hold
    this stock".

    ``conn``: cross-loop callers (``asyncio.run`` islands) must pass an
    ``ephemeral_connection()``; None uses the main-loop singleton.
    """
    tkr = ticker.strip().upper()
    if not tkr:
        return []

    c = conn if conn is not None else await _conn()

    issuer_key = _issuer_key(issuer_name)

    def _where_clause() -> tuple[str, tuple[Any, ...]]:
        if issuer_key:
            return "(ticker = ? OR (ticker IS NULL AND issuer_key = ?))", (tkr, issuer_key)
        return "ticker = ?", (tkr,)

    where_sql, where_params = _where_clause()

    if period_end is None:
        async with c.execute(
            f"""
            SELECT period_end FROM holdings WHERE {where_sql}
            ORDER BY period_end DESC LIMIT 1
            """,
            where_params,
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return []
        period_end_str = str(row[0])
    else:
        period_end_str = period_end.isoformat()

    async with c.execute(
        f"""
        SELECT holder_name, holder_cik, shares, value_usd, period_end,
               filing_date, accession_no, name_of_issuer, cusip, title_of_class
        FROM holdings
        WHERE {where_sql} AND period_end = ?
        ORDER BY value_usd DESC
        LIMIT ?
        """,
        (*where_params, period_end_str, limit),
    ) as cur:
        rows = await cur.fetchall()

    # QoQ share-count change vs the immediately-prior cached quarter, keyed on
    # (holder_cik, title_of_class). Populated ONLY when a prior quarter exists in
    # cache — a fresh cache holds one quarter, so this stays None (the UI renders
    # "—") rather than a fabricated 0. A holder absent from the prior quarter (a
    # NEW position) also stays None, never +∞. This is the one place the QoQ Δ
    # column was ever meant to be filled: the field was declared "computed by
    # FinRobot vs prior quarter" but never actually computed, so the column was a
    # permanent dead "—". Now it lights up automatically once ≥2 quarters cache.
    prior_shares = await _prior_quarter_shares(c, where_sql, where_params, period_end_str)

    return [
        {
            "holder_name": row[0],
            "holder_cik": row[1],
            "shares": int(row[2]),
            "value_usd": float(row[3]),
            "period_end": str(row[4]),
            "filing_date": str(row[5]),
            "accession_no": str(row[6]),
            "name_of_issuer": str(row[7]),
            "cusip": str(row[8]),
            "title_of_class": str(row[9]),
            "shares_change_pct": _shares_change_pct(
                int(row[2]), prior_shares.get((str(row[1]), str(row[9])))
            ),
        }
        for row in rows
    ]


def _shares_change_pct(current: int, prior: int | None) -> float | None:
    """QoQ % change in a holder's share count, or None when there is no prior
    position to diff against (fresh cache / new holder). None ≠ 0 and never ±∞."""
    if prior is None or prior <= 0:
        return None
    return round((current - prior) / prior * 100.0, 2)


async def _prior_quarter_shares(
    c: aiosqlite.Connection,
    where_sql: str,
    where_params: tuple[Any, ...],
    current_period_end: str,
) -> dict[tuple[str, str], int]:
    """Map (holder_cik, title_of_class) → shares for the newest cached quarter
    strictly before ``current_period_end`` for this ticker/issuer. Empty when no
    earlier quarter is cached (so QoQ change stays None, not a fabricated 0)."""
    async with c.execute(
        f"""
        SELECT MAX(period_end) FROM holdings
        WHERE {where_sql} AND period_end < ?
        """,
        (*where_params, current_period_end),
    ) as cur:
        row = await cur.fetchone()
    if row is None or row[0] is None:
        return {}
    prior_period = str(row[0])
    async with c.execute(
        f"""
        SELECT holder_cik, title_of_class, shares FROM holdings
        WHERE {where_sql} AND period_end = ?
        """,
        (*where_params, prior_period),
    ) as cur:
        prior_rows = await cur.fetchall()
    return {(str(r[0]), str(r[1])): int(r[2]) for r in prior_rows}


async def bulk_upsert_holdings(rows: Iterable[dict[str, Any]]) -> int:
    """Insert/update holdings rows. Returns count of rows touched.

    Each row dict must carry ALL these keys (refresh script's
    responsibility to normalise the EdgarTools DataFrame into this shape):
      ticker, cusip, name_of_issuer, title_of_class, holder_name, holder_cik,
      shares, value_usd, period_end (date or ISO str),
      filing_date (date or ISO str), accession_no
    """
    c = await _conn()
    count = 0
    for r in rows:
        period_end = r["period_end"]
        if isinstance(period_end, date):
            period_end = period_end.isoformat()
        filing_date = r["filing_date"]
        if isinstance(filing_date, date):
            filing_date = filing_date.isoformat()
        try:
            name_of_issuer = str(r["name_of_issuer"])
            await c.execute(
                """
                INSERT INTO holdings (
                    ticker, cusip, name_of_issuer, issuer_key, title_of_class,
                    holder_name, holder_cik, shares, value_usd,
                    period_end, filing_date, accession_no
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cusip, holder_cik, period_end, title_of_class)
                DO UPDATE SET
                    ticker = excluded.ticker,
                    name_of_issuer = excluded.name_of_issuer,
                    issuer_key = excluded.issuer_key,
                    holder_name = excluded.holder_name,
                    shares = excluded.shares,
                    value_usd = excluded.value_usd,
                    filing_date = excluded.filing_date,
                    accession_no = excluded.accession_no
                """,
                (
                    r.get("ticker"),
                    r["cusip"],
                    name_of_issuer,
                    _issuer_key(name_of_issuer),
                    r.get("title_of_class", "COM"),
                    r["holder_name"],
                    # holder_cik is part of the PRIMARY KEY; coalesce a missing
                    # CIK to '' so SQLite can dedup it (NULLs are distinct in a
                    # PK, which would let CIK-less filers accumulate dup rows).
                    r.get("holder_cik") or "",
                    int(r["shares"]),
                    float(r["value_usd"]),
                    period_end,
                    filing_date,
                    r["accession_no"],
                ),
            )
            count += 1
        except sqlite3.Error:
            logger.exception(
                "Failed to upsert holding cusip=%s holder_cik=%s period_end=%s",
                r.get("cusip"),
                r.get("holder_cik"),
                period_end,
            )
    await c.commit()
    return count


async def cache_status(*, conn: aiosqlite.Connection | None = None) -> dict[str, Any]:
    """Quick health probe for /api/health/sec-holdings or Settings page.

    Returns ``{"populated": bool, "row_count": int, "latest_period_end":
    str|None, "distinct_tickers": int, "expected_period_end": str,
    "stale": bool}``.

    ``stale`` is True when the cache IS populated but its newest quarter
    predates ``expected_period_end`` (the most recent quarter whose 13F
    deadline has passed) — i.e. a refresh is overdue. An unpopulated cache
    is reported via ``populated``, not ``stale``.

    ``distinct_tickers`` counts distinct CUSIPs, NOT the ``ticker`` column:
    13F XML identifies securities by CUSIP + issuer name, so ``ticker`` is
    always NULL (we hold no CUSIP→ticker license). Counting DISTINCT ticker
    therefore reported 0 even with millions of rows. CUSIP is the real
    "number of distinct securities held" — that is what the UI's "N 只标的"
    means.
    """
    expected = expected_latest_period_end(date.today()).isoformat()
    c = conn if conn is not None else await _conn()
    async with c.execute(
        "SELECT COUNT(*), MAX(period_end), COUNT(DISTINCT cusip) FROM holdings"
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return {
            "populated": False,
            "row_count": 0,
            "latest_period_end": None,
            "distinct_tickers": 0,
            "expected_period_end": expected,
            "stale": False,
        }
    total, latest, distinct = row
    latest_str = str(latest) if latest else None
    return {
        "populated": bool(total),
        "row_count": int(total) if total else 0,
        "latest_period_end": latest_str,
        "distinct_tickers": int(distinct) if distinct else 0,
        "expected_period_end": expected,
        # ISO date strings compare lexicographically == chronologically.
        "stale": bool(latest_str is not None and latest_str < expected),
    }


async def mark_period_complete(
    period_end: date | str,
    filings_processed: int,
    *,
    conn: aiosqlite.Connection | None = None,
) -> None:
    """Record that a quarter's refresh finished — every 13F-HR for the period
    was parsed, not just the newest slice the run happened to reach before it
    was interrupted.

    Why this exists: ``_refresh_quarter`` iterates ``get_filings(form="13F-HR")``
    NEWEST-first, and a partial run (app quit mid-parse, ``--max-filings`` dev
    cap, rate-limit abort) leaves only the most-recently-filed managers. The
    early filers — including the two largest, BlackRock (files its holdings under
    "BlackRock, Inc." CIK 2012383 since its 2025 reorg) and the Vanguard advisory
    sub-entities — file on/near the deadline day, so a truncated run silently
    drops them. Without a completion marker the freshness guard treats "has ANY
    rows for the latest quarter" as "complete" and never re-fetches, freezing the
    partial cache forever (2026: AAPL's top-8 institutional table missing
    BlackRock entirely). The marker lets the guard re-run an incomplete quarter.
    """
    period_str = period_end.isoformat() if isinstance(period_end, date) else str(period_end)
    completed_at = datetime.now(tz=timezone.utc).isoformat()
    c = conn if conn is not None else await _conn()
    await c.execute(
        """
        INSERT INTO holdings_refresh_meta (period_end, filings_processed, completed_at)
        VALUES (?, ?, ?)
        ON CONFLICT(period_end) DO UPDATE SET
            filings_processed = excluded.filings_processed,
            completed_at = excluded.completed_at
        """,
        (period_str, int(filings_processed), completed_at),
    )
    await c.commit()


async def is_period_complete(
    period_end: date | str,
    *,
    conn: aiosqlite.Connection | None = None,
) -> bool:
    """True when ``period_end`` has a completion marker (a full refresh finished).

    A quarter with holdings rows but NO marker was populated by an interrupted /
    capped run and should be re-fetched, not treated as done."""
    period_str = period_end.isoformat() if isinstance(period_end, date) else str(period_end)
    c = conn if conn is not None else await _conn()
    async with c.execute(
        "SELECT 1 FROM holdings_refresh_meta WHERE period_end = ?",
        (period_str,),
    ) as cur:
        return await cur.fetchone() is not None
