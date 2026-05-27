from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import aiosqlite
from pydantic import BaseModel

from finrobot.events import RunEvent

logger = logging.getLogger(__name__)

RunStatus = Literal["created", "running", "completed", "failed"]


_CREATE_RUNS = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    pipeline_type TEXT NOT NULL,
    ticker        TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('created', 'running', 'completed', 'failed')),
    created_at    TEXT NOT NULL,
    completed_at  TEXT,
    duration_s    REAL,
    result_text   TEXT,
    result_json   TEXT,
    error         TEXT
)
"""

_CREATE_RUN_EVENTS = """
CREATE TABLE IF NOT EXISTS run_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL REFERENCES runs(run_id),
    seq        INTEGER NOT NULL,
    event      TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

_CREATE_ARTIFACTS = """
CREATE TABLE IF NOT EXISTS artifacts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL REFERENCES runs(run_id),
    artifact_type TEXT NOT NULL,
    format        TEXT NOT NULL,
    data          BLOB,
    file_path     TEXT,
    created_at    TEXT NOT NULL
)
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_runs_ticker ON runs(ticker)",
    "CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_events_run ON run_events(run_id, seq)",
    "CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts(run_id)",
]

# Column order consumed by _row_to_run; keep the SELECT lists below in sync
# with this tuple so positional decoding matches the row layout.
_RUN_SELECT_COLUMNS = (
    "run_id, pipeline_type, ticker, status, created_at, completed_at, "
    "duration_s, result_text, result_json, error"
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
                    await conn.execute("PRAGMA journal_mode=WAL")
                    await conn.execute("PRAGMA synchronous=NORMAL")
                    await conn.execute(_CREATE_RUNS)
                    await conn.execute(_CREATE_RUN_EVENTS)
                    await conn.execute(_CREATE_ARTIFACTS)
                    for stmt in _CREATE_INDEXES:
                        await conn.execute(stmt)
                    await conn.commit()
                except BaseException:
                    await conn.close()
                    raise
                self._conn = conn
        return self._conn

    async def create_run(self, pipeline_type: str, ticker: str) -> RunRecord:
        try:
            run_id = f"run_{uuid.uuid4().hex[:12]}"
            created_at = _now()
            conn = await self._ensure_connection()
            await conn.execute(
                """
                INSERT INTO runs (run_id, pipeline_type, ticker, status, created_at)
                VALUES (?, ?, ?, 'created', ?)
                """,
                (run_id, pipeline_type, ticker.upper(), created_at),
            )
            await conn.commit()
            return RunRecord(
                run_id=run_id,
                pipeline_type=pipeline_type,
                ticker=ticker.upper(),
                status="created",
                created_at=created_at,
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

    async def list_runs(self, limit: int = 50) -> list[RunRecord]:
        conn = await self._ensure_connection()
        async with conn.execute(
            f"SELECT {_RUN_SELECT_COLUMNS} FROM runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_run(row) for row in rows]

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
        data: bytes | None = None,
        file_path: str | None = None,
    ) -> None:
        try:
            conn = await self._ensure_connection()
            await conn.execute(
                """
                INSERT INTO artifacts (run_id, artifact_type, format, data, file_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run_id, artifact_type, format, data, file_path, _now()),
            )
            await conn.commit()
        except aiosqlite.OperationalError:
            logger.exception("Failed to add artifact to run %s", run_id)
            raise

    async def list_artifacts(self, run_id: str) -> list[ArtifactRecord]:
        conn = await self._ensure_connection()
        async with conn.execute(
            """
            SELECT artifact_type, format, file_path, created_at
            FROM artifacts
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
    )
