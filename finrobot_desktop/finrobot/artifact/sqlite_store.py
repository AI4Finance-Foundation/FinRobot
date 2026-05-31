"""SQLite-backed ArtifactStore.

Replaces the legacy filesystem layout (one JSON file per artifact, one
index.json per ticker dir) with a single SQLite db at
``~/.finrobot/artifacts.db``. Same async surface so consumers can swap
without code changes.

Schema (single table ``artifacts``):
    id             TEXT PRIMARY KEY
    ticker         TEXT NULL  (NULL ↔ cross-ticker artifact)
    cross_tickers  TEXT NOT NULL  (JSON list, empty array when ticker set)
    type           TEXT NOT NULL
    verdict        TEXT NULL   (BUY/HOLD/SELL; indexed)
    created_at     TEXT NOT NULL  (ISO 8601 UTC)
    last_viewed_at TEXT NULL
    archived       INTEGER NOT NULL DEFAULT 0
    entry_price    REAL NULL
    target_price   REAL NULL
    target_date    TEXT NULL
    source         TEXT NULL
    headline       TEXT NULL
    tagline        TEXT NULL
    payload        TEXT NOT NULL  (full Artifact JSON)

Why secondary columns: the dashboard hit-rate aggregation and the
"recent research" strip both group by verdict / sort by created_at and
need entry_price/target_price for the signal lamp — keeping these as
columns rather than re-extracting them from the payload on every read
eliminates the N+1 read pattern that dominated landing cold-start.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from finrobot.artifact.models import Artifact, ArtifactSummary, ArtifactType
from finrobot.engine.compute.signal import Signal  # noqa: F401 — used in ArtifactSummary
from finrobot.artifact.summary_extractor import (
    extract_entry_price,
    extract_tagline,
    extract_target_date,
    extract_target_price,
    extract_verdict,
)
from finrobot import paths as _paths

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS artifacts (
    id             TEXT PRIMARY KEY,
    ticker         TEXT,
    cross_tickers  TEXT NOT NULL DEFAULT '[]',
    type           TEXT NOT NULL,
    verdict        TEXT,
    created_at     TEXT NOT NULL,
    last_viewed_at TEXT,
    archived       INTEGER NOT NULL DEFAULT 0,
    entry_price    REAL,
    target_price   REAL,
    target_date    TEXT,
    source         TEXT,
    headline       TEXT,
    tagline        TEXT,
    payload        TEXT NOT NULL
)
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_artifacts_ticker_created ON artifacts(ticker, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_artifacts_ticker_type_created ON artifacts(ticker, type, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_artifacts_created ON artifacts(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_artifacts_archived_created ON artifacts(archived, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_artifacts_verdict ON artifacts(verdict) WHERE verdict IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_artifacts_archived ON artifacts(archived)",
]

_SUMMARY_COLUMNS = (
    "id, ticker, cross_tickers, type, verdict, created_at, archived, "
    "entry_price, target_price, target_date, source, headline, tagline"
)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _row_to_summary(row: tuple[Any, ...]) -> ArtifactSummary:
    (
        id_,
        ticker,
        cross_tickers_json,
        type_,
        verdict,
        created_at,
        archived,
        entry_price,
        target_price,
        target_date,
        source,
        headline,
        tagline,
    ) = row
    return ArtifactSummary(
        id=id_,
        ticker=ticker,
        cross_tickers=json.loads(cross_tickers_json) if cross_tickers_json else [],
        type=type_,
        created_at=_parse_dt(created_at) or _now(),
        headline=headline or id_,
        source=source or "",
        archived=bool(archived),
        entry_price=entry_price,
        target_price=target_price,
        target_date=_parse_dt(target_date),
        signal=None,
        verdict=verdict,
        tagline=tagline,
    )


def summary_from_artifact(artifact: Artifact) -> ArtifactSummary:
    """Build the lean :class:`ArtifactSummary` for a fully populated artifact.

    Same shape the SqliteArtifactStore writes into the indexed columns —
    exposed as a public helper because the old filesystem store used to
    publish this function and downstream tests pull from it.
    """
    target_price = extract_target_price(artifact)
    return ArtifactSummary(
        id=artifact.id,
        ticker=artifact.ticker,
        cross_tickers=list(artifact.cross_tickers or []),
        type=artifact.type,
        created_at=artifact.meta.created_at,
        headline=(artifact.outputs.summary_text[:120] or artifact.id) if artifact.outputs else artifact.id,
        source=artifact.meta.source,
        archived=artifact.meta.archived,
        entry_price=extract_entry_price(artifact),
        target_price=target_price,
        target_date=extract_target_date(artifact, target_price),
        signal=None,
        verdict=extract_verdict(artifact),
        tagline=extract_tagline(artifact),
    )


def _artifact_to_row(artifact: Artifact) -> tuple[Any, ...]:
    target_price = extract_target_price(artifact)
    target_date = extract_target_date(artifact, target_price)
    headline = (
        (artifact.outputs.summary_text[:120] or artifact.id)
        if artifact.outputs
        else artifact.id
    )
    return (
        artifact.id,
        artifact.ticker,
        json.dumps(list(artifact.cross_tickers or [])),
        artifact.type,
        extract_verdict(artifact),
        artifact.meta.created_at.isoformat(),
        artifact.meta.last_viewed_at.isoformat() if artifact.meta.last_viewed_at else None,
        1 if artifact.meta.archived else 0,
        extract_entry_price(artifact),
        target_price,
        target_date.isoformat() if target_date else None,
        artifact.meta.source,
        headline,
        extract_tagline(artifact),
        artifact.model_dump_json(),
    )


class SqliteArtifactStore:
    """SQLite-backed equivalent of the legacy filesystem ArtifactStore.

    Drop-in: identical async method signatures.

    Args:
        db_path: SQLite file path. Defaults to ``finrobot.paths.ARTIFACTS_DB``.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            _paths.ensure_home()
            db_path = _paths.ARTIFACTS_DB
        self._db_path = str(db_path)
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
                    for stmt in _CREATE_INDEXES:
                        await conn.execute(stmt)
                    await conn.commit()
                except BaseException:
                    await conn.close()
                    raise
                self._conn = conn
        return self._conn

    async def save(self, artifact: Artifact) -> str:
        conn = await self._conn_ready()
        row = _artifact_to_row(artifact)
        await conn.execute(
            """
            INSERT INTO artifacts (
                id, ticker, cross_tickers, type, verdict, created_at,
                last_viewed_at, archived, entry_price, target_price,
                target_date, source, headline, tagline, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                ticker = excluded.ticker,
                cross_tickers = excluded.cross_tickers,
                type = excluded.type,
                verdict = excluded.verdict,
                created_at = excluded.created_at,
                last_viewed_at = excluded.last_viewed_at,
                archived = excluded.archived,
                entry_price = excluded.entry_price,
                target_price = excluded.target_price,
                target_date = excluded.target_date,
                source = excluded.source,
                headline = excluded.headline,
                tagline = excluded.tagline,
                payload = excluded.payload
            """,
            row,
        )
        await conn.commit()
        return artifact.id

    async def get(self, artifact_id: str) -> Artifact | None:
        conn = await self._conn_ready()
        async with conn.execute(
            "SELECT payload FROM artifacts WHERE id = ?", (artifact_id,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        try:
            return Artifact.model_validate_json(row[0])
        except (ValueError, TypeError, KeyError):
            logger.warning("Corrupt artifact payload for %s", artifact_id)
            return None

    async def delete(self, artifact_id: str) -> bool:
        conn = await self._conn_ready()
        cur = await conn.execute(
            "DELETE FROM artifacts WHERE id = ?", (artifact_id,)
        )
        await conn.commit()
        return cur.rowcount > 0

    async def list_by_ticker(
        self,
        ticker: str | None = None,
        type: ArtifactType | None = None,  # noqa: A002
        include_archived: bool = False,
        limit: int = 100,
    ) -> list[ArtifactSummary]:
        conn = await self._conn_ready()
        where: list[str] = []
        params: list[Any] = []
        if ticker is not None:
            where.append("ticker = ?")
            params.append(ticker.upper())
        if type is not None:
            where.append("type = ?")
            params.append(type)
        if not include_archived:
            where.append("archived = 0")
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        sql = (
            f"SELECT {_SUMMARY_COLUMNS} FROM artifacts {clause} "
            f"ORDER BY created_at DESC LIMIT ?"
        )
        params.append(limit)
        async with conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [_row_to_summary(tuple(r)) for r in rows]

    async def list_versions(
        self,
        ticker: str,
        type: ArtifactType,  # noqa: A002
    ) -> list[ArtifactSummary]:
        return await self.list_by_ticker(
            ticker=ticker, type=type, include_archived=True, limit=1000
        )

    async def mark_viewed(self, artifact_id: str) -> None:
        artifact = await self.get(artifact_id)
        if artifact is None:
            return
        artifact.meta.last_viewed_at = _now()
        artifact.meta.archived = False
        await self.save(artifact)

    async def rebuild_summaries(self) -> int:
        """No-op: summary columns are populated at save time.

        Kept for interface parity with the legacy filesystem store, where
        ``index.json`` could drift behind the underlying artifact files.
        """
        return 0

    async def archive_stale(self, hours: int = 24) -> int:
        conn = await self._conn_ready()
        cutoff = _now()
        async with conn.execute(
            "SELECT id, created_at, last_viewed_at FROM artifacts WHERE archived = 0"
        ) as cur:
            rows = await cur.fetchall()
        archived = 0
        for id_, created_at, last_viewed_at in rows:
            last_seen = _parse_dt(last_viewed_at) or _parse_dt(created_at) or cutoff
            age_h = (cutoff - last_seen).total_seconds() / 3600
            if age_h < hours:
                continue
            # Full re-save so the embedded payload's meta.archived stays in
            # sync with the column; a bare UPDATE would leave callers of
            # get() seeing archived=False inside the payload while
            # list_by_ticker (column-driven) reports archived=True.
            artifact = await self.get(id_)
            if artifact is None:
                continue
            artifact.meta.archived = True
            await self.save(artifact)
            archived += 1
        return archived

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
