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
    fairly_valued  INTEGER NULL  (1 = in-band point-target withhold; NULL→False)
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
from finrobot.engine.compute.operators.signal import Signal  # noqa: F401 — used in ArtifactSummary
from finrobot.artifact.summary_extractor import (
    extract_entry_price,
    extract_fairly_valued,
    extract_llm_narrative,
    extract_primary_provider,
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
    primary_provider TEXT,
    fairly_valued  INTEGER,
    payload        TEXT NOT NULL
)
"""

# Columns added after the table first shipped. _conn_ready ALTERs them into an
# existing db (SQLite's CREATE TABLE IF NOT EXISTS never adds columns), so an
# install upgrading across the bump keeps its store. Pair every entry with a
# SUMMARY_PROJECTION_VERSION bump so rebuild_summaries backfills the values
# from the stored payloads on next boot.
_MIGRATED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("primary_provider", "TEXT"),  # 门四溯源半, 2026-06-10
    ("fairly_valued", "INTEGER"),  # in-band point-target withhold, 2026-06-27
)

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
    "entry_price, target_price, target_date, source, headline, tagline, "
    "primary_provider, fairly_valued"
)

# Version of the mirror-column projection (the summary_extractor rules behind
# verdict/entry_price/target_price/target_date/tagline/headline). Bump this by
# ONE whenever those extraction rules change so that the next startup re-runs
# rebuild_summaries() over every already-stored row — otherwise old rows keep
# the value the previous extractor produced forever, since the columns are only
# written at save() time and are read as source-of-truth (BUG-065). The applied
# version is persisted in the artifacts.db header via PRAGMA user_version, so
# the backfill runs exactly once per bump, not on every boot.
# v2 — 2026-06-10: primary_provider column added (门四溯源半); bump so legacy
# rows get the provider backfilled from their payload's inputs.data_source.
# v3 — 2026-06-14: REVIEW→graded-call redesign (commits ③④). The verdict no
# longer carries a REVIEW state and the target can be honestly withheld
# (valuation_withheld) while the directional verdict still ships — so the
# verdict / target_price projection semantics changed. Bump so legacy rows
# re-project their mirror columns under the new extractor rules instead of
# keeping a stale REVIEW verdict / phantom target forever.
# v4 — 2026-06-27: fairly_valued column added to the projection; bump so
# existing rows backfill the in-band point-target-withhold marker from their
# stored payload (lets the version-timeline row render "Fairly Valued" rather
# than a generic "WITHHELD").
# v5 — 2026-07-07: headline projection cleaned. It was a blind
# ``summary_text[:120]`` that leaked the "# FinRobot Analysis Report\n---\n
# ## Data Collection …" markdown scaffolding into the exported-HTML timeline
# JSON (external-review defect). _headline_from_summary now skips the heading /
# rule / blank scaffolding and previews the first prose line; bump so existing
# rows re-project a clean headline instead of the leaked markdown facade.
SUMMARY_PROJECTION_VERSION = 5


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# Inline markdown emphasis chars stripped from a headline preview: ``*`` covers
# both ``**bold**`` and ``*italic*``, backticks cover ``code`` spans. ``_``/``~``
# are deliberately left alone — an underscore is far more often part of prose /
# an identifier than an emphasis marker, and blanket-stripping it would mangle
# real text.
_INLINE_MD_CHARS = "*`"
# A line made only of these (and ≥3 long) is a horizontal rule / thematic break
# (``---`` / ``***`` / ``___`` and their space-separated forms) — decoration.
_RULE_CHARS = frozenset("-*_ ")


def _strip_inline_markdown(line: str) -> str:
    """Strip leading block markers and inline emphasis from one line.

    Deliberately lightweight (no markdown parser): drop leading blockquote / list
    markers, then remove inline emphasis chars anywhere in the line.
    """
    line = line.lstrip(">+-* \t")
    for ch in _INLINE_MD_CHARS:
        line = line.replace(ch, "")
    return line.strip()


def _headline_from_summary(summary_text: str) -> str:
    """Derive a plain-text summary preview from an artifact's ``summary_text``.

    A multi-method equity_research report's ``summary_text`` is
    ``format_summary()`` output (builders.py ``_summary_text``), which opens with
    the generic ``# FinRobot Analysis Report`` / ``---`` / ``## Data Collection``
    markdown scaffolding. A blind ``summary_text[:120]`` therefore projected that
    markdown facade into the ``headline`` column — invisible in the app (the
    version-timeline row prefers ``tagline``) but embedded verbatim in the
    exported-HTML timeline JSON, where an external reviewer reads it as a
    data-pipeline defect.

    Skip the heading / horizontal-rule / blank scaffolding lines and preview the
    first line carrying real prose, stripped of light inline markdown. Fall back
    to the raw ``[:120]`` slice when every line is scaffolding, so the result is
    never emptier than the old behaviour produced (the caller keeps its
    ``or artifact.id`` guard for a genuinely empty summary).
    """
    for raw_line in summary_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # ATX heading: 1–6 leading '#' then a space (or a bare '######').
        hashes = len(line) - len(line.lstrip("#"))
        if 1 <= hashes <= 6 and (len(line) == hashes or line[hashes] == " "):
            continue
        if len(line) >= 3 and set(line) <= _RULE_CHARS:  # horizontal rule
            continue
        cleaned = _strip_inline_markdown(line)
        if cleaned:
            return cleaned[:120]
    return summary_text[:120]


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
        primary_provider,
        fairly_valued,
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
        primary_provider=primary_provider,
        # SQLite stores 0/1/NULL; NULL (legacy / un-backfilled row) → False.
        fairly_valued=bool(fairly_valued),
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
        headline=(_headline_from_summary(artifact.outputs.summary_text) or artifact.id)
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
        primary_provider=extract_primary_provider(artifact),
        fairly_valued=extract_fairly_valued(artifact),
    )


def _artifact_to_row(artifact: Artifact) -> tuple[Any, ...]:
    target_price = extract_target_price(artifact)
    target_date = extract_target_date(artifact, target_price)
    headline = (
        (_headline_from_summary(artifact.outputs.summary_text) or artifact.id)
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
        extract_primary_provider(artifact),
        1 if extract_fairly_valued(artifact) else 0,
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
                    # CREATE TABLE IF NOT EXISTS never adds columns to an
                    # existing db — ALTER the post-ship columns in so upgrading
                    # installs keep their store (values backfilled by the
                    # SUMMARY_PROJECTION_VERSION rebuild at startup).
                    async with conn.execute("PRAGMA table_info(artifacts)") as cur:
                        existing_cols = {row[1] for row in await cur.fetchall()}
                    for col_name, col_type in _MIGRATED_COLUMNS:
                        if col_name not in existing_cols:
                            await conn.execute(
                                f"ALTER TABLE artifacts ADD COLUMN {col_name} {col_type}"
                            )
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
                target_date, source, headline, tagline, primary_provider,
                fairly_valued, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                primary_provider = excluded.primary_provider,
                fairly_valued = excluded.fairly_valued,
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
            # Schema-drift self-heal: the summary columns still render this row
            # in every list, but the payload can never be deserialised again —
            # a permanent ghost the user can see but not open. Archive it
            # (column-only, payload preserved for forensics / a future
            # migration) so it drops out of default lists on first detection;
            # the detail route distinguishes this case via exists() → 410.
            logger.warning(
                "Unreadable artifact payload for %s (schema drift / corruption) — archiving",
                artifact_id,
            )
            await conn.execute("UPDATE artifacts SET archived = 1 WHERE id = ?", (artifact_id,))
            await conn.commit()
            return None
        # The archived/last_viewed_at COLUMNS are authoritative — they are the
        # mutable lifecycle fields list_by_ticker/count read and that
        # archive_stale flips with a bare column UPDATE (no payload rewrite).
        # The same values mirrored inside payload.meta are written only at
        # save() time and would otherwise go stale after a column-only archive,
        # so realign the payload to the columns at read time.
        artifact.meta.archived = bool(row[1])
        artifact.meta.last_viewed_at = _parse_dt(row[2])
        if not artifact.outputs.llm_narrative:
            artifact.outputs.llm_narrative = extract_llm_narrative(artifact)
        return artifact

    async def exists(self, artifact_id: str) -> bool:
        """True when a row with this id exists, readable or not.

        Lets callers split ``get() is None`` into its two real cases: the id
        was never stored (404) vs the row exists but its payload no longer
        deserialises after schema drift (410 — gone, with an explanation).
        """
        conn = await self._conn_ready()
        async with conn.execute("SELECT 1 FROM artifacts WHERE id = ?", (artifact_id,)) as cur:
            return await cur.fetchone() is not None

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
        if limit < 1:
            raise ValueError(f"limit must be >= 1, got {limit}")
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
        """Stamp ``last_viewed_at`` and un-archive, as a column-only UPDATE.

        ``last_viewed_at`` / ``archived`` are the mutable lifecycle columns —
        the same ones ``archive_stale`` flips without touching the payload, and
        :meth:`get` realigns ``payload.meta`` to them at read time. The old
        get()+save() round-trip re-(de)serialised the full multi-MB payload to
        change two scalars, and silently skipped rows whose payload no longer
        validates (which is exactly when the lifecycle columns still matter).
        Missing ids are a no-op (rowcount 0), matching the old behaviour.
        """
        conn = await self._conn_ready()
        await conn.execute(
            "UPDATE artifacts SET last_viewed_at = ?, archived = 0 WHERE id = ?",
            (_now().isoformat(), artifact_id),
        )
        await conn.commit()

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
                (_headline_from_summary(artifact.outputs.summary_text) or artifact.id)
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
                    headline = ?,
                    primary_provider = ?,
                    fairly_valued = ?
                WHERE id = ?
                """,
                (
                    extract_verdict(artifact),
                    extract_entry_price(artifact),
                    target_price,
                    target_date.isoformat() if target_date else None,
                    extract_tagline(artifact),
                    headline,
                    extract_primary_provider(artifact),
                    1 if extract_fairly_valued(artifact) else 0,
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
        if hours < 0:
            raise ValueError(f"hours must be >= 0, got {hours}")
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
