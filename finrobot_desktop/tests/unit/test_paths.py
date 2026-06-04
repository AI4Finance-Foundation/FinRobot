"""Storage path constants.

`finrobot.paths` is the single source of truth for every state file location
under ``~/.finrobot/``. These tests pin the constant resolution so refactors
don't silently move a database off the unified home (which would split a
user's history across two directories).
"""

from __future__ import annotations

import importlib
from pathlib import Path


def _reload_paths(home: Path):
    """Re-import finrobot.paths under a swapped HOME so module-level
    constants pick up the override."""
    import finrobot.paths as paths_module

    return importlib.reload(paths_module)


def test_constants_resolve_under_finrobot_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    paths = _reload_paths(tmp_path)

    assert paths.FINROBOT_HOME == tmp_path / ".finrobot"
    assert paths.ARTIFACTS_DB == tmp_path / ".finrobot" / "artifacts.db"
    assert paths.QUOTES_DB == tmp_path / ".finrobot" / "quotes.db"
    assert paths.DATA_CACHE_DB == tmp_path / ".finrobot" / "data_cache.db"
    assert paths.RUNS_DB == tmp_path / ".finrobot" / "runs.db"
    assert paths.SESSIONS_DIR == tmp_path / ".finrobot" / "sessions"
    assert paths.SETTINGS_JSON == tmp_path / ".finrobot" / "settings.json"


def test_ensure_home_creates_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    paths = _reload_paths(tmp_path)

    paths.ensure_home()
    assert (tmp_path / ".finrobot").is_dir()


def test_default_data_cache_db_path_uses_unified_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    paths = _reload_paths(tmp_path)

    result = paths.default_data_cache_db_path()
    assert result == str(tmp_path / ".finrobot" / "data_cache.db")


def test_logs_dir_under_home() -> None:
    from finrobot import paths

    assert paths.LOGS_DIR == paths.FINROBOT_HOME / "logs"


def test_ensure_home_creates_logs_dir(tmp_path, monkeypatch) -> None:
    from finrobot import paths

    monkeypatch.setattr(paths, "FINROBOT_HOME", tmp_path / ".finrobot")
    monkeypatch.setattr(paths, "LOGS_DIR", tmp_path / ".finrobot" / "logs")
    paths.ensure_home()
    assert (tmp_path / ".finrobot" / "logs").is_dir()
