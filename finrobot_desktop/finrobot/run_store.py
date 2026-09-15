from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import aiosqlite
from pydantic import BaseModel, Field

from finrobot.events import RunEvent
from finrobot.paths import configure_connection

logger = logging.getLogger(__name__)

RunStatus = Literal["created", "running", "completed", "failed", "cancelled"]

# Single authority for "this run will never change again". Every consumer that
# branches on terminality (SSE poll loops, reattach filters, event pruning)
# imports this set instead of hand-writing {completed, failed} — that literal
# pair is exactly how `cancelled` would get silently excluded and wedge an SSE
# stream forever.
TERMINAL_RUN_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})

# How long the per-run SSE event log is retained after a run reaches a terminal
# state. run_events accumulates ~12-22 rows per run and was never cleaned, so a
# long-lived desktop install grew the table without bound while every row past
# the live stream's resume window is dead weight (Last-Event-ID resume only
# matters for an *active* run). We keep the runs row itself (it's the history
# the Coverage overview reads) and only drop the bulky event log of runs whose
# completed_at is older than this many days. Pruned on startup (BUG-050).
RUN_EVENT_RETENTION_DAYS = 7


_CREATE_RUNS = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    pipeline_type TEXT NOT NULL,
    ticker        TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('created', 'running', 'completed', 'failed', 'cancelled')),
    created_at    TEXT NOT NULL,
    completed_at  TEXT,
    duration_s    REAL,
    result_text   TEXT,
    result_json   TEXT,
    error         TEXT,
    language      TEXT,
    source_artifact_id TEXT
)
"""

# Columns added after the initial schema shipped. Applied idempotently on every
# connection open via ALTER TABLE (SQLite has no "ADD COLUMN IF NOT EXISTS"), so
# existing on-disk run DBs gain the column without a manual migration. Keep the
# CREATE statement above in sync — fresh DBs get the column from CREATE directly.
_RUN_COLUMN_MIGRATIONS = (
    ("language", "ALTER TABLE runs ADD COLUMN language TEXT"),
    ("source_artifact_id", "ALTER TABLE runs ADD COLUMN source_artifact_id TEXT"),
)

_CREATE_RUN_EVENTS = """
CREATE TABLE IF NOT EXISTS run_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL REFERENCES runs(run_id),
    seq        INTEGER NOT NULL,
    event      TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

# run→artifact link table. Distinct from the canonical artifact store in
# artifacts.db (artifact/sqlite_store.py); named run_artifacts to avoid the
# collision. file_path holds the canonical artifact's API path
# (/api/artifacts/<id>). No data BLOB: artifact bodies live in artifacts.db,
# this table only records which artifact a run produced.
_CREATE_ARTIFACTS = """
CREATE TABLE IF NOT EXISTS run_artifacts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL REFERENCES runs(run_id),
    artifact_type TEXT NOT NULL,
    format        TEXT NOT NULL,
    file_path     TEXT,
    created_at    TEXT NOT NULL
)
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_runs_ticker ON runs(ticker)",
    "CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_events_run ON run_events(run_id, seq)",
    "CREATE INDEX IF NOT EXISTS idx_run_artifacts_run ON run_artifacts(run_id)",
]

# Column order consumed by _row_to_run; keep the SELECT lists below in sync
# with this tuple so positional decoding matches the row layout.
_RUN_SELECT_COLUMNS = (
    "run_id, pipeline_type, ticker, status, created_at, completed_at, "
    "duration_s, result_text, result_json, error, language, source_artifact_id"
)


class RunRecord(BaseModel):
    run_id: str
    pipeline_type: str
    ticker: str
    status: RunStatus
    created_at: str
    completed_at: str | None = None
    duration_s: float | None = None
    result_text: str | None = None
    result_json: dict[str, Any] | None = None
    error: str | None = None
    language: str | None = Field(
        default=None,
        description=(
            "Output language requested for this run ('en'|'zh'), set from the UI "
            "locale at creation and passed to Pipeline.execute(lang=). None → "
            "execute falls back to settings.language. Legacy rows are NULL."
        ),
    )
    source_artifact_id: str | None = Field(
        default=None,
        description=(
            "When this run is a re-run/iteration triggered from an existing "
            "artifact, the id of that source artifact. Threaded to "
            "Pipeline.execute(source_artifact_id=) and stamped onto the new "
            "artifact's meta.parent_artifact_id to build the version lineage "
            "the diff view follows. None for fresh runs / legacy rows."
        ),
    )


class StoredRunEvent(BaseModel):
    seq: int
    event: RunEvent
    created_at: str


class ArtifactRecord(BaseModel):
    artifact_type: str
    format: str
    file_path: str | None = None
    created_at: str


class RunStore:
    """SQLite-backed run, event, and artifact metadata store."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            from finrobot.paths import RUNS_DB, ensure_home

            ensure_home()
            db_path = RUNS_DB
        self._db_path = str(db_path)
        self._conn: aiosqlite.Connection | None = None
        self._conn_lock = asyncio.Lock()

    async def _ensure_connection(self) -> aiosqlite.Connection:
        async with self._conn_lock:
            if self._conn is None:
                Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
                conn = await aiosqlite.connect(self._db_path)
                try:
                    await configure_connection(conn)
                    await conn.execute(_CREATE_RUNS)
                    # Column migrations BEFORE the CHECK rebuild: the rebuild
                    # copies an explicit 12-column list, so a legacy table must
                    # gain language/source_artifact_id first.
                    await _apply_run_column_migrations(conn)
                    await _migrate_runs_status_check(conn)
                    await conn.execute(_CREATE_RUN_EVENTS)
                    await conn.execute(_CREATE_ARTIFACTS)
                    # Indexes AFTER the CHECK rebuild — DROP TABLE inside the
                    # rebuild drops the runs indexes with it; IF NOT EXISTS
                    # recreates them here.
                    for stmt in _CREATE_INDEXES:
                        await conn.execute(stmt)
                    await conn.commit()
                except BaseException:
                    await conn.close()
                    raise
                self._conn = conn
        return self._conn

    async def create_run(
        self,
        pipeline_type: str,
        ticker: str,
        language: str | None = None,
        source_artifact_id: str | None = None,
    ) -> RunRecord:
        try:
            run_id = f"run_{uuid.uuid4().hex[:12]}"
            created_at = _now()
            conn = await self._ensure_connection()
            await conn.execute(
                """
                INSERT INTO runs
                    (run_id, pipeline_type, ticker, status, created_at, language, source_artifact_id)
                VALUES (?, ?, ?, 'created', ?, ?, ?)
                """,
                (run_id, pipeline_type, ticker.upper(), created_at, language, source_artifact_id),
            )
            await conn.commit()
            return RunRecord(
                run_id=run_id,
                pipeline_type=pipeline_type,
                ticker=ticker.upper(),
                status="created",
                created_at=created_at,
                language=language,
                source_artifact_id=source_artifact_id,
            )
        except aiosqlite.OperationalError:
            logger.exception("Failed to create run for %s/%s", pipeline_type, ticker)
            raise

    async def update_run(
        self,
        run_id: str,
        *,
        status: RunStatus | None = None,
        completed_at: str | None = None,
        duration_s: float | None = None,
        result_text: str | None = None,
        result_json: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        try:
            conn = await self._ensure_connection()
            async with conn.execute(
                """
                UPDATE runs SET
                    status = COALESCE(?, status),
                    completed_at = COALESCE(?, completed_at),
                    duration_s = COALESCE(?, duration_s),
                    result_text = COALESCE(?, result_text),
                    result_json = COALESCE(?, result_json),
                    error = COALESCE(?, error)
                WHERE run_id = ?
                """,
                (
                    status,
                    completed_at,
                    duration_s,
                    result_text,
                    json.dumps(result_json) if result_json is not None else None,
                    error,
                    run_id,
                ),
            ) as cursor:
                if cursor.rowcount == 0:
                    raise KeyError(f"Run not found: {run_id}")
            await conn.commit()
        except KeyError:
            raise
        except aiosqlite.OperationalError:
            logger.exception("Failed to update run %s", run_id)
            raise

    async def get_run(self, run_id: str) -> RunRecord | None:
        conn = await self._ensure_connection()
        async with conn.execute(
            f"SELECT {_RUN_SELECT_COLUMNS} FROM runs WHERE run_id = ?",
            (run_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_run(row)

    async def reconcile_orphaned_runs(self) -> int:
        """Fail runs left mid-flight by a previous process.

        Run tasks live in ``app.state.run_tasks`` (in-memory), so a server
        restart abandons every ``created``/``running`` row — the asyncio task
        is gone but the DB still says "running", which would wedge the SSE
        stream forever (it only breaks on a terminal status) and show phantom
        in-progress runs in the Coverage overview. Called once on startup to
        mark them ``failed``. Returns the number reconciled.

        Goes through ``finish_run`` per orphan rather than one bulk UPDATE:
        the bulk path flipped status without appending a ``run.failed`` event,
        so a desktop that reattached to the run's SSE stream right after the
        restart saw the stream close with no terminal event — the UI card hung
        on its last pre-restart step forever instead of showing the failure.
        finish_run also preserves the event-before-status ordering invariant
        (BUG-034) that the bulk UPDATE bypassed.
        """
        from finrobot.events import RunFailed

        error_msg = "interrupted by server restart"
        conn = await self._ensure_connection()
        async with conn.execute(
            "SELECT run_id FROM runs WHERE status IN ('created', 'running')"
        ) as cursor:
            orphan_ids = [str(row[0]) for row in await cursor.fetchall()]
        completed_at = _now()
        for run_id in orphan_ids:
            await self.finish_run(
                run_id,
                RunFailed(event="run.failed", run_id=run_id, error=error_msg),
                status="failed",
                completed_at=completed_at,
                error=error_msg,
            )
        if orphan_ids:
            logger.info("Reconciled %d orphaned run(s) to failed on startup", len(orphan_ids))
        return len(orphan_ids)

    async def prune_run_events(self, retention_days: int = RUN_EVENT_RETENTION_DAYS) -> int:
        """Delete the SSE event log of long-finished runs.

        run_events grew unbounded: every run appended ~12-22 rows that were
        never cleaned, so a single shared aiosqlite connection paid an
        ever-larger ``run_events`` table on every ``get_events_after`` poll
        (BUG-050). The events of a *terminal* run older than ``retention_days``
        are pure dead weight — Last-Event-ID resume only matters while a run is
        live. We drop those event rows but keep the ``runs`` rows themselves
        (the Coverage overview's history). Returns the number of event rows
        deleted.
        """
        cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=retention_days)).isoformat()
        conn = await self._ensure_connection()
        async with conn.execute(
            """
            DELETE FROM run_events
            WHERE run_id IN (
                SELECT run_id FROM runs
                WHERE status IN ('completed', 'failed', 'cancelled')
                  AND completed_at IS NOT NULL
                  AND completed_at < ?
            )
            """,
            (cutoff,),
        ) as cursor:
            count = cursor.rowcount
        await conn.commit()
        if count:
            logger.info(
                "Pruned %d run_events row(s) for runs terminal > %d days", count, retention_days
            )
        return count

    async def list_runs(
        self, limit: int = 50, statuses: Sequence[str] | None = None
    ) -> list[RunRecord]:
        """Recent runs, newest first; ``statuses`` narrows to that status set.

        The status filter powers the desktop's restart-reattach (GET
        /api/runs?status=created,running): after a webview reload the in-memory
        run map is gone while backend pipelines keep executing, so the UI asks
        for the non-terminal rows to re-subscribe their SSE streams. Filtering
        in SQL (not post-hoc on a LIMITed page) so an active run can never be
        pushed off the page by newer terminal rows.
        """
        conn = await self._ensure_connection()
        where = ""
        params: tuple[Any, ...] = ()
        if statuses:
            placeholders = ",".join("?" * len(statuses))
            where = f" WHERE status IN ({placeholders})"
            params = tuple(statuses)
        async with conn.execute(
            f"SELECT {_RUN_SELECT_COLUMNS} FROM runs{where} ORDER BY created_at DESC LIMIT ?",
            (*params, limit),
        ) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_run(row) for row in rows]

    async def latest_runs_by_ticker(self, tickers: list[str]) -> dict[str, RunRecord]:
        """Most-recent run per ticker, in one query. Empty dict for no tickers.

        Powers the Coverage overview's run-status column / needs-refresh:
        surfaces an in-flight ``running`` run or a ``failed`` last attempt per
        covered ticker without N round-trips.
        """
        if not tickers:
            return {}
        uppers = [t.upper() for t in tickers]
        placeholders = ",".join("?" * len(uppers))
        conn = await self._ensure_connection()
        async with conn.execute(
            f"SELECT {_RUN_SELECT_COLUMNS} FROM runs "
            f"WHERE ticker IN ({placeholders}) ORDER BY created_at DESC",
            uppers,
        ) as cursor:
            rows = await cursor.fetchall()
        out: dict[str, RunRecord] = {}
        for row in rows:
            record = _row_to_run(row)
            out.setdefault(record.ticker, record)  # newest first → first wins
        return out

    async def finish_run(
        self,
        run_id: str,
        terminal_event: RunEvent,
        *,
        status: RunStatus,
        completed_at: str | None = None,
        duration_s: float | None = None,
        result_text: str | None = None,
        result_json: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Transition a run to a terminal state — event FIRST, status second.

        The BUG-034 ordering invariant, made mechanical: the SSE poll loop
        breaks the moment it observes status∈TERMINAL_RUN_STATUSES and then
        fetches trailing events, so the terminal event MUST be committed
        before the status flip or a poll landing in the gap never emits it
        (the client EventSource then reconnect-storms into the "请检查后端服务"
        banner). An invariant every event writer must share belongs in the
        store, not in each call site's prose.
        """
        await self.append_event(run_id, terminal_event)
        await self.update_run(
            run_id,
            status=status,
            completed_at=completed_at,
            duration_s=duration_s,
            result_text=result_text,
            result_json=result_json,
            error=error,
        )

    async def append_event(self, run_id: str, event: RunEvent) -> int:
        try:
            conn = await self._ensure_connection()
            now = _now()
            async with conn.execute(
                """
                INSERT INTO run_events (run_id, seq, event, created_at)
                VALUES (
                    ?,
                    (SELECT COALESCE(MAX(seq), 0) + 1
                     FROM run_events WHERE run_id = ?),
                    ?, ?
                )
                """,
                (run_id, run_id, json.dumps(event), now),
            ) as cursor:
                seq = cursor.lastrowid
            # Fetch the actual seq value (lastrowid is the AUTOINCREMENT id, not seq)
            async with conn.execute("SELECT seq FROM run_events WHERE id = ?", (seq,)) as cursor:
                row = await cursor.fetchone()
            await conn.commit()
            if row is None:
                raise RuntimeError(f"Failed to read back seq for run {run_id}")
            return int(row[0])
        except aiosqlite.OperationalError:
            logger.exception("Failed to append event to run %s", run_id)
            raise

    async def get_events_after(self, run_id: str, last_seq: int = 0) -> list[StoredRunEvent]:
        conn = await self._ensure_connection()
        async with conn.execute(
            """
            SELECT seq, event, created_at
            FROM run_events
            WHERE run_id = ? AND seq > ?
            ORDER BY seq ASC
            """,
            (run_id, last_seq),
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            StoredRunEvent(
                seq=int(row[0]),
                event=json.loads(row[1]),
                created_at=str(row[2]),
            )
            for row in rows
        ]

    async def add_artifact(
        self,
        run_id: str,
        *,
        artifact_type: str,
        format: str,
        file_path: str | None = None,
    ) -> None:
        try:
            conn = await self._ensure_connection()
            await conn.execute(
                """
                INSERT INTO run_artifacts (run_id, artifact_type, format, file_path, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, artifact_type, format, file_path, _now()),
            )
            await conn.commit()
        except aiosqlite.OperationalError:
            logger.exception("Failed to add artifact to run %s", run_id)
            raise

    async def remove_artifact_links(self, artifact_id: str) -> int:
        """Drop run_artifacts rows pointing at a deleted canonical artifact.

        run_artifacts only records which artifact a run produced (the body
        lives in artifacts.db). When DELETE /api/artifacts/{id} removes the
        canonical artifact, the link rows here used to dangle forever — GET
        /api/runs/{run_id} kept listing the artifact and the UI's open-report
        path 404'd on a ghost. Linkage is by the stored API path (the only
        artifact identity this table holds). Returns the rows removed.
        """
        try:
            conn = await self._ensure_connection()
            async with conn.execute(
                "DELETE FROM run_artifacts WHERE file_path = ?",
                (f"/api/artifacts/{artifact_id}",),
            ) as cursor:
                count = cursor.rowcount
            await conn.commit()
            return count
        except aiosqlite.OperationalError:
            logger.exception("Failed to remove run_artifacts links for %s", artifact_id)
            raise

    async def list_artifacts(self, run_id: str) -> list[ArtifactRecord]:
        conn = await self._ensure_connection()
        async with conn.execute(
            """
            SELECT artifact_type, format, file_path, created_at
            FROM run_artifacts
            WHERE run_id = ?
            ORDER BY created_at ASC
            """,
            (run_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            ArtifactRecord(
                artifact_type=str(row[0]),
                format=str(row[1]),
                file_path=row[2],
                created_at=str(row[3]),
            )
            for row in rows
        ]

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _row_to_run(row: Any) -> RunRecord:
    result_raw = row[8]
    return RunRecord(
        run_id=str(row[0]),
        pipeline_type=str(row[1]),
        ticker=str(row[2]),
        status=row[3],
        created_at=str(row[4]),
        completed_at=row[5],
        duration_s=row[6],
        result_text=row[7],
        result_json=json.loads(result_raw) if result_raw else None,
        error=row[9],
        language=row[10],
        source_artifact_id=row[11],
    )


async def _migrate_runs_status_check(conn: aiosqlite.Connection) -> None:
    """Rebuild ``runs`` when its CHECK constraint predates the 'cancelled' status.

    SQLite cannot ALTER a CHECK constraint, so on-disk DBs created before the
    cancel feature would reject ``UPDATE runs SET status='cancelled'`` with an
    IntegrityError forever. Detection reads the stored CREATE sql from
    sqlite_master; a fresh DB (created by today's ``_CREATE_RUNS``) already
    contains 'cancelled' and skips the rebuild entirely.

    Rebuild pattern: CREATE new → INSERT…SELECT → DROP old → RENAME new. The
    old ``runs`` table is never RENAMEd (only dropped), because SQLite ≥3.25
    rewrites other tables' REFERENCES clauses to follow a rename —
    run_events/run_artifacts must keep pointing at the name ``runs``. The whole
    dance runs inside one IMMEDIATE transaction so a crash mid-migration can't
    strand the data in the temp table; a leftover temp from a previous crashed
    attempt is dropped before retrying.
    """
    async with conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='runs'"
    ) as cursor:
        row = await cursor.fetchone()
    if row is None or row[0] is None or "'cancelled'" in row[0]:
        return
    logger.info("Migrating runs table: rebuilding status CHECK to admit 'cancelled'")
    await conn.execute("DROP TABLE IF EXISTS runs_check_migration_new")
    await conn.execute("BEGIN IMMEDIATE")
    try:
        await conn.execute(
            _CREATE_RUNS.replace(
                "CREATE TABLE IF NOT EXISTS runs ",
                "CREATE TABLE runs_check_migration_new ",
            )
        )
        await conn.execute(
            f"INSERT INTO runs_check_migration_new ({_RUN_SELECT_COLUMNS}) "
            f"SELECT {_RUN_SELECT_COLUMNS} FROM runs"
        )
        await conn.execute("DROP TABLE runs")
        await conn.execute("ALTER TABLE runs_check_migration_new RENAME TO runs")
        await conn.commit()
    except BaseException:
        await conn.rollback()
        raise


async def _apply_run_column_migrations(conn: aiosqlite.Connection) -> None:
    """Idempotently add columns introduced after the initial runs schema.

    SQLite lacks ADD COLUMN IF NOT EXISTS, so we read the current columns from
    PRAGMA table_info and only ALTER for the ones that are missing. Safe to call
    on every connection open; a no-op once the column exists.
    """
    cursor = await conn.execute("PRAGMA table_info(runs)")
    existing = {row[1] for row in await cursor.fetchall()}
    await cursor.close()
    for column, ddl in _RUN_COLUMN_MIGRATIONS:
        if column not in existing:
            await conn.execute(ddl)
