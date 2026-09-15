"""One-shot migration: filesystem JSON → SQLite ArtifactStore.

Covers:
  - empty legacy dir → returns 0
  - N JSON files → returns N inserted
  - index.json files are ignored
  - re-run is idempotent (ON CONFLICT UPDATE)
  - corrupt JSON files are skipped, not fatal
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from finrobot.artifact.migrate import migrate_filesystem_to_sqlite
from finrobot.artifact.sqlite_store import SqliteArtifactStore
from tests.artifact.conftest import _make_artifact


@pytest_asyncio.fixture
async def store(tmp_path: Path) -> AsyncIterator[SqliteArtifactStore]:
    """Per-test SqliteArtifactStore; close() at teardown to keep aiosqlite
    from racing the event-loop teardown and emitting noisy warnings."""
    s = SqliteArtifactStore(db_path=tmp_path / "new.db")
    try:
        yield s
    finally:
        await s.close()


def _write_artifact_json(base: Path, ticker: str, artifact_id: str) -> None:
    art = _make_artifact(id=artifact_id, ticker=ticker)
    tdir = base / ticker
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / f"{artifact_id}.json").write_text(art.model_dump_json())


@pytest.mark.asyncio
async def test_migrate_empty_legacy_returns_zero(
    tmp_path: Path, store: SqliteArtifactStore
) -> None:
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    n = await migrate_filesystem_to_sqlite(legacy_root=legacy, store=store)
    assert n == 0


@pytest.mark.asyncio
async def test_migrate_nonexistent_returns_zero(tmp_path: Path, store: SqliteArtifactStore) -> None:
    """Legacy path may not exist on a fresh install — return 0, don't crash."""
    n = await migrate_filesystem_to_sqlite(legacy_root=tmp_path / "does_not_exist", store=store)
    assert n == 0


@pytest.mark.asyncio
async def test_migrate_inserts_all_json_files(tmp_path: Path, store: SqliteArtifactStore) -> None:
    legacy = tmp_path / "legacy"
    _write_artifact_json(legacy, "AAPL", "art_a1")
    _write_artifact_json(legacy, "AAPL", "art_a2")
    _write_artifact_json(legacy, "MSFT", "art_m1")

    n = await migrate_filesystem_to_sqlite(legacy_root=legacy, store=store)
    assert n == 3

    summaries = await store.list_by_ticker(limit=10)
    assert {s.id for s in summaries} == {"art_a1", "art_a2", "art_m1"}


@pytest.mark.asyncio
async def test_migrate_ignores_index_json(tmp_path: Path, store: SqliteArtifactStore) -> None:
    legacy = tmp_path / "legacy"
    _write_artifact_json(legacy, "AAPL", "art_a1")
    # legacy stores wrote an index.json sibling — must not be re-ingested
    (legacy / "AAPL" / "index.json").write_text("[]")
    n = await migrate_filesystem_to_sqlite(legacy_root=legacy, store=store)
    assert n == 1


@pytest.mark.asyncio
async def test_migrate_is_idempotent(tmp_path: Path, store: SqliteArtifactStore) -> None:
    legacy = tmp_path / "legacy"
    _write_artifact_json(legacy, "AAPL", "art_a1")
    await migrate_filesystem_to_sqlite(legacy_root=legacy, store=store)
    # Second run upserts same id → no duplicate row
    await migrate_filesystem_to_sqlite(legacy_root=legacy, store=store)
    summaries = await store.list_by_ticker(limit=10)
    assert len(summaries) == 1


@pytest.mark.asyncio
async def test_migrate_skips_corrupt(tmp_path: Path, store: SqliteArtifactStore) -> None:
    legacy = tmp_path / "legacy"
    tdir = legacy / "AAPL"
    tdir.mkdir(parents=True)
    (tdir / "art_corrupt.json").write_text("{not json")
    _write_artifact_json(legacy, "AAPL", "art_good")

    n = await migrate_filesystem_to_sqlite(legacy_root=legacy, store=store)
    assert n == 1
    summaries = await store.list_by_ticker(limit=10)
    assert {s.id for s in summaries} == {"art_good"}
