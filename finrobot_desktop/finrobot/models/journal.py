"""Decision Journal models + SQLite persistence.

Architecture note: this module lives in finrobot/models/ (NOT engine/models/)
because it contains I/O (SQLite). The engine/models/ leaf layer is pure-Pydantic
with no I/O.

Coding discipline:
- All public sync methods are thin; callers must wrap them with asyncio.to_thread.
- Exceptions are raised with specific types; callers handle them.
- Config via injected db_path or Path.home() default; never reads env vars directly.
- No print(); logging only.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from finrobot.paths import configure_connection_sync

logger = logging.getLogger(__name__)


class JournalEntryCreate(BaseModel):
    ticker: str
    action: Literal["BUY", "SELL", "HOLD"]
    entry_price: float
    target_price: float | None = None
    thesis: str
    notes: str | None = None


class JournalEntry(BaseModel):
    id: str
    ticker: str
    action: Literal["BUY", "SELL", "HOLD"]
    entry_price: float
    target_price: float | None = None
    thesis: str
    notes: str | None = None
    created_at: str  # ISO-8601 UTC
    # Enriched fields — populated on read, never stored in SQLite
    current_price: float | None = None
    pnl_pct: float | None = None
    pnl_abs: float | None = None


class JournalStore:
    """SQLite-backed journal storage.

    All public methods are synchronous. Async route handlers must call them
    inside ``asyncio.to_thread`` to avoid blocking the event loop.

    Thread safety: sqlite3 connections are created per-call (not shared),
    so concurrent threads each get their own connection.  WAL mode on the
    database file (set at ``_init_db`` time) allows concurrent readers with
    one writer.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            from finrobot.paths import JOURNAL_DB, ensure_home

            ensure_home()
            db_path = JOURNAL_DB
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """Open a per-call connection with WAL mode for concurrency safety."""
        conn = sqlite3.connect(self._db_path)
        configure_connection_sync(conn)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS journal (
                    id          TEXT PRIMARY KEY,
                    ticker      TEXT NOT NULL,
                    action      TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    target_price REAL,
                    thesis      TEXT NOT NULL,
                    notes       TEXT,
                    created_at  TEXT NOT NULL
                )
            """)
            conn.commit()

    def create(self, entry: JournalEntryCreate) -> JournalEntry:
        """Insert a new journal entry and return the persisted record."""
        entry_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO journal VALUES (?,?,?,?,?,?,?,?)",
                (
                    entry_id,
                    entry.ticker.upper(),
                    entry.action,
                    entry.entry_price,
                    entry.target_price,
                    entry.thesis,
                    entry.notes,
                    now,
                ),
            )
            conn.commit()
        logger.debug("JournalStore.create: id=%s ticker=%s", entry_id, entry.ticker)
        return JournalEntry(
            id=entry_id,
            ticker=entry.ticker.upper(),
            action=entry.action,
            entry_price=entry.entry_price,
            target_price=entry.target_price,
            thesis=entry.thesis,
            notes=entry.notes,
            created_at=now,
        )

    def list_all(self) -> list[JournalEntry]:
        """Return all entries ordered by creation time (newest first)."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM journal ORDER BY created_at DESC").fetchall()
        return [JournalEntry(**dict(r)) for r in rows]

    def get(self, entry_id: str) -> JournalEntry | None:
        """Return a single entry by id, or None if not found."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM journal WHERE id = ?", (entry_id,)).fetchone()
        return JournalEntry(**dict(row)) if row else None

    def update(self, entry_id: str, data: dict[str, object]) -> JournalEntry | None:
        """Partial-update allowed fields; return updated entry or None if missing.

        Only the keys in ``allowed`` are written. Unknown / computed fields
        (current_price, pnl_pct, pnl_abs, id, created_at) are silently ignored.
        Column names come from a hard-coded whitelist so the f-string SET clause
        is not an injection risk.
        """
        entry = self.get(entry_id)
        if not entry:
            return None
        allowed: set[str] = {"ticker", "action", "entry_price", "target_price", "thesis", "notes"}
        updates = {k: v for k, v in data.items() if k in allowed and v is not None}
        if not updates:
            return entry
        # Column names are from the whitelist above — not user-controlled strings.
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values: list[object] = list(updates.values()) + [entry_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE journal SET {set_clause} WHERE id = ?", values)
            conn.commit()
        return self.get(entry_id)

    def delete(self, entry_id: str) -> bool:
        """Delete an entry. Returns True if a row was deleted, False otherwise."""
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM journal WHERE id = ?", (entry_id,))
            conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            logger.debug("JournalStore.delete: id=%s", entry_id)
        return deleted
