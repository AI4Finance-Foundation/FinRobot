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
from collections.abc import Iterable
from datetime import date
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
    holder_cik      TEXT,
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


async def _conn() -> aiosqlite.Connection:
    global _GLOBAL_CONN
    if _GLOBAL_CONN is not None:
        return _GLOBAL_CONN
    async with _CONN_LOCK:
        if _GLOBAL_CONN is None:
            _paths.ensure_home()
            db = _paths.SEC_HOLDINGS_DB
            Path(db).parent.mkdir(parents=True, exist_ok=True)
            c = await aiosqlite.connect(str(db))
            try:
                await c.execute("PRAGMA journal_mode=WAL")
                await c.execute("PRAGMA synchronous=NORMAL")
                # executescript not supported across all aiosqlite paths;
                # split into individual statements.
                for stmt in [s.strip() for s in _SCHEMA.split(";") if s.strip()]:
                    await c.execute(stmt)
                await c.commit()
            except BaseException:
                await c.close()
                raise
            _GLOBAL_CONN = c
    return _GLOBAL_CONN


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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def lookup_holders_for_ticker(
    ticker: str,
    issuer_name: str | None = None,
    period_end: date | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return list of institutions holding ``ticker`` at ``period_end``.

    When ``period_end`` is None, returns the most-recent quarter present in
    cache. Empty list when:
      - cache hasn't been built (no SEC_HOLDINGS_DB file yet)
      - no holders recorded for this ticker / period

    Caller (Chapter 12.2) MUST handle the empty-list case as "data
    unavailable — refresh job not yet run", NOT as "no institutions hold
    this stock".
    """
    tkr = ticker.strip().upper()
    if not tkr:
        return []

    c = await _conn()

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
        }
        for row in rows
    ]


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
                    r.get("holder_cik"),
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


async def cache_status() -> dict[str, Any]:
    """Quick health probe for /api/health/sec-holdings or Settings page.

    Returns ``{"populated": bool, "row_count": int, "latest_period_end":
    str|None, "distinct_tickers": int}``.
    """
    c = await _conn()
    async with c.execute(
        "SELECT COUNT(*), MAX(period_end), COUNT(DISTINCT ticker) FROM holdings"
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return {
            "populated": False,
            "row_count": 0,
            "latest_period_end": None,
            "distinct_tickers": 0,
        }
    total, latest, distinct = row
    return {
        "populated": bool(total),
        "row_count": int(total) if total else 0,
        "latest_period_end": str(latest) if latest else None,
        "distinct_tickers": int(distinct) if distinct else 0,
    }
