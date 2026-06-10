"""runs 表 status CHECK 约束迁移(admit 'cancelled')。

On-disk DBs created before the cancel feature carry
``CHECK (status IN ('created','running','completed','failed'))`` — SQLite can't
ALTER a CHECK, so RunStore rebuilds the table on open (create new → copy →
drop old → rename). These tests pin: legacy data survives byte-for-byte, the
rebuilt table accepts 'cancelled', the rebuild never renames the old ``runs``
(so run_events/run_artifacts keep referencing the name ``runs``), and fresh /
already-migrated DBs skip the rebuild.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from finrobot.events import RunCancelled
from finrobot.run_store import RunStore

# The exact CREATE shipped before the cancel feature — old CHECK, and without
# the language/source_artifact_id columns (they arrived via column migrations),
# so this also exercises column-migration-before-rebuild ordering.
_LEGACY_CREATE_RUNS = """
CREATE TABLE runs (
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

_LEGACY_CREATE_RUN_EVENTS = """
CREATE TABLE run_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL REFERENCES runs(run_id),
    seq        INTEGER NOT NULL,
    event      TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""


def _build_legacy_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_LEGACY_CREATE_RUNS)
        conn.execute(_LEGACY_CREATE_RUN_EVENTS)
        conn.execute(
            "INSERT INTO runs (run_id, pipeline_type, ticker, status, created_at, "
            "completed_at, duration_s, result_text, result_json, error) "
            "VALUES ('run_old1', 'research', 'AAPL', 'completed', "
            "'2026-01-01T00:00:00+00:00', '2026-01-01T00:05:00+00:00', 300.0, "
            "'summary', '{\"structured_data\": {}}', NULL)"
        )
        conn.execute(
            "INSERT INTO runs (run_id, pipeline_type, ticker, status, created_at) "
            "VALUES ('run_old2', 'dcf', 'MSFT', 'running', '2026-01-02T00:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO run_events (run_id, seq, event, created_at) VALUES "
            '(\'run_old1\', 1, \'{"event": "run.started", "run_id": "run_old1", '
            '"pipeline_type": "research", "ticker": "AAPL", "total_steps": 1}\', '
            "'2026-01-01T00:00:00+00:00')"
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_legacy_db_is_rebuilt_and_accepts_cancelled(tmp_path: Path) -> None:
    db_path = tmp_path / "runs.db"
    _build_legacy_db(db_path)

    store = RunStore(db_path)
    # The very write the old CHECK rejected with IntegrityError:
    await store.finish_run(
        "run_old2",
        RunCancelled(event="run.cancelled", run_id="run_old2", ticker="MSFT"),
        status="cancelled",
        completed_at="2026-06-10T00:00:00+00:00",
    )
    cancelled = await store.get_run("run_old2")
    assert cancelled is not None and cancelled.status == "cancelled"
    await store.close()


@pytest.mark.asyncio
async def test_legacy_rows_survive_rebuild_intact(tmp_path: Path) -> None:
    db_path = tmp_path / "runs.db"
    _build_legacy_db(db_path)

    store = RunStore(db_path)
    old = await store.get_run("run_old1")
    assert old is not None
    assert old.status == "completed"
    assert old.ticker == "AAPL"
    assert old.duration_s == 300.0
    assert old.result_text == "summary"
    assert old.result_json == {"structured_data": {}}
    assert old.language is None  # column added by migration, NULL for legacy rows
    assert old.source_artifact_id is None
    # The pre-existing event log is untouched by the runs-table rebuild.
    events = await store.get_events_after("run_old1", 0)
    assert len(events) == 1 and events[0].event["event"] == "run.started"
    await store.close()


@pytest.mark.asyncio
async def test_rebuild_preserves_referencing_tables_and_indexes(tmp_path: Path) -> None:
    """run_events must still reference the table NAME ``runs`` after the
    rebuild (the old table is dropped, never renamed — a rename would drag
    other tables' REFERENCES clauses along), and the runs indexes dropped with
    the old table are recreated."""
    db_path = tmp_path / "runs.db"
    _build_legacy_db(db_path)

    store = RunStore(db_path)
    await store._ensure_connection()
    await store.close()

    conn = sqlite3.connect(db_path)
    try:
        runs_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='runs'"
        ).fetchone()[0]
        assert "'cancelled'" in runs_sql
        events_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='run_events'"
        ).fetchone()[0]
        assert "REFERENCES runs(run_id)" in events_sql
        assert "runs_check_migration_new" not in events_sql
        # No temp table left behind.
        leftover = conn.execute(
            "SELECT name FROM sqlite_master WHERE name='runs_check_migration_new'"
        ).fetchone()
        assert leftover is None
        index_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='runs'"
            ).fetchall()
        }
        assert {"idx_runs_ticker", "idx_runs_created"} <= index_names
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_crashed_previous_attempt_leftover_is_recovered(tmp_path: Path) -> None:
    """A temp table stranded by a crash mid-previous-migration must not block
    the retry (it is dropped before rebuilding)."""
    db_path = tmp_path / "runs.db"
    _build_legacy_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE runs_check_migration_new (junk TEXT)")
    conn.commit()
    conn.close()

    store = RunStore(db_path)
    record = await store.get_run("run_old1")
    assert record is not None and record.status == "completed"
    await store.update_run("run_old2", status="cancelled")
    await store.close()


@pytest.mark.asyncio
async def test_fresh_db_skips_rebuild(tmp_path: Path) -> None:
    """A DB created by today's schema already admits 'cancelled' — opening it
    twice must not rebuild (sqlite_master rootpage churn is invisible, so we
    pin behaviour: writes work and the CREATE sql already contains the new
    status before the second open)."""
    db_path = tmp_path / "runs.db"
    store = RunStore(db_path)
    record = await store.create_run("research", "AAPL")
    await store.update_run(record.run_id, status="cancelled")
    await store.close()

    again = RunStore(db_path)
    reread = await again.get_run(record.run_id)
    assert reread is not None and reread.status == "cancelled"
    await again.close()
