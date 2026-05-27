# Storage Overhaul + Landing Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the 4-5 second cold-start delay on `/stocks` landing AND migrate ArtifactStore from filesystem JSON to SQLite, so artifact growth past ~100 records stays sub-second.

**Architecture:**
- Migrate `ArtifactStore` from `~/.finrobot-desktop/artifacts/*/<id>.json + index.json` filesystem layout to a single SQLite db `~/.finrobot/artifacts.db` with secondary indexes on (ticker, created_at), verdict, archived.
- Add a `QuoteCache` (L1 in-memory TTL + L2 SQLite at `~/.finrobot/quotes.db`) so the two dashboard endpoints stop fan-out-calling yfinance and instead share a per-ticker quote that refreshes at most every 60s.
- Fix the `dashboard.py` N+1 dead-path: use `ArtifactSummary.verdict` (already indexed in summary) instead of reloading the full artifact JSON to re-extract verdict.
- Unify all FinRobot state under `~/.finrobot/` (move `~/.cache/finrobot/cache.db` → `~/.finrobot/data_cache.db`); auto-migrate from legacy paths on first boot.

**Tech Stack:** Python 3.11, FastAPI, aiosqlite, pydantic v2, yfinance, asyncio, pytest, vitest

**Performance Targets (measured via `curl -w "%{time_total}s"`):**
| Endpoint | Cold (TTL miss) | Warm |
|---|---|---|
| `/api/dashboard/hit-rate` | < 500ms | < 50ms |
| `/api/dashboard/recent-research` | < 300ms | < 50ms |
| `/api/artifacts/studied-tickers` | < 30ms | < 30ms |

Current baseline: 4.80s / 1.79s / 7ms — the first two are the regression target.

---

## File Structure

### New files
- `finrobot/artifact/sqlite_store.py` — `SqliteArtifactStore` class implementing the same async interface as the existing `ArtifactStore` (drop-in replacement at the consumer level)
- `finrobot/artifact/migrate.py` — one-shot script that walks `~/.finrobot-desktop/artifacts/` JSON files and inserts them into `artifacts.db`; idempotent (skip if `id` already present)
- `finrobot/engine/data/quote_cache.py` — `QuoteCache` class with L1 in-memory TTL dict + L2 aiosqlite-backed table; exposes async `get(ticker) → float | None` and `get_batch(tickers) → dict[str, float | None]`
- `finrobot/paths.py` — single source of truth for all `~/.finrobot/<file>.db` locations; auto-migrates legacy paths on first import
- `tests/artifact/test_sqlite_store.py` — full contract test for `SqliteArtifactStore` (mirror of `tests/artifact/test_store.py`)
- `tests/artifact/test_migrate.py` — migration script: empty → empty, partial → backfill, idempotent re-run
- `tests/unit/test_quote_cache.py` — L1 hit / L2 hit / cold miss / TTL expiry / per-ticker failure / concurrent fan-out

### Modified files
- `finrobot/artifact/store.py:40` — keep file as `FsArtifactStore` shim that delegates to `SqliteArtifactStore` (one-line drop-in) to avoid breaking ~20 imports across `routes/` and `engine/pipelines/`
- `finrobot/server.py:119` — instantiate `SqliteArtifactStore` instead of `ArtifactStore`; add lifespan task to warm `QuoteCache` for distinct studied tickers
- `finrobot/engine/data/quote_batch.py` — replace synchronous yfinance loop with async fan-out wrapping `QuoteCache`; keep `fetch_quotes_batch(tickers)` signature for backwards compatibility but route through cache
- `finrobot/engine/data/cache.py:67` — switch default path resolution to `finrobot.paths.DATA_CACHE_DB`
- `finrobot/run_store.py:103` — switch default path resolution to `finrobot.paths.RUNS_DB`
- `finrobot/routes/dashboard.py:714,786` — remove `await store.get(s.id)` + `extract_verdict(art)` paths; use `s.verdict` directly from summary
- `finrobot/config.py:20` — `_default_cache_db_path` now returns `finrobot.paths.DATA_CACHE_DB`
- `tests/routes/test_dashboard_landing.py` — assert `store.get` call count is 0 in `/api/dashboard/hit-rate` and bounded by `top-N tickers × MAX_RUNS_PER_TICKER` only for `/api/dashboard/recent-research` runs that need the artifact body for `entry/target/age` (already in summary — should be 0)
- `tests/unit/test_quote_batch.py` — assert L1 cache hit doesn't call yfinance; assert TTL expiry forces fresh fetch
- `tests/artifact/test_store.py` — keep but parametrize across both `FsArtifactStore` (deprecated) and `SqliteArtifactStore` to ensure interface parity during migration window
- `CLAUDE.md` — update storage section: `~/.finrobot/{artifacts,quotes,data_cache,runs}.db` unified; remove `~/.finrobot-desktop/artifacts/`, `~/.cache/finrobot/` references
- `MEMORY.md` index entry for new project memory file documenting the storage architecture decision

### Deleted files
- None during this work — old `FsArtifactStore` stays as deprecated shim until a follow-up cleanup (CLAUDE.md notes it's deprecated)

---

## Task 1: paths.py — single source of truth + legacy auto-migration

**Files:**
- Create: `finrobot/paths.py`
- Create: `tests/unit/test_paths.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_paths.py
"""All-storage path resolution + legacy migration.

The previous storage paths were scattered across three locations:
  ~/.finrobot-desktop/artifacts/  ArtifactStore (filesystem JSON)
  ~/.cache/finrobot/cache.db      DataCache
  ~/.finrobot/runs.db             RunStore

paths.py unifies them under ~/.finrobot/ and exposes constants.
On first import after upgrade, legacy paths are auto-moved (best-effort).
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_constants_resolve_under_finrobot_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from finrobot import paths
    import importlib
    importlib.reload(paths)

    assert paths.FINAGENT_HOME == tmp_path / ".finrobot"
    assert paths.ARTIFACTS_DB == tmp_path / ".finrobot" / "artifacts.db"
    assert paths.QUOTES_DB == tmp_path / ".finrobot" / "quotes.db"
    assert paths.DATA_CACHE_DB == tmp_path / ".finrobot" / "data_cache.db"
    assert paths.RUNS_DB == tmp_path / ".finrobot" / "runs.db"


def test_ensure_home_creates_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from finrobot import paths
    import importlib
    importlib.reload(paths)

    paths.ensure_home()
    assert (tmp_path / ".finrobot").is_dir()


def test_migrate_legacy_data_cache_moves_file(tmp_path, monkeypatch):
    """~/.cache/finrobot/cache.db → ~/.finrobot/data_cache.db"""
    monkeypatch.setenv("HOME", str(tmp_path))
    legacy = tmp_path / ".cache" / "finrobot" / "cache.db"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy-content")

    from finrobot import paths
    import importlib
    importlib.reload(paths)

    paths.migrate_legacy_paths()
    assert (tmp_path / ".finrobot" / "data_cache.db").read_bytes() == b"legacy-content"
    # Legacy marker: file moved, not duplicated
    assert not legacy.exists()


def test_migrate_legacy_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from finrobot import paths
    import importlib
    importlib.reload(paths)

    paths.migrate_legacy_paths()
    paths.migrate_legacy_paths()  # should be a no-op


def test_migrate_legacy_does_not_overwrite_existing(tmp_path, monkeypatch):
    """If new path already exists, legacy is left alone (manual cleanup)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    legacy = tmp_path / ".cache" / "finrobot" / "cache.db"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy")
    new = tmp_path / ".finrobot" / "data_cache.db"
    new.parent.mkdir(parents=True)
    new.write_bytes(b"new")

    from finrobot import paths
    import importlib
    importlib.reload(paths)

    paths.migrate_legacy_paths()
    assert new.read_bytes() == b"new"
    assert legacy.read_bytes() == b"legacy"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_paths.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'finrobot.paths'`

- [ ] **Step 3: Implement `finrobot/paths.py`**

```python
"""Unified storage path resolution.

Single source of truth for every FinRobot state directory or db file.
All paths live under ~/.finrobot/ for backup symmetry and so users can
nuke state with one rm -rf.

Legacy paths (~/.cache/finrobot/, ~/.finrobot-desktop/) are auto-moved
into ~/.finrobot/ on first import via migrate_legacy_paths().
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def _home() -> Path:
    return Path.home()


FINAGENT_HOME: Path = _home() / ".finrobot"
ARTIFACTS_DB: Path = FINAGENT_HOME / "artifacts.db"
QUOTES_DB: Path = FINAGENT_HOME / "quotes.db"
DATA_CACHE_DB: Path = FINAGENT_HOME / "data_cache.db"
RUNS_DB: Path = FINAGENT_HOME / "runs.db"
SETTINGS_JSON: Path = FINAGENT_HOME / "settings.json"


def ensure_home() -> Path:
    """Create ~/.finrobot/ if missing. Returns the directory path."""
    FINAGENT_HOME.mkdir(parents=True, exist_ok=True)
    return FINAGENT_HOME


def migrate_legacy_paths() -> dict[str, str]:
    """Move legacy storage to the unified ~/.finrobot/ home.

    Idempotent: only moves when the legacy path exists AND the new path does not.
    Returns a {legacy → new} dict of migrations actually performed (empty on no-op).
    """
    ensure_home()
    migrations: dict[str, str] = {}

    # data cache: ~/.cache/finrobot/cache.db → ~/.finrobot/data_cache.db
    legacy_data_cache = _home() / ".cache" / "finrobot" / "cache.db"
    if legacy_data_cache.exists() and not DATA_CACHE_DB.exists():
        try:
            shutil.move(str(legacy_data_cache), str(DATA_CACHE_DB))
            migrations[str(legacy_data_cache)] = str(DATA_CACHE_DB)
            # Also move WAL/SHM sidecar files if present
            for suffix in ("-wal", "-shm"):
                side = legacy_data_cache.with_name(legacy_data_cache.name + suffix)
                if side.exists():
                    shutil.move(str(side), str(DATA_CACHE_DB.with_name(DATA_CACHE_DB.name + suffix)))
        except OSError as exc:
            logger.warning("Could not migrate %s: %s", legacy_data_cache, exc)

    return migrations
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_paths.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add finrobot/paths.py tests/unit/test_paths.py
git commit -m "feat(storage): unify FinRobot state paths under ~/.finrobot/ + legacy auto-migrate"
```

---

## Task 2: SqliteArtifactStore — schema + CRUD parity

**Files:**
- Create: `finrobot/artifact/sqlite_store.py`
- Create: `tests/artifact/test_sqlite_store.py`

- [ ] **Step 1: Write failing tests (full interface contract)**

```python
# tests/artifact/test_sqlite_store.py
"""Contract tests for SqliteArtifactStore — mirrors tests/artifact/test_store.py.

Goal: SqliteArtifactStore is a drop-in replacement for the legacy filesystem
ArtifactStore. Every method should behave identically; this test file
encodes the contract.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from finrobot.artifact.models import (
    Artifact,
    ArtifactMeta,
    ArtifactOutputs,
)
from finrobot.artifact.sqlite_store import SqliteArtifactStore


def _make_artifact(
    artifact_id: str = "art_test_001",
    ticker: str | None = "AAPL",
    type_: str = "dcf",
) -> Artifact:
    return Artifact(
        id=artifact_id,
        ticker=ticker,
        cross_tickers=[],
        type=type_,
        inputs={},
        outputs=ArtifactOutputs(structured={"implied_price": 200.0}, summary_text="test"),
        meta=ArtifactMeta(
            created_at=datetime.now(tz=timezone.utc),
            source="test",
            archived=False,
        ),
    )


@pytest.mark.asyncio
async def test_save_then_get_roundtrip(tmp_path):
    store = SqliteArtifactStore(db_path=tmp_path / "test.db")
    art = _make_artifact()
    await store.save(art)

    loaded = await store.get(art.id)
    assert loaded is not None
    assert loaded.id == art.id
    assert loaded.ticker == "AAPL"
    assert loaded.outputs.structured == {"implied_price": 200.0}


@pytest.mark.asyncio
async def test_get_missing_returns_none(tmp_path):
    store = SqliteArtifactStore(db_path=tmp_path / "test.db")
    assert await store.get("nope") is None


@pytest.mark.asyncio
async def test_list_by_ticker_sorted_desc(tmp_path):
    store = SqliteArtifactStore(db_path=tmp_path / "test.db")
    now = datetime.now(tz=timezone.utc)
    a1 = _make_artifact("art_a1")
    a1.meta.created_at = now - timedelta(hours=2)
    a2 = _make_artifact("art_a2")
    a2.meta.created_at = now - timedelta(hours=1)
    a3 = _make_artifact("art_a3")
    a3.meta.created_at = now
    await store.save(a1)
    await store.save(a2)
    await store.save(a3)

    summaries = await store.list_by_ticker(ticker="AAPL", limit=10)
    assert [s.id for s in summaries] == ["art_a3", "art_a2", "art_a1"]


@pytest.mark.asyncio
async def test_list_all_tickers(tmp_path):
    store = SqliteArtifactStore(db_path=tmp_path / "test.db")
    await store.save(_make_artifact("art_a", ticker="AAPL"))
    await store.save(_make_artifact("art_m", ticker="MSFT"))
    summaries = await store.list_by_ticker(ticker=None, limit=10)
    tickers = {s.ticker for s in summaries}
    assert tickers == {"AAPL", "MSFT"}


@pytest.mark.asyncio
async def test_list_filters_archived(tmp_path):
    store = SqliteArtifactStore(db_path=tmp_path / "test.db")
    a = _make_artifact("art_archived")
    a.meta.archived = True
    await store.save(a)
    await store.save(_make_artifact("art_live"))
    visible = await store.list_by_ticker(ticker="AAPL")
    assert {s.id for s in visible} == {"art_live"}
    with_archived = await store.list_by_ticker(ticker="AAPL", include_archived=True)
    assert {s.id for s in with_archived} == {"art_archived", "art_live"}


@pytest.mark.asyncio
async def test_list_filters_by_type(tmp_path):
    store = SqliteArtifactStore(db_path=tmp_path / "test.db")
    await store.save(_make_artifact("art_d", type_="dcf"))
    await store.save(_make_artifact("art_l", type_="lbo"))
    only_dcf = await store.list_by_ticker(ticker="AAPL", type="dcf")
    assert {s.id for s in only_dcf} == {"art_d"}


@pytest.mark.asyncio
async def test_delete(tmp_path):
    store = SqliteArtifactStore(db_path=tmp_path / "test.db")
    art = _make_artifact()
    await store.save(art)
    assert await store.delete(art.id) is True
    assert await store.get(art.id) is None
    assert await store.delete(art.id) is False  # second delete = miss


@pytest.mark.asyncio
async def test_cross_ticker_artifact(tmp_path):
    """ticker=None artifacts live in the same table, identified by ticker IS NULL."""
    store = SqliteArtifactStore(db_path=tmp_path / "test.db")
    art = _make_artifact("art_cross", ticker=None)
    art.cross_tickers = ["AAPL", "MSFT"]
    await store.save(art)
    loaded = await store.get("art_cross")
    assert loaded is not None
    assert loaded.ticker is None
    assert loaded.cross_tickers == ["AAPL", "MSFT"]


@pytest.mark.asyncio
async def test_summary_has_verdict_from_artifact(tmp_path):
    """ArtifactSummary.verdict must be populated at write time so dashboard
    aggregations don't N+1-read the full artifact for the verdict field."""
    store = SqliteArtifactStore(db_path=tmp_path / "test.db")
    art = _make_artifact()
    # mock a structured payload that extract_verdict can read
    art.outputs.structured = {
        "thesis": {"recommendation": "BUY"},
        "implied_price": 200.0,
    }
    await store.save(art)
    summaries = await store.list_by_ticker(ticker="AAPL")
    assert summaries[0].verdict == "BUY"


@pytest.mark.asyncio
async def test_mark_viewed_unarchives(tmp_path):
    store = SqliteArtifactStore(db_path=tmp_path / "test.db")
    art = _make_artifact()
    art.meta.archived = True
    await store.save(art)
    await store.mark_viewed(art.id)
    summaries = await store.list_by_ticker(ticker="AAPL")
    assert any(s.id == art.id for s in summaries)  # un-archived


@pytest.mark.asyncio
async def test_archive_stale_marks_old(tmp_path):
    store = SqliteArtifactStore(db_path=tmp_path / "test.db")
    art = _make_artifact()
    art.meta.created_at = datetime.now(tz=timezone.utc) - timedelta(hours=48)
    art.meta.last_viewed_at = None
    await store.save(art)
    n = await store.archive_stale(hours=24)
    assert n == 1
    visible = await store.list_by_ticker(ticker="AAPL")
    assert visible == []


@pytest.mark.asyncio
async def test_rebuild_summaries_is_noop_after_save(tmp_path):
    """rebuild_summaries should be a no-op now that summaries are always
    fresh at write time (no separate index.json that can drift)."""
    store = SqliteArtifactStore(db_path=tmp_path / "test.db")
    await store.save(_make_artifact())
    rewritten = await store.rebuild_summaries()
    assert rewritten == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/artifact/test_sqlite_store.py -v`
Expected: All FAIL with `ImportError: cannot import name 'SqliteArtifactStore'`

- [ ] **Step 3: Implement `finrobot/artifact/sqlite_store.py`**

```python
"""SQLite-backed ArtifactStore.

Schema (single table `artifacts`):
    id            TEXT PRIMARY KEY
    ticker        TEXT NULL  (NULL = cross-ticker artifact)
    cross_tickers TEXT NOT NULL  (JSON list)
    type          TEXT NOT NULL
    verdict       TEXT NULL  (extracted at write time; secondary indexed)
    created_at    TEXT NOT NULL  (ISO 8601 UTC)
    last_viewed_at TEXT NULL
    archived      INTEGER NOT NULL DEFAULT 0
    entry_price   REAL NULL
    target_price  REAL NULL
    target_date   TEXT NULL
    source        TEXT NULL
    headline      TEXT NULL
    tagline       TEXT NULL
    payload       TEXT NOT NULL  (full Artifact JSON)

Indexes:
    idx_artifacts_ticker_created   (ticker, created_at DESC)
    idx_artifacts_created           (created_at DESC) for cross-ticker scans
    idx_artifacts_verdict           (verdict) WHERE verdict IS NOT NULL
    idx_artifacts_archived          (archived)

Interface contract: same async signature as the legacy ArtifactStore so
consumers can swap without code changes. See tests/artifact/test_sqlite_store.py
for the contract.
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
from finrobot.artifact.summary_extractor import (
    extract_entry_price,
    extract_tagline,
    extract_target_date,
    extract_target_price,
    extract_verdict,
)
from finrobot.paths import ARTIFACTS_DB, ensure_home

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
    "CREATE INDEX IF NOT EXISTS idx_artifacts_created ON artifacts(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_artifacts_verdict ON artifacts(verdict) WHERE verdict IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_artifacts_archived ON artifacts(archived)",
]


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _summary_columns() -> str:
    return (
        "id, ticker, cross_tickers, type, verdict, created_at, archived, "
        "entry_price, target_price, target_date, source, headline, tagline"
    )


def _row_to_summary(row: Any) -> ArtifactSummary:
    (
        id_, ticker, cross_tickers_json, type_, verdict, created_at, archived,
        entry_price, target_price, target_date, source, headline, tagline,
    ) = row
    return ArtifactSummary(
        id=id_,
        ticker=ticker,
        cross_tickers=json.loads(cross_tickers_json) if cross_tickers_json else [],
        type=type_,
        verdict=verdict,
        created_at=datetime.fromisoformat(created_at),
        archived=bool(archived),
        entry_price=entry_price,
        target_price=target_price,
        target_date=datetime.fromisoformat(target_date) if target_date else None,
        source=source,
        headline=headline or id_,
        signal=None,
        tagline=tagline,
    )


class SqliteArtifactStore:
    """SQLite-backed equivalent of the legacy filesystem ArtifactStore.

    Drop-in: identical async method signatures.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        ensure_home()
        self._db_path = str(db_path or ARTIFACTS_DB)
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
        target_price = extract_target_price(artifact)
        row = (
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
            (
                extract_target_date(artifact, target_price).isoformat()
                if extract_target_date(artifact, target_price)
                else None
            ),
            artifact.meta.source,
            (artifact.outputs.summary_text[:120] or artifact.id) if artifact.outputs else artifact.id,
            extract_tagline(artifact),
            artifact.model_dump_json(),
        )
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
        cur = await conn.execute("DELETE FROM artifacts WHERE id = ?", (artifact_id,))
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
        sql = f"SELECT {_summary_columns()} FROM artifacts {clause} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        async with conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [_row_to_summary(r) for r in rows]

    async def list_versions(
        self, ticker: str, type: ArtifactType  # noqa: A002
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
        """No-op: summary columns are always fresh at write time.

        Kept for interface parity with the legacy filesystem store, where
        index.json could drift behind the artifact JSON files.
        """
        return 0

    async def archive_stale(self, hours: int = 24) -> int:
        conn = await self._conn_ready()
        cutoff = _now()
        # All non-archived artifacts whose last activity is older than cutoff
        async with conn.execute(
            "SELECT id, created_at, last_viewed_at FROM artifacts WHERE archived = 0"
        ) as cur:
            rows = await cur.fetchall()
        archived = 0
        for id_, created_at, last_viewed_at in rows:
            last_seen = datetime.fromisoformat(last_viewed_at or created_at)
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            age_h = (cutoff - last_seen).total_seconds() / 3600
            if age_h < hours:
                continue
            await conn.execute("UPDATE artifacts SET archived = 1 WHERE id = ?", (id_,))
            archived += 1
        await conn.commit()
        return archived

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/artifact/test_sqlite_store.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add finrobot/artifact/sqlite_store.py tests/artifact/test_sqlite_store.py
git commit -m "feat(artifact): add SqliteArtifactStore with secondary indexes on verdict + (ticker, created_at)"
```

---

## Task 3: Migration script — JSON filesystem → SQLite

**Files:**
- Create: `finrobot/artifact/migrate.py`
- Create: `tests/artifact/test_migrate.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/artifact/test_migrate.py
"""One-shot migration from ~/.finrobot-desktop/artifacts/ (JSON files) to
~/.finrobot/artifacts.db (SqliteArtifactStore).

Behaviour:
  - empty legacy dir → return 0
  - N JSON files → return N inserted
  - re-run is idempotent (ON CONFLICT UPDATE in SqliteArtifactStore.save)
  - corrupt JSON files are skipped + logged, not fatal
  - index.json files are ignored
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from finrobot.artifact.migrate import migrate_filesystem_to_sqlite
from finrobot.artifact.models import Artifact, ArtifactMeta, ArtifactOutputs
from finrobot.artifact.sqlite_store import SqliteArtifactStore


def _write_artifact_json(base: Path, ticker: str, artifact_id: str) -> Artifact:
    art = Artifact(
        id=artifact_id,
        ticker=ticker,
        cross_tickers=[],
        type="dcf",
        inputs={},
        outputs=ArtifactOutputs(structured={"implied_price": 100.0}, summary_text="x"),
        meta=ArtifactMeta(created_at=datetime.now(tz=timezone.utc), source="test"),
    )
    tdir = base / ticker
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / f"{artifact_id}.json").write_text(art.model_dump_json())
    return art


@pytest.mark.asyncio
async def test_migrate_empty_legacy_returns_zero(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    store = SqliteArtifactStore(db_path=tmp_path / "new.db")
    n = await migrate_filesystem_to_sqlite(legacy_root=legacy, store=store)
    assert n == 0


@pytest.mark.asyncio
async def test_migrate_inserts_all_json_files(tmp_path):
    legacy = tmp_path / "legacy"
    _write_artifact_json(legacy, "AAPL", "art_a1")
    _write_artifact_json(legacy, "AAPL", "art_a2")
    _write_artifact_json(legacy, "MSFT", "art_m1")
    store = SqliteArtifactStore(db_path=tmp_path / "new.db")

    n = await migrate_filesystem_to_sqlite(legacy_root=legacy, store=store)
    assert n == 3

    summaries = await store.list_by_ticker(limit=10)
    assert len(summaries) == 3


@pytest.mark.asyncio
async def test_migrate_ignores_index_json(tmp_path):
    legacy = tmp_path / "legacy"
    _write_artifact_json(legacy, "AAPL", "art_a1")
    (legacy / "AAPL" / "index.json").write_text("[]")  # should not be re-imported
    store = SqliteArtifactStore(db_path=tmp_path / "new.db")
    n = await migrate_filesystem_to_sqlite(legacy_root=legacy, store=store)
    assert n == 1


@pytest.mark.asyncio
async def test_migrate_is_idempotent(tmp_path):
    legacy = tmp_path / "legacy"
    _write_artifact_json(legacy, "AAPL", "art_a1")
    store = SqliteArtifactStore(db_path=tmp_path / "new.db")
    await migrate_filesystem_to_sqlite(legacy_root=legacy, store=store)
    n2 = await migrate_filesystem_to_sqlite(legacy_root=legacy, store=store)
    # second run inserts 0 new but upserts existing — count what migrated, not skipped
    assert n2 == 1  # we re-ingest, save is upsert; total artifacts in db still 1
    summaries = await store.list_by_ticker(limit=10)
    assert len(summaries) == 1


@pytest.mark.asyncio
async def test_migrate_skips_corrupt(tmp_path):
    legacy = tmp_path / "legacy"
    tdir = legacy / "AAPL"
    tdir.mkdir(parents=True)
    (tdir / "art_corrupt.json").write_text("{not json")
    _write_artifact_json(legacy, "AAPL", "art_good")
    store = SqliteArtifactStore(db_path=tmp_path / "new.db")

    n = await migrate_filesystem_to_sqlite(legacy_root=legacy, store=store)
    assert n == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/artifact/test_migrate.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `finrobot/artifact/migrate.py`**

```python
"""One-shot migration: filesystem JSON → SQLite ArtifactStore.

Called during server startup (lifespan) and idempotent — safe to re-run.
After migration, the legacy ~/.finrobot-desktop/artifacts/ directory is
left in place as a backup until the user manually deletes it.
"""

from __future__ import annotations

import logging
from pathlib import Path

from finrobot.artifact.models import Artifact
from finrobot.artifact.sqlite_store import SqliteArtifactStore

logger = logging.getLogger(__name__)

LEGACY_ARTIFACTS_ROOT = Path.home() / ".finrobot-desktop" / "artifacts"


async def migrate_filesystem_to_sqlite(
    legacy_root: Path | None = None,
    store: SqliteArtifactStore | None = None,
) -> int:
    """Walk legacy_root for *.json artifact files and save them to store.

    Returns the count of artifacts processed (insert OR upsert).
    Safe to call repeatedly.
    """
    root = legacy_root if legacy_root is not None else LEGACY_ARTIFACTS_ROOT
    if not root.exists():
        return 0

    target = store if store is not None else SqliteArtifactStore()
    count = 0
    for sub in root.iterdir():
        if not sub.is_dir():
            continue
        for art_file in sub.glob("*.json"):
            if art_file.name == "index.json":
                continue
            try:
                payload = art_file.read_text(encoding="utf-8")
                artifact = Artifact.model_validate_json(payload)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                logger.warning("Skip corrupt artifact %s: %s", art_file, exc)
                continue
            await target.save(artifact)
            count += 1

    logger.info("Migrated %d artifacts from %s", count, root)
    return count
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/artifact/test_migrate.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add finrobot/artifact/migrate.py tests/artifact/test_migrate.py
git commit -m "feat(artifact): one-shot migration from filesystem JSON to SQLite"
```

---

## Task 4: Wire SqliteArtifactStore into server.py + run migration on startup

**Files:**
- Modify: `finrobot/artifact/store.py` (turn legacy class into a deprecated shim)
- Modify: `finrobot/server.py`
- Modify: `finrobot/engine/data/cache.py` (use paths.DATA_CACHE_DB)
- Modify: `finrobot/run_store.py` (use paths.RUNS_DB)
- Modify: `finrobot/config.py:20` (use paths.DATA_CACHE_DB)

- [ ] **Step 1: Replace `ArtifactStore` with shim that delegates to `SqliteArtifactStore`**

Edit `finrobot/artifact/store.py:86-100` (replace the class declaration):

```python
class ArtifactStore:
    """Deprecated alias — delegates to SqliteArtifactStore.

    Kept so existing imports (~20 sites) continue to work without churn.
    New code should import SqliteArtifactStore directly.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        # base_dir kept for backwards compat; SqliteArtifactStore uses paths.ARTIFACTS_DB
        del base_dir
        from finrobot.artifact.sqlite_store import SqliteArtifactStore
        self._impl = SqliteArtifactStore()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._impl, name)
```

Delete the rest of the old filesystem implementation (lines 100-515).

- [ ] **Step 2: Update `finrobot/server.py` lifespan to run migration**

Edit `finrobot/server.py` around line 119 — replace `artifact_store = ArtifactStore()` with `SqliteArtifactStore()`, and add a migration task next to `_rebuild_indexes_background`:

```python
# server.py replacement
from finrobot.artifact.sqlite_store import SqliteArtifactStore
from finrobot.artifact.migrate import migrate_filesystem_to_sqlite
from finrobot.paths import ensure_home, migrate_legacy_paths

# inside lifespan(), before instantiating stores:
ensure_home()
migrate_legacy_paths()

artifact_store = SqliteArtifactStore()

# inside lifespan, replace _rebuild_indexes_background:
async def _migrate_legacy_artifacts_background() -> None:
    try:
        n = await migrate_filesystem_to_sqlite(store=artifact_store)
        if n:
            logger.info("Migrated %d legacy filesystem artifacts to SQLite", n)
    except (OSError, ValueError, TypeError, RuntimeError):
        logger.exception("Legacy artifact migration failed — non-fatal")

# Replace asyncio.create_task(_rebuild_indexes_background()) with:
asyncio.create_task(_migrate_legacy_artifacts_background())
```

- [ ] **Step 3: Wire paths.py into cache.py, run_store.py, config.py**

Edit `finrobot/config.py:20-32`:

```python
def _default_cache_db_path() -> str:
    """Return the default cache database path under ~/.finrobot/."""
    from finrobot.paths import DATA_CACHE_DB, ensure_home
    ensure_home()
    return str(DATA_CACHE_DB)
```

Edit `finrobot/run_store.py:103`:

```python
def __init__(self, db_path: str | Path | None = None) -> None:
    if db_path is None:
        from finrobot.paths import RUNS_DB, ensure_home
        ensure_home()
        db_path = RUNS_DB
    self._db_path = str(db_path)
```

- [ ] **Step 4: Run full test suite to verify nothing broke**

Run: `pytest tests/ -x --ignore=tests/integration -m "not slow" -q`
Expected: All existing tests pass (1468 + new 11 + new 5 + new 5 = 1489 passing)

Run: `pytest tests/artifact/test_store.py -v` (legacy tests via shim)
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add finrobot/artifact/store.py finrobot/server.py finrobot/run_store.py finrobot/config.py finrobot/engine/data/cache.py
git commit -m "feat(server): switch lifespan to SqliteArtifactStore + unified ~/.finrobot/ paths"
```

---

## Task 5: QuoteCache — L1 in-memory + L2 SQLite

**Files:**
- Create: `finrobot/engine/data/quote_cache.py`
- Create: `tests/unit/test_quote_cache.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_quote_cache.py
"""QuoteCache — L1 in-memory TTL cache + L2 SQLite-backed quotes table.

Why two layers?
  L1 keeps the hot-path latency near zero (no IO at all when cache is warm)
  L2 survives process restarts and tab reloads (e.g. tauri reopen)
  Both share a 60s TTL — short enough to feel live, long enough to absorb
  refresh storms.

Per-ticker failures (delisted, yfinance miss) are stored as None and
expire on the same TTL — so we don't keep beating yfinance for a dead symbol.
"""

import time
from unittest.mock import patch

import pytest

from finrobot.engine.data.quote_cache import QuoteCache


@pytest.mark.asyncio
async def test_cold_miss_calls_fetcher(tmp_path):
    cache = QuoteCache(db_path=tmp_path / "q.db", ttl_seconds=60)
    calls: list[str] = []

    async def fake_fetch(tickers):
        calls.extend(tickers)
        return {t: 100.0 for t in tickers}

    result = await cache.get_batch(["AAPL", "MSFT"], fetcher=fake_fetch)
    assert result == {"AAPL": 100.0, "MSFT": 100.0}
    assert sorted(calls) == ["AAPL", "MSFT"]


@pytest.mark.asyncio
async def test_l1_hit_skips_fetcher(tmp_path):
    cache = QuoteCache(db_path=tmp_path / "q.db", ttl_seconds=60)
    calls: list[str] = []

    async def fake_fetch(tickers):
        calls.extend(tickers)
        return {t: 100.0 for t in tickers}

    await cache.get_batch(["AAPL"], fetcher=fake_fetch)
    calls.clear()
    result = await cache.get_batch(["AAPL"], fetcher=fake_fetch)
    assert result == {"AAPL": 100.0}
    assert calls == []  # L1 served it


@pytest.mark.asyncio
async def test_l2_hit_after_l1_reset(tmp_path):
    """Recreating QuoteCache wipes L1 but L2 (SQLite) should still hit."""
    db = tmp_path / "q.db"

    async def fake_fetch(tickers):
        return {t: 100.0 for t in tickers}

    cache1 = QuoteCache(db_path=db, ttl_seconds=60)
    await cache1.get_batch(["AAPL"], fetcher=fake_fetch)
    await cache1.close()

    cache2 = QuoteCache(db_path=db, ttl_seconds=60)
    calls: list[str] = []

    async def fail_fetch(tickers):
        calls.extend(tickers)
        return {t: 999.0 for t in tickers}

    result = await cache2.get_batch(["AAPL"], fetcher=fail_fetch)
    assert result == {"AAPL": 100.0}
    assert calls == []  # L2 served it


@pytest.mark.asyncio
async def test_ttl_expiry_forces_refetch(tmp_path):
    cache = QuoteCache(db_path=tmp_path / "q.db", ttl_seconds=0)
    calls: list[str] = []

    async def fake_fetch(tickers):
        calls.extend(tickers)
        return {t: 100.0 for t in tickers}

    await cache.get_batch(["AAPL"], fetcher=fake_fetch)
    time.sleep(0.01)
    await cache.get_batch(["AAPL"], fetcher=fake_fetch)
    assert calls == ["AAPL", "AAPL"]


@pytest.mark.asyncio
async def test_partial_batch_only_fetches_misses(tmp_path):
    """If AAPL is warm but MSFT is not, only MSFT is passed to fetcher."""
    cache = QuoteCache(db_path=tmp_path / "q.db", ttl_seconds=60)

    async def first(tickers):
        return {t: 100.0 for t in tickers}

    await cache.get_batch(["AAPL"], fetcher=first)
    fetched: list[str] = []

    async def second(tickers):
        fetched.extend(tickers)
        return {t: 200.0 for t in tickers}

    result = await cache.get_batch(["AAPL", "MSFT"], fetcher=second)
    assert result == {"AAPL": 100.0, "MSFT": 200.0}
    assert fetched == ["MSFT"]


@pytest.mark.asyncio
async def test_none_quote_cached_with_same_ttl(tmp_path):
    """Failed fetches (None) should also be cached so we don't beat yfinance
    on every refresh for a delisted symbol."""
    cache = QuoteCache(db_path=tmp_path / "q.db", ttl_seconds=60)
    calls: list[str] = []

    async def fake_fetch(tickers):
        calls.extend(tickers)
        return {t: None for t in tickers}

    await cache.get_batch(["DELISTED"], fetcher=fake_fetch)
    calls.clear()
    result = await cache.get_batch(["DELISTED"], fetcher=fake_fetch)
    assert result == {"DELISTED": None}
    assert calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_quote_cache.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `finrobot/engine/data/quote_cache.py`**

```python
"""Two-layer quote cache: L1 in-memory + L2 SQLite.

Why this exists:
  yfinance's Tickers(...).fast_info is synchronous and ~1-2s per ticker.
  Two dashboard endpoints (hit-rate, recent-research) each fan out to all
  studied tickers — that's 7-8s on cold load. This cache collapses all
  callers to one upstream fetch per TTL window per ticker.

Layout:
  L1: dict[ticker, (price, fetched_at)] — wiped on process restart
  L2: SQLite table `quotes_cache` at ~/.finrobot/quotes.db — survives restart

Lookup flow:
  get_batch(tickers, fetcher) →
    1. For each ticker, check L1; if fresh, take from L1
    2. For remaining, check L2; if fresh, copy to L1 and take
    3. For remaining (still missing or stale), call fetcher(remaining)
    4. Write fetcher results to both L1 and L2
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import aiosqlite

from finrobot.paths import QUOTES_DB, ensure_home

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS quotes_cache (
    ticker     TEXT PRIMARY KEY,
    last_price REAL,
    fetched_at REAL NOT NULL
)
"""

FetcherType = Callable[[list[str]], Awaitable[dict[str, float | None]]]


class QuoteCache:
    def __init__(
        self,
        db_path: str | Path | None = None,
        ttl_seconds: float = 60.0,
    ) -> None:
        ensure_home()
        self._db_path = str(db_path or QUOTES_DB)
        self._ttl = float(ttl_seconds)
        self._l1: dict[str, tuple[float | None, float]] = {}
        self._l1_lock = asyncio.Lock()
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
                    await conn.commit()
                except BaseException:
                    await conn.close()
                    raise
                self._conn = conn
        return self._conn

    async def get_batch(
        self, tickers: list[str], fetcher: FetcherType
    ) -> dict[str, float | None]:
        now = time.time()
        syms = [t.strip().upper() for t in tickers if t and t.strip()]
        result: dict[str, float | None] = {}
        missing: list[str] = []

        # Layer 1: in-memory
        async with self._l1_lock:
            for sym in syms:
                hit = self._l1.get(sym)
                if hit is not None and now - hit[1] < self._ttl:
                    result[sym] = hit[0]
                else:
                    missing.append(sym)

        # Layer 2: SQLite
        if missing:
            conn = await self._conn_ready()
            placeholders = ",".join("?" * len(missing))
            async with conn.execute(
                f"SELECT ticker, last_price, fetched_at FROM quotes_cache WHERE ticker IN ({placeholders})",
                missing,
            ) as cur:
                rows = await cur.fetchall()
            l2_fresh: dict[str, float | None] = {}
            for ticker, last_price, fetched_at in rows:
                if now - float(fetched_at) < self._ttl:
                    l2_fresh[ticker] = last_price
            # Promote L2 hits to L1
            async with self._l1_lock:
                for ticker, price in l2_fresh.items():
                    self._l1[ticker] = (price, now)
                    result[ticker] = price
            missing = [m for m in missing if m not in l2_fresh]

        # Origin: call fetcher
        if missing:
            try:
                fetched = await fetcher(missing)
            except (OSError, ValueError, TypeError, RuntimeError) as exc:
                logger.warning("Quote fetcher failed for %s: %s", missing, exc)
                fetched = dict.fromkeys(missing)
            now = time.time()
            conn = await self._conn_ready()
            async with self._l1_lock:
                for sym in missing:
                    price = fetched.get(sym)
                    self._l1[sym] = (price, now)
                    result[sym] = price
                    await conn.execute(
                        """
                        INSERT INTO quotes_cache (ticker, last_price, fetched_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(ticker) DO UPDATE SET
                            last_price = excluded.last_price,
                            fetched_at = excluded.fetched_at
                        """,
                        (sym, price, now),
                    )
            await conn.commit()

        return result

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_quote_cache.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add finrobot/engine/data/quote_cache.py tests/unit/test_quote_cache.py
git commit -m "feat(data): QuoteCache with L1 in-memory + L2 SQLite (60s TTL)"
```

---

## Task 6: Rewrite quote_batch.py to use QuoteCache

**Files:**
- Modify: `finrobot/engine/data/quote_batch.py`
- Modify: `tests/unit/test_quote_batch.py`

- [ ] **Step 1: Update tests to assert cache behaviour**

Read existing `tests/unit/test_quote_batch.py` first to preserve coverage, then add:

```python
# Append to tests/unit/test_quote_batch.py

import pytest
from unittest.mock import patch

from finrobot.engine.data.quote_batch import fetch_quotes_batch_cached, reset_quote_cache_singleton


@pytest.mark.asyncio
async def test_fetch_quotes_batch_cached_is_warm_on_second_call(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    reset_quote_cache_singleton()

    yf_calls: list[list[str]] = []

    def fake_yf(tickers):
        yf_calls.append(list(tickers))
        return {t: 200.0 for t in tickers}

    with patch("finrobot.engine.data.quote_batch._fetch_via_yfinance", side_effect=fake_yf):
        out1 = await fetch_quotes_batch_cached(["AAPL", "MSFT"])
        assert out1 == {"AAPL": 200.0, "MSFT": 200.0}
        assert len(yf_calls) == 1

        out2 = await fetch_quotes_batch_cached(["AAPL"])
        assert out2 == {"AAPL": 200.0}
        assert len(yf_calls) == 1  # served from L1


@pytest.mark.asyncio
async def test_empty_batch_is_no_op(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    reset_quote_cache_singleton()
    out = await fetch_quotes_batch_cached([])
    assert out == {}
```

- [ ] **Step 2: Rewrite `finrobot/engine/data/quote_batch.py`**

Keep the synchronous `fetch_quotes_batch` for backwards compatibility (still used by some routes), but add async `fetch_quotes_batch_cached` as the new entry point:

```python
"""Batched live-quote helpers.

Two entry points:
  fetch_quotes_batch(tickers)       — synchronous, direct yfinance, no cache
                                       Kept for backwards compat with callers
                                       wrapped in asyncio.to_thread.
  fetch_quotes_batch_cached(tickers) — async, two-layer cache (in-memory + SQLite)
                                        Use this in routes and pipelines.

L2 cache TTL is 60s. Per-ticker failures are cached as None so we don't
hammer yfinance for a delisted symbol.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

from finrobot.engine.data.quote_cache import QuoteCache

logger = logging.getLogger(__name__)


_GLOBAL_QUOTE_CACHE: QuoteCache | None = None


def reset_quote_cache_singleton() -> None:
    """Drop the process-wide QuoteCache. Tests only."""
    global _GLOBAL_QUOTE_CACHE
    _GLOBAL_QUOTE_CACHE = None


def _get_singleton() -> QuoteCache:
    global _GLOBAL_QUOTE_CACHE
    if _GLOBAL_QUOTE_CACHE is None:
        _GLOBAL_QUOTE_CACHE = QuoteCache()
    return _GLOBAL_QUOTE_CACHE


def _fetch_via_yfinance(tickers: list[str]) -> dict[str, float | None]:
    """Synchronous yfinance call — intended to be wrapped in asyncio.to_thread."""
    if not tickers:
        return {}
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance unavailable — returning all-None quote batch")
        return dict.fromkeys(tickers)

    try:
        container = yf.Tickers(" ".join(tickers))
    except (ValueError, OSError) as exc:
        logger.warning("yf.Tickers init failed (%s) — falling back to per-ticker", exc)
        return {sym: _fetch_one(sym) for sym in tickers}

    out: dict[str, float | None] = {}
    for sym in tickers:
        try:
            t = container.tickers.get(sym) or container.tickers.get(sym.upper())
            if t is None:
                out[sym] = None
                continue
            info = t.fast_info
            price = getattr(info, "last_price", None) or getattr(info, "lastPrice", None)
            out[sym] = float(price) if price is not None else None
        except (AttributeError, ValueError, TypeError, OSError):
            logger.exception("Quote fetch failed for %s", sym)
            out[sym] = None
    return out


def _fetch_one(symbol: str) -> float | None:
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).fast_info
        price = getattr(info, "last_price", None) or getattr(info, "lastPrice", None)
        return float(price) if price is not None else None
    except (ImportError, AttributeError, ValueError, TypeError, OSError):
        logger.exception("Single-ticker fallback failed for %s", symbol)
        return None


def fetch_quotes_batch(tickers: Iterable[str]) -> dict[str, float | None]:
    """Synchronous, no-cache. Direct yfinance. Use only when async isn't available."""
    return _fetch_via_yfinance([t.strip().upper() for t in tickers if t and t.strip()])


async def fetch_quotes_batch_cached(tickers: Iterable[str]) -> dict[str, float | None]:
    """Async, two-layer cached. Preferred entry point for routes + pipelines."""
    syms = [t.strip().upper() for t in tickers if t and t.strip()]
    if not syms:
        return {}
    cache = _get_singleton()

    async def yf_async(missing: list[str]) -> dict[str, float | None]:
        return await asyncio.to_thread(_fetch_via_yfinance, missing)

    return await cache.get_batch(syms, fetcher=yf_async)
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `pytest tests/unit/test_quote_batch.py tests/unit/test_quote_cache.py -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add finrobot/engine/data/quote_batch.py tests/unit/test_quote_batch.py
git commit -m "feat(data): route quote_batch through QuoteCache singleton"
```

---

## Task 7: dashboard.py — remove N+1 verdict reads + use cached quotes

**Files:**
- Modify: `finrobot/routes/dashboard.py`
- Modify: `tests/routes/test_dashboard_landing.py`

- [ ] **Step 1: Add a regression test for store.get() call count**

Add to `tests/routes/test_dashboard_landing.py`:

```python
@pytest.mark.asyncio
async def test_hit_rate_does_not_call_store_get(client, deps_with_artifacts):
    """The hit-rate aggregation must use ArtifactSummary.verdict from index
    rather than reloading the full artifact (the legacy N+1 path)."""
    store = deps_with_artifacts.artifact_store
    original_get = store.get
    calls: list[str] = []

    async def counting_get(artifact_id):
        calls.append(artifact_id)
        return await original_get(artifact_id)

    store.get = counting_get

    resp = await client.get("/api/dashboard/hit-rate?window=all")
    assert resp.status_code == 200
    assert calls == [], f"hit-rate called store.get {len(calls)} times, expected 0"


@pytest.mark.asyncio
async def test_recent_research_uses_summary_verdict(client, deps_with_artifacts):
    """recent-research should also rely on summary.verdict, not store.get()."""
    store = deps_with_artifacts.artifact_store
    original_get = store.get
    calls: list[str] = []

    async def counting_get(artifact_id):
        calls.append(artifact_id)
        return await original_get(artifact_id)

    store.get = counting_get

    resp = await client.get("/api/dashboard/recent-research?limit=5")
    assert resp.status_code == 200
    assert calls == [], f"recent-research called store.get {len(calls)} times, expected 0"
```

(Conftest fixture `deps_with_artifacts` must seed a few artifacts with non-null verdict via the actual SqliteArtifactStore — check existing fixture pattern in `tests/routes/test_dashboard_landing.py` and extend if missing.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/routes/test_dashboard_landing.py::test_hit_rate_does_not_call_store_get -v`
Expected: FAIL (currently calls store.get N times for verdict extraction)

- [ ] **Step 3: Modify `finrobot/routes/dashboard.py`**

Edit `_collect_signal_inputs` at line 771-812:

```python
async def _collect_signal_inputs(store: Any) -> list[Any]:
    """Walk artifact summaries → ArtifactSignalInput list (with live prices).

    Uses ArtifactSummary.verdict directly — does NOT reload the full artifact.
    The summary is the index column; verdict was extracted at save time.
    """
    from finrobot.engine.aggregations.hit_rate_overview import ArtifactSignalInput
    from finrobot.engine.data.quote_batch import fetch_quotes_batch_cached

    summaries = await store.list_by_ticker(
        ticker=None, include_archived=False, limit=500
    )
    if not summaries:
        return []

    tickers = sorted({s.ticker for s in summaries if s.ticker})
    quotes = await fetch_quotes_batch_cached(tickers)

    return [
        ArtifactSignalInput(
            entry_price=s.entry_price,
            target_price=s.target_price,
            current_price=quotes.get(s.ticker) if s.ticker else None,
            entry_date=s.created_at,
            target_date=s.target_date,
            verdict=s.verdict,  # <- from summary index, NOT from full artifact
        )
        for s in summaries
    ]
```

Edit `recent_research` handler around line 694-735:

```python
    # Per-row verdict: use summary.verdict directly — no need to reload the
    # full artifact, the summary column was extracted at save time.
    inputs: list[RecentResearchInput] = []
    for ticker in top_tickers:
        group = sorted(by_ticker[ticker], key=lambda s: s.created_at, reverse=True)
        latest = group[0]
        current = quotes.get(ticker)
        for s in group:
            is_latest = s.id == latest.id
            inputs.append(
                RecentResearchInput(
                    artifact_id=s.id,
                    ticker=s.ticker,
                    cross_tickers=tuple(s.cross_tickers),
                    type=s.type,
                    headline=s.headline,
                    verdict=s.verdict,  # <- from summary, not extract_verdict(art)
                    entry_price=s.entry_price,
                    target_price=s.target_price,
                    target_date=s.target_date,
                    current_price=current if is_latest else None,
                    created_at=s.created_at,
                )
            )
```

Replace the `quotes = await asyncio.to_thread(fetch_quotes_batch, top_tickers)` call at line 689 with:

```python
    quotes = await fetch_quotes_batch_cached(top_tickers)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/routes/test_dashboard_landing.py -v`
Expected: All pass (including 2 new regression tests)

- [ ] **Step 5: Commit**

```bash
git add finrobot/routes/dashboard.py tests/routes/test_dashboard_landing.py
git commit -m "perf(dashboard): drop N+1 verdict reads, use cached quote batch"
```

---

## Task 8: Lifespan quote warmup + verification

**Files:**
- Modify: `finrobot/server.py`

- [ ] **Step 1: Add quote warmup task to lifespan**

In `finrobot/server.py` lifespan, after the migration task:

```python
async def _warm_quote_cache_background() -> None:
    """On startup, warm QuoteCache for studied tickers so the first
    landing-page load doesn't pay the cold yfinance penalty."""
    try:
        summaries = await artifact_store.list_by_ticker(
            ticker=None, include_archived=False, limit=500
        )
        tickers = sorted({s.ticker for s in summaries if s.ticker})
        if not tickers:
            return
        from finrobot.engine.data.quote_batch import fetch_quotes_batch_cached
        await fetch_quotes_batch_cached(tickers)
        logger.info("Quote cache warmed for %d studied tickers", len(tickers))
    except (OSError, ValueError, TypeError, RuntimeError):
        logger.exception("Quote cache warmup failed — non-fatal")

asyncio.create_task(_warm_quote_cache_background())
```

- [ ] **Step 2: Restart server and measure latency**

Run:
```bash
# Kill running server, restart from .venv/bin/finrobot serve
pkill -f "finrobot serve" || true
.venv/bin/finrobot serve --host 127.0.0.1 --port 8321 --reload &
sleep 8  # give warmup time
curl -s -o /dev/null -w "hit-rate: %{time_total}s\n" http://127.0.0.1:8321/api/dashboard/hit-rate
curl -s -o /dev/null -w "recent-research: %{time_total}s\n" "http://127.0.0.1:8321/api/dashboard/recent-research?limit=5"
```

Expected: both endpoints return in < 500ms on cold curl (warmup already populated quote cache).

- [ ] **Step 3: Commit**

```bash
git add finrobot/server.py
git commit -m "feat(server): warm QuoteCache on startup for studied tickers"
```

---

## Task 9: Full-system verification + docs

**Files:**
- Modify: `CLAUDE.md` — storage section
- Create: `project-memory/编码模式/存储架构-SQLite统一.md`
- Modify: `/Users/zhunihaoyun/.claude/projects/-Users-zhunihaoyun-Desktop-code-FinRobot/memory/MEMORY.md`

- [ ] **Step 1: Run the full backend test suite**

Run: `pytest tests/ -m "not slow" -q`
Expected: all green (~1489 tests, 8+ skipped)

Run: `ruff check finrobot/ tests/`
Expected: all clean

Run: `mypy finrobot/`
Expected: all clean

- [ ] **Step 2: Run the frontend smoke test**

```bash
cd ui
npm run build
```
Expected: build success, no TS errors.

```bash
npm run test
```
Expected: 250+ vitest pass.

- [ ] **Step 3: Restart Tauri dev shell + verify landing latency**

```bash
# Already running: target/debug/finrobot-desktop and vite
# After Task 8 server restart, open the app, navigate to /stocks
# Open devtools Network tab → reload → confirm:
#   /api/dashboard/hit-rate finishes < 500ms
#   /api/dashboard/recent-research finishes < 300ms
#   No requests to ~/.finrobot-desktop/artifacts/
```

- [ ] **Step 4: Update `CLAUDE.md` storage section**

Replace the data layer description (search for "数据层 `engine/data/`") with:

```markdown
- **存储路径**（统一在 `~/.finrobot/`）：
  - `artifacts.db` — 投资研报 SQLite（`SqliteArtifactStore`，二级索引在 `(ticker, created_at)` / `verdict` / `archived`）
  - `quotes.db` — 实时报价 L2 缓存（60s TTL，配合 `QuoteCache` 进程内 L1）
  - `data_cache.db` — provider 响应缓存（yfinance / FMP / Finnhub / SEC EDGAR）
  - `runs.db` — pipeline SSE 事件流 + run 元数据
  - `settings.json` — 用户配置
- **旧路径自动迁移**：首次启动检测到 `~/.finrobot-desktop/artifacts/` 或 `~/.cache/finrobot/cache.db` 时一次性搬运到 `~/.finrobot/`，安全幂等
- **数据层** `engine/data/` — providers + `DataCache` (aiosqlite + WAL) + `QuoteCache` (L1 内存 + L2 SQLite) + WeakValueDictionary 防 stampede
```

- [ ] **Step 5: Create project memory note**

Create `project-memory/编码模式/存储架构-SQLite统一.md`:

```markdown
# 存储架构：统一在 ~/.finrobot/ 的 SQLite

**Why（决策日期 2026-05-23）**：
- 旧 `ArtifactStore` 用文件系统 + per-ticker `index.json`，无 secondary index，规模 100+ artifact 时 list_by_ticker(None) 慢
- 旧路径分裂 `~/.finrobot-desktop/artifacts/` + `~/.cache/finrobot/cache.db` + `~/.finrobot/runs.db` 不利备份/迁移
- 首页冷启动 4-5s 主要由 yfinance 同步报价 fan-out 拖累；缺一个跨调用方共享的 quote cache 层

**How**：
- 所有 SQLite db 文件统一住在 `~/.finrobot/`（artifacts / quotes / data_cache / runs）
- `SqliteArtifactStore` 在 `(ticker, created_at)` / `verdict` / `archived` 建索引；`ArtifactSummary.verdict` 在写入时一次性 extract 持久化到列，避免读全 JSON
- `QuoteCache` 双层：L1 进程内 dict + L2 `quotes.db`，60s TTL；两个 dashboard 接口经 `fetch_quotes_batch_cached` 共享同一份缓存
- Lifespan 启动后台预热：迁移旧 artifact JSON 到 SQLite + 把当前 studied tickers 的报价预填到 QuoteCache

**Where to look**:
- `finrobot/paths.py` — 路径单一来源
- `finrobot/artifact/sqlite_store.py` — Artifact CRUD + 索引化 verdict
- `finrobot/engine/data/quote_cache.py` — 报价双层缓存
- `finrobot/artifact/migrate.py` — 旧文件系统 → SQLite 一次性脚本（lifespan 自动跑）
```

- [ ] **Step 6: Update `MEMORY.md` index**

Append to `/Users/zhunihaoyun/.claude/projects/-Users-zhunihaoyun-Desktop-code-FinRobot/memory/MEMORY.md` under `## Project`:

```markdown
- [project_storage_architecture.md](project_storage_architecture.md) — All state in ~/.finrobot/*.db (SQLite WAL); ArtifactStore is SQLite with indexed verdict; QuoteCache double-layer L1/L2
```

Then write `/Users/zhunihaoyun/.claude/projects/-Users-zhunihaoyun-Desktop-code-FinRobot/memory/project_storage_architecture.md` with the same body content as the project-memory note above.

- [ ] **Step 7: Final commit**

```bash
git add CLAUDE.md project-memory/编码模式/存储架构-SQLite统一.md
git commit -m "docs: update storage architecture to unified ~/.finrobot/ + SQLite ArtifactStore"
```

---

## Self-Review Summary

**Spec coverage:**
- ✅ Artifact filesystem → SQLite migration (Tasks 1-4)
- ✅ Path unification under ~/.finrobot/ (Task 1, Task 4 step 3)
- ✅ Quote double-layer cache (Tasks 5-6)
- ✅ dashboard.py N+1 removal (Task 7)
- ✅ Lifespan warmup (Task 8)
- ✅ Documentation (Task 9)
- ✅ Verification: pytest + ruff + mypy + npm build + curl latency (Task 9)

**Type consistency check:**
- `SqliteArtifactStore.get` returns `Artifact | None` ✓ (matches legacy)
- `QuoteCache.get_batch` returns `dict[str, float | None]` ✓ (matches `fetch_quotes_batch` signature)
- `fetch_quotes_batch_cached(tickers: Iterable[str])` async ✓; `fetch_quotes_batch` stays sync for backwards compat ✓
- `_collect_signal_inputs` returns `list[ArtifactSignalInput]` ✓ (same as before)
- `ArtifactSummary.verdict` already exists (verified at `finrobot/artifact/models.py:174`)

**Performance assertion:**
- After Task 8 warmup, cold curl on landing endpoints should be < 500ms (down from 4.8s/1.79s)
- L1 hit path = pure dict lookup, sub-millisecond
- L2 hit path = single SELECT on indexed PK, ~1ms
- Cold L2 miss = single yfinance call shared across all callers within 60s TTL window
