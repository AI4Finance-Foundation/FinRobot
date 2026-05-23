"""Unified storage path resolution.

Single source of truth for every FinAgent state directory or db file.
All paths live under ~/.finagent/ for backup symmetry and so users can
nuke state with one ``rm -rf ~/.finagent/``.

Legacy paths (~/.cache/finagent/, ~/.finagent-desktop/) can be migrated
into ~/.finagent/ via :func:`migrate_legacy_paths`, which is called from
the server lifespan on startup (idempotent, safe to run repeatedly).

Why a separate module: every storage class (ArtifactStore, RunStore,
DataCache, QuoteCache, JournalDb, TranscriptWriter) used to bake in its
own default path with a ``Path.home() / ".something"`` literal — diffs
across them drift, and testing required monkey-patching each module
separately. One module, one set of constants, one migration entry point.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def _home() -> Path:
    return Path.home()


FINAGENT_HOME: Path = _home() / ".finagent"
ARTIFACTS_DB: Path = FINAGENT_HOME / "artifacts.db"
QUOTES_DB: Path = FINAGENT_HOME / "quotes.db"
DATA_CACHE_DB: Path = FINAGENT_HOME / "data_cache.db"
RUNS_DB: Path = FINAGENT_HOME / "runs.db"
JOURNAL_DB: Path = FINAGENT_HOME / "journal.db"
SESSIONS_DIR: Path = FINAGENT_HOME / "sessions"
SETTINGS_JSON: Path = FINAGENT_HOME / "settings.json"


def ensure_home() -> Path:
    """Create ``~/.finagent/`` if it does not exist. Returns the dir path."""
    FINAGENT_HOME.mkdir(parents=True, exist_ok=True)
    return FINAGENT_HOME


def default_data_cache_db_path() -> str:
    """Return the default DataCache SQLite path.

    Resolves to ``~/.finagent/data_cache.db`` by default. The legacy
    in-repo ``finagent_cache.db`` is still honoured when it exists so an
    existing dev setup keeps working without a config change.

    Lives in :mod:`finagent.paths` (not ``finagent.config``) so the storage
    layer's "where do files live" knowledge stays in one module.
    """
    legacy = Path("finagent_cache.db")
    if legacy.exists():
        return str(legacy)
    ensure_home()
    return str(DATA_CACHE_DB)


_LEGACY_DB_MOVES: list[tuple[Path, Path]] = [
    (_home() / ".cache" / "finagent" / "cache.db", DATA_CACHE_DB),
    (_home() / ".finagent-desktop" / "journal.db", JOURNAL_DB),
]

_LEGACY_DIR_MOVES: list[tuple[Path, Path]] = [
    (_home() / ".finagent-desktop" / "sessions", SESSIONS_DIR),
]


def migrate_legacy_paths() -> dict[str, str]:
    """Move legacy storage to the unified ``~/.finagent/`` home.

    Idempotent: only moves a file/dir when the legacy path exists AND the
    new path does not. If both exist the legacy file/dir is left in place
    so the user can decide which copy to keep.

    Returns a ``{legacy_path: new_path}`` mapping of moves actually
    performed (empty dict on no-op).
    """
    ensure_home()
    migrations: dict[str, str] = {}

    for legacy, new in _LEGACY_DB_MOVES:
        if not legacy.exists() or new.exists():
            continue
        try:
            shutil.move(str(legacy), str(new))
            migrations[str(legacy)] = str(new)
            for suffix in ("-wal", "-shm"):
                side_legacy = legacy.with_name(legacy.name + suffix)
                if side_legacy.exists():
                    shutil.move(
                        str(side_legacy),
                        str(new.with_name(new.name + suffix)),
                    )
        except OSError as exc:
            logger.warning("Could not migrate %s → %s: %s", legacy, new, exc)

    for legacy, new in _LEGACY_DIR_MOVES:
        if not legacy.exists() or new.exists():
            continue
        try:
            shutil.move(str(legacy), str(new))
            migrations[str(legacy)] = str(new)
        except OSError as exc:
            logger.warning("Could not migrate %s → %s: %s", legacy, new, exc)

    return migrations
