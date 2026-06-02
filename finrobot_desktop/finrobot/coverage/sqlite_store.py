"""SQLite-backed CoverageStore — persistence for coverage groups + members.

Single db at ``~/.finrobot/coverage.db`` (own slot per the per-module
convention). Pure persistence: this layer depends only on
:mod:`finrobot.coverage.models` and :mod:`finrobot.paths` — it never imports
``engine`` or ``routes``. All orchestration (assembling the Coverage Table by
fetching prices / financials / artifacts) lives in :mod:`coverage.service`,
which sits above this store in the dependency graph (ADR-0012).

Concurrency model is copied verbatim from :class:`finrobot.run_store.RunStore`
and :class:`finrobot.artifact.sqlite_store.SqliteArtifactStore`: one lazily
opened aiosqlite connection guarded by an ``asyncio.Lock``, WAL +
``synchronous=NORMAL``, idempotent ``CREATE TABLE IF NOT EXISTS``.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from finrobot import paths as _paths
from finrobot.coverage.models import (
    CoverageGroup,
    CoverageGroupDetail,
    CoverageGroupSummary,
    CoverageMember,
)

logger = logging.getLogger(__name__)

_CREATE_GROUPS = """
CREATE TABLE IF NOT EXISTS coverage_groups (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    is_system   INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
)
"""

_CREATE_MEMBERS = """
CREATE TABLE IF NOT EXISTS coverage_members (
    group_id TEXT NOT NULL,
    ticker   TEXT NOT NULL,
    added_at TEXT NOT NULL,
    note     TEXT,
    priority INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (group_id, ticker)
)
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_coverage_members_group ON coverage_members(group_id)",
    "CREATE INDEX IF NOT EXISTS idx_coverage_groups_created ON coverage_groups(created_at)",
]


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _row_to_group(row: tuple[Any, ...]) -> CoverageGroup:
    id_, name, description, is_system, created_at, updated_at = row
    return CoverageGroup(
        id=id_,
        name=name,
        description=description,
        is_system=bool(is_system),
        created_at=_parse_dt(created_at),
        updated_at=_parse_dt(updated_at),
    )


def _row_to_member(row: tuple[Any, ...]) -> CoverageMember:
    ticker, added_at, note, priority = row
    return CoverageMember(
        ticker=ticker,
        added_at=_parse_dt(added_at),
        note=note,
        priority=priority,
    )


class CoverageStore:
    """SQLite-backed store for coverage groups and their members."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            _paths.ensure_home()
            db_path = _paths.COVERAGE_DB
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
                    await conn.execute(_CREATE_GROUPS)
                    await conn.execute(_CREATE_MEMBERS)
                    for stmt in _CREATE_INDEXES:
                        await conn.execute(stmt)
                    await conn.commit()
                except BaseException:
                    await conn.close()
                    raise
                self._conn = conn
        return self._conn

    # ── Groups ───────────────────────────────────────────────────────────────

    async def create_group(
        self,
        name: str,
        description: str | None = None,
        *,
        is_system: bool = False,
    ) -> CoverageGroup:
        conn = await self._conn_ready()
        group_id = f"cov_{uuid.uuid4().hex[:12]}"
        now = _now()
        await conn.execute(
            """
            INSERT INTO coverage_groups (id, name, description, is_system, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (group_id, name, description, 1 if is_system else 0, _iso(now), _iso(now)),
        )
        await conn.commit()
        return CoverageGroup(
            id=group_id,
            name=name,
            description=description,
            is_system=is_system,
            created_at=now,
            updated_at=now,
        )

    async def list_groups(self) -> list[CoverageGroupSummary]:
        conn = await self._conn_ready()
        async with conn.execute(
            """
            SELECT g.id, g.name, g.description, g.is_system, g.created_at, g.updated_at,
                   COUNT(m.ticker) AS member_count
            FROM coverage_groups g
            LEFT JOIN coverage_members m ON m.group_id = g.id
            GROUP BY g.id
            ORDER BY g.created_at ASC
            """
        ) as cur:
            rows = await cur.fetchall()
        out: list[CoverageGroupSummary] = []
        for row in rows:
            group = _row_to_group(tuple(row[:6]))
            out.append(CoverageGroupSummary(**group.model_dump(), member_count=int(row[6])))
        return out

    async def count_groups(self) -> int:
        conn = await self._conn_ready()
        async with conn.execute("SELECT COUNT(*) FROM coverage_groups") as cur:
            row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def get_group(self, group_id: str) -> CoverageGroupDetail | None:
        conn = await self._conn_ready()
        async with conn.execute(
            "SELECT id, name, description, is_system, created_at, updated_at "
            "FROM coverage_groups WHERE id = ?",
            (group_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        group = _row_to_group(tuple(row))
        members = await self.list_members(group_id)
        return CoverageGroupDetail(**group.model_dump(), members=members)

    async def update_group(
        self,
        group_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> CoverageGroupDetail | None:
        if name is None and description is None:
            return await self.get_group(group_id)
        conn = await self._conn_ready()
        async with conn.execute(
            """
            UPDATE coverage_groups SET
                name = COALESCE(?, name),
                description = COALESCE(?, description),
                updated_at = ?
            WHERE id = ?
            """,
            (name, description, _iso(_now()), group_id),
        ) as cur:
            if cur.rowcount == 0:
                return None
        await conn.commit()
        return await self.get_group(group_id)

    async def delete_group(self, group_id: str) -> bool:
        conn = await self._conn_ready()
        await conn.execute("DELETE FROM coverage_members WHERE group_id = ?", (group_id,))
        async with conn.execute("DELETE FROM coverage_groups WHERE id = ?", (group_id,)) as cur:
            deleted = cur.rowcount > 0
        await conn.commit()
        return deleted

    # ── Members ────────────────────────────────────────────────────────────────

    async def list_members(self, group_id: str) -> list[CoverageMember]:
        conn = await self._conn_ready()
        async with conn.execute(
            """
            SELECT ticker, added_at, note, priority
            FROM coverage_members WHERE group_id = ?
            ORDER BY priority DESC, added_at ASC
            """,
            (group_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_member(tuple(r)) for r in rows]

    async def add_members(
        self,
        group_id: str,
        tickers: list[str],
        *,
        note: str | None = None,
    ) -> CoverageGroupDetail | None:
        """Add tickers to a group (idempotent). Returns the updated group, or
        ``None`` if the group doesn't exist. Re-adding an existing ticker is a
        no-op (keeps its original ``added_at``)."""
        conn = await self._conn_ready()
        async with conn.execute("SELECT 1 FROM coverage_groups WHERE id = ?", (group_id,)) as cur:
            if await cur.fetchone() is None:
                return None
        now = _iso(_now())
        clean = [t.strip().upper() for t in tickers if t and t.strip()]
        for ticker in clean:
            await conn.execute(
                """
                INSERT INTO coverage_members (group_id, ticker, added_at, note, priority)
                VALUES (?, ?, ?, ?, 0)
                ON CONFLICT(group_id, ticker) DO NOTHING
                """,
                (group_id, ticker, now, note),
            )
        if clean:
            await conn.execute(
                "UPDATE coverage_groups SET updated_at = ? WHERE id = ?", (now, group_id)
            )
        await conn.commit()
        return await self.get_group(group_id)

    async def remove_member(self, group_id: str, ticker: str) -> bool:
        conn = await self._conn_ready()
        async with conn.execute(
            "DELETE FROM coverage_members WHERE group_id = ? AND ticker = ?",
            (group_id, ticker.strip().upper()),
        ) as cur:
            removed = cur.rowcount > 0
        if removed:
            await conn.execute(
                "UPDATE coverage_groups SET updated_at = ? WHERE id = ?",
                (_iso(_now()), group_id),
            )
        await conn.commit()
        return removed

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
