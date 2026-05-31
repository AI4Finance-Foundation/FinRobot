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
from pathlib import Path

logger = logging.getLogger(__name__)


def _home() -> Path:
    return Path.home()


FINROBOT_HOME: Path = _home() / ".finrobot"
ARTIFACTS_DB: Path = FINROBOT_HOME / "artifacts.db"
QUOTES_DB: Path = FINROBOT_HOME / "quotes.db"
DATA_CACHE_DB: Path = FINROBOT_HOME / "data_cache.db"
RUNS_DB: Path = FINROBOT_HOME / "runs.db"
JOURNAL_DB: Path = FINROBOT_HOME / "journal.db"
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
