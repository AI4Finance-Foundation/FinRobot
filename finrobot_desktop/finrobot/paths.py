"""Unified storage path resolution.

Single source of truth for every FinRobot state directory or db file.
All paths live under ~/.finrobot/ for backup symmetry and so users can
nuke state with one ``rm -rf ~/.finrobot/``.

Why a separate module: every storage class (ArtifactStore, RunStore,
DataCache, QuoteCache, JournalDb, TranscriptWriter) used to bake in its
own default path with a ``Path.home() / ".something"`` literal — diffs
across them drift, and testing required monkey-patching each module
separately. One module, one set of constants.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger(__name__)

# Shared SQLite connection tuning. Every store opens WAL (one-writer-many-readers)
# + synchronous=NORMAL, but the default ``busy_timeout`` of 0 means a writer that
# hits the single-writer lock fails *immediately* with SQLITE_BUSY. SDK/CLI run as
# separate processes from the server against the same db files, so cross-process
# writes collide constantly. A 5 s busy_timeout makes SQLite wait+retry the lock
# instead of bubbling "database is locked" up to the caller (500 / failed run).
# This only smooths transient lock waits, not sustained-concurrency throughput.
SQLITE_BUSY_TIMEOUT_MS = 5000


async def configure_connection(conn: aiosqlite.Connection) -> None:
    """Apply the shared PRAGMA tuning to an aiosqlite connection.

    Call this immediately after ``aiosqlite.connect`` and before creating tables.
    """
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA synchronous=NORMAL")
    await conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")


def _home() -> Path:
    return Path.home()


def bundle_resource_root() -> Path:
    """Root directory for bundled read-only resources (``skills/`` etc.).

    Two runtime shapes:
    - **Frozen** (PyInstaller desktop sidecar): resources are unpacked under
      ``sys._MEIPASS``. There is no source tree and no repo root — the binary
      may be launched from anywhere (Tauri spawns it with an arbitrary cwd).
    - **Dev / pip install**: resolve relative to the source tree, i.e. the repo
      root two levels up from this file (``finrobot/paths.py`` → repo root).

    Resolving resources through this function instead of a bare relative path
    removes the implicit "cwd must be the repo root" assumption — which the old
    ``Path("skills")`` default silently relied on and which breaks both in a
    frozen bundle and when running the CLI from any other directory.
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def default_skills_dir() -> str:
    """Absolute path to the vendored ``skills/`` directory for this runtime."""
    return str(bundle_resource_root() / "skills")


FINROBOT_HOME: Path = _home() / ".finrobot"
ARTIFACTS_DB: Path = FINROBOT_HOME / "artifacts.db"
QUOTES_DB: Path = FINROBOT_HOME / "quotes.db"
DATA_CACHE_DB: Path = FINROBOT_HOME / "data_cache.db"
RUNS_DB: Path = FINROBOT_HOME / "runs.db"
# Coverage Desk: the user's research coverage universe (groups + members).
# Own db slot per the per-module convention (artifacts.db / runs.db / …) so a
# user's curated coverage is a first-class, backup-able research asset rather
# than localStorage that evaporates (see CoverageDesk plan M5 / ADR-0012).
COVERAGE_DB: Path = FINROBOT_HOME / "coverage.db"
SESSIONS_DIR: Path = FINROBOT_HOME / "sessions"
SETTINGS_JSON: Path = FINROBOT_HOME / "settings.json"
# 13F local holdings cache — reverse index built by
# scripts/refresh_sec_holdings.py because edgartools has no ticker→holders
# reverse API (probe 2026-05-27, see specs/research/edgartools_probe_findings_2026-05-27.md).
SEC_HOLDINGS_DB: Path = FINROBOT_HOME / "sec_holdings_cache.db"
LOGS_DIR: Path = FINROBOT_HOME / "logs"


def ensure_home() -> Path:
    """Create ``~/.finrobot/`` (and ``logs/``) if missing. Returns the dir path."""
    FINROBOT_HOME.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return FINROBOT_HOME


def default_data_cache_db_path() -> str:
    """Return the default DataCache SQLite path (``~/.finrobot/data_cache.db``)."""
    ensure_home()
    return str(DATA_CACHE_DB)
