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
from datetime import datetime, timedelta, timezone
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

# Version of the mirror-column projection (the summary_extractor rules behind
# verdict/entry_price/target_price/target_date/tagline/headline). Bump this by
# ONE whenever those extraction rules change so that the next startup re-runs
# rebuild_summaries() over every already-stored row — otherwise old rows keep
# the value the previous extractor produced forever, since the columns are only
# written at save() time and are read as source-of-truth (BUG-065). The applied
# version is persisted in the artifacts.db header via PRAGMA user_version, so
# the backfill runs exactly once per bump, not on every boot.
SUMMARY_PROJECTION_VERSION = 1


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
        headline=(artifact.outputs.summary_text[:120] or artifact.id)
        if artifact.outputs
        else artifact.id,
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
        (artifact.outputs.summary_text[:120] or artifact.id) if artifact.outputs else artifact.id
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
                    await _paths.configure_connection(conn)
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
            "SELECT payload, archived, last_viewed_at FROM artifacts WHERE id = ?",
            (artifact_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        try:
            artifact = Artifact.model_validate_json(row[0])
        except (ValueError, TypeError, KeyError):
            logger.warning("Corrupt artifact payload for %s", artifact_id)
            return None
        # The archived/last_viewed_at COLUMNS are authoritative — they are the
        # mutable lifecycle fields list_by_ticker/count read and that
        # archive_stale flips with a bare column UPDATE (no payload rewrite).
        # The same values mirrored inside payload.meta are written only at
        # save() time and would otherwise go stale after a column-only archive,
        # so realign the payload to the columns at read time.
        artifact.meta.archived = bool(row[1])
        artifact.meta.last_viewed_at = _parse_dt(row[2])
        return artifact

    async def delete(self, artifact_id: str) -> bool:
        conn = await self._conn_ready()
        cur = await conn.execute("DELETE FROM artifacts WHERE id = ?", (artifact_id,))
        await conn.commit()
        return cur.rowcount > 0

    async def list_by_ticker(
        self,
        ticker: str | None = None,
        type: ArtifactType | None = None,  # noqa: A002
        include_archived: bool = False,
        limit: int = 100,
        tickers: set[str] | None = None,
    ) -> list[ArtifactSummary]:
        """List artifact summaries, newest first, capped at ``limit``.

        ``ticker`` (single) and ``tickers`` (a coverage-group set) are mutually
        exclusive scopes. When ``tickers`` is given the filter is pushed into
        SQL as ``ticker IN (?,?,...)`` so the LIMIT applies to the SCOPED page —
        a group whose reports predate the global newest-``limit`` page is no
        longer evicted before it can be seen (BUG-018). The empty set yields no
        rows (an empty group has no track record). ``ticker=None`` and
        ``tickers=None`` keep the global-page behavior unchanged.
        """
        conn = await self._conn_ready()
        where: list[str] = []
        params: list[Any] = []
        if ticker is not None:
            where.append("ticker = ?")
            params.append(ticker.upper())
        if tickers is not None:
            upper = sorted({t.upper() for t in tickers})
            if not upper:
                # Empty scope → no rows (don't degrade to the global page).
                return []
            placeholders = ", ".join("?" for _ in upper)
            where.append(f"ticker IN ({placeholders})")
            params.extend(upper)
        if type is not None:
            where.append("type = ?")
            params.append(type)
        if not include_archived:
            where.append("archived = 0")
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        sql = f"SELECT {_SUMMARY_COLUMNS} FROM artifacts {clause} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        async with conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [_row_to_summary(tuple(r)) for r in rows]

    async def count(
        self,
        *,
        include_archived: bool = False,
        tickers: set[str] | None = None,
        created_after: datetime | None = None,
    ) -> int:
        """Artifact count, optionally scoped to a ticker set and/or time window.

        Unlike ``list_by_ticker`` this never caps — the dashboard needs the
        true total to label "N reports in store", which a LIMIT-500 page
        silently misrepresents once the store grows past the cap.

        ``tickers`` (a coverage-group set) and ``created_after`` mirror the
        filters ``list_by_ticker`` / the hit-rate aggregation apply, so the
        caller can ask "how many artifacts fall in THIS scope+window" — the
        population the buckets actually describe (BUG-039). An empty ``tickers``
        set yields 0 (an empty group has no track record). ``created_after``
        compares against ``created_at`` because the aggregation's window cut
        filters on ``entry_date == created_at``.
        """
        conn = await self._conn_ready()
        where: list[str] = []
        params: list[Any] = []
        if not include_archived:
            where.append("archived = 0")
        if tickers is not None:
            upper = sorted({t.upper() for t in tickers})
            if not upper:
                return 0
            placeholders = ", ".join("?" for _ in upper)
            where.append(f"ticker IN ({placeholders})")
            params.extend(upper)
        if created_after is not None:
            # Stored as ``created_at.isoformat()`` (UTC, ``+00:00`` suffix);
            # the route passes a tz-aware UTC cutoff so the ISO strings sort
            # lexicographically the same as chronologically.
            where.append("created_at >= ?")
            params.append(created_after.isoformat())
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        sql = f"SELECT COUNT(*) FROM artifacts {clause}"
        async with conn.execute(sql, params) as cur:
            row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def distinct_ticker_count(self, *, include_archived: bool = False) -> int:
        """Number of distinct non-NULL tickers across the store.

        Cross-ticker artifacts (ticker IS NULL) are excluded, matching the
        dashboard's ``{s.ticker for s in summaries if s.ticker}`` semantics.
        """
        conn = await self._conn_ready()
        sql = "SELECT COUNT(DISTINCT ticker) FROM artifacts WHERE ticker IS NOT NULL"
        if not include_archived:
            sql += " AND archived = 0"
        async with conn.execute(sql) as cur:
            row = await cur.fetchone()
        return int(row[0]) if row else 0

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

    async def rebuild_summaries_if_outdated(self, version: int = SUMMARY_PROJECTION_VERSION) -> int:
        """Backfill the mirror columns once per projection-version bump.

        The applied version lives in the db header (``PRAGMA user_version``).
        When the code's ``SUMMARY_PROJECTION_VERSION`` is ahead of it (a fresh
        bump after an extractor change, or a legacy db at version 0), this runs
        the full :meth:`rebuild_summaries` re-projection and then records the
        new version so it won't run again until the next bump. Returns the
        number of rows re-projected (0 when already current). Called once on
        startup (BUG-065).
        """
        conn = await self._conn_ready()
        async with conn.execute("PRAGMA user_version") as cur:
            row = await cur.fetchone()
        applied = int(row[0]) if row else 0
        if applied >= version:
            return 0
        updated = await self.rebuild_summaries()
        # PRAGMA user_version doesn't accept a bound parameter; the value is a
        # validated int constant so interpolation is safe.
        await conn.execute(f"PRAGMA user_version = {int(version)}")
        await conn.commit()
        logger.info(
            "Mirror-column projection upgraded %d → %d (%d rows re-projected)",
            applied,
            version,
            updated,
        )
        return updated

    async def rebuild_summaries(self, batch_size: int = 500) -> int:
        """Re-project the mirror columns from every stored payload.

        The verdict / entry_price / target_price / target_date / tagline /
        headline columns are written by :func:`_artifact_to_row` ONLY at
        ``save()`` time, yet the dashboard hit-rate, recent-research strip and
        coverage counts read them as source-of-truth and never fall back to the
        payload. So whenever the ``summary_extractor`` rules evolve (a new
        recommendation shape, a fixed target-price parse), every already-stored
        row keeps the value the OLD extractor produced — permanently stale, and
        invisibly wrong because the number still looks plausible (BUG-065).

        This re-runs the current extractor over each row's payload and UPDATEs
        ONLY the mirror columns — the payload itself is untouched (no O(N·MB)
        rewrite of the raw_data snapshots) and the lifecycle columns
        (``archived`` / ``last_viewed_at``) are left alone, so this stays
        consistent with the column-only ``archive_stale`` / ``mark_viewed``
        path. Rows whose payload fails to validate are skipped and logged,
        never aborting the batch. Commits every ``batch_size`` rows so a large
        store doesn't hold a write lock for the whole pass. Returns the number
        of rows re-projected.

        Gated behind ``SUMMARY_PROJECTION_VERSION`` at startup so it only runs
        when the projection logic actually changed.
        """
        conn = await self._conn_ready()
        async with conn.execute("SELECT id, payload FROM artifacts") as cur:
            rows = await cur.fetchall()

        updated = 0
        pending = 0
        for artifact_id, payload in rows:
            try:
                artifact = Artifact.model_validate_json(payload)
            except (ValueError, TypeError, KeyError):
                logger.warning("rebuild_summaries: skipping unparseable artifact %s", artifact_id)
                continue
            target_price = extract_target_price(artifact)
            target_date = extract_target_date(artifact, target_price)
            headline = (
                (artifact.outputs.summary_text[:120] or artifact.id)
                if artifact.outputs
                else artifact.id
            )
            await conn.execute(
                """
                UPDATE artifacts SET
                    verdict = ?,
                    entry_price = ?,
                    target_price = ?,
                    target_date = ?,
                    tagline = ?,
                    headline = ?
                WHERE id = ?
                """,
                (
                    extract_verdict(artifact),
                    extract_entry_price(artifact),
                    target_price,
                    target_date.isoformat() if target_date else None,
                    extract_tagline(artifact),
                    headline,
                    artifact_id,
                ),
            )
            updated += 1
            pending += 1
            if pending >= batch_size:
                await conn.commit()
                pending = 0
        if pending:
            await conn.commit()
        if updated:
            logger.info(
                "rebuild_summaries: re-projected mirror columns for %d artifact(s)", updated
            )
        return updated

    async def archive_stale(self, hours: int = 24) -> int:
        """Flip ``archived`` on every row unviewed for ``hours``, in one UPDATE.

        Archiving is a single-column lifecycle flip, so it runs as a set-based
        ``UPDATE … SET archived = 1`` over the matching rows rather than a
        get()+save() that re-(de)serialises each full payload (raw_data
        snapshots run to MB) just to toggle one bool. The payload's mirrored
        ``meta.archived`` is realigned to the column lazily in :meth:`get`, so
        skipping the rewrite is invisible to callers.

        Staleness is ``COALESCE(last_viewed_at, created_at) <= cutoff`` where
        ``cutoff = now - hours``. The timestamps are ISO-8601 UTC strings
        (``+00:00`` suffix), so lexicographic comparison matches chronological
        order, and the cutoff is rendered the same way for an apples-to-apples
        string compare.
        """
        conn = await self._conn_ready()
        cutoff_iso = (_now() - timedelta(hours=hours)).isoformat()
        cur = await conn.execute(
            "UPDATE artifacts SET archived = 1 "
            "WHERE archived = 0 "
            "AND COALESCE(last_viewed_at, created_at) <= ?",
            (cutoff_iso,),
        )
        await conn.commit()
        return cur.rowcount

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
