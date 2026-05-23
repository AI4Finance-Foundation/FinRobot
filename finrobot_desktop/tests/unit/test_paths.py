"""Path resolution + legacy auto-migration.

The previous storage paths were scattered across three locations:
  ~/.finagent-desktop/artifacts/  ArtifactStore (filesystem JSON)
  ~/.cache/finagent/cache.db      DataCache
  ~/.finagent/runs.db             RunStore

`finagent.paths` unifies them under `~/.finagent/` and exposes constants.
On `migrate_legacy_paths()` call, legacy db files are best-effort moved.
"""

from __future__ import annotations

import importlib
from pathlib import Path


def _reload_paths(home: Path):
    """Re-import finagent.paths under a swapped HOME so module-level
    constants pick up the override."""
    import finagent.paths as paths_module

    return importlib.reload(paths_module)


def test_constants_resolve_under_finagent_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    paths = _reload_paths(tmp_path)

    assert paths.FINAGENT_HOME == tmp_path / ".finagent"
    assert paths.ARTIFACTS_DB == tmp_path / ".finagent" / "artifacts.db"
    assert paths.QUOTES_DB == tmp_path / ".finagent" / "quotes.db"
    assert paths.DATA_CACHE_DB == tmp_path / ".finagent" / "data_cache.db"
    assert paths.RUNS_DB == tmp_path / ".finagent" / "runs.db"


def test_ensure_home_creates_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    paths = _reload_paths(tmp_path)

    paths.ensure_home()
    assert (tmp_path / ".finagent").is_dir()


def test_migrate_legacy_data_cache_moves_file(tmp_path, monkeypatch):
    """~/.cache/finagent/cache.db → ~/.finagent/data_cache.db"""
    monkeypatch.setenv("HOME", str(tmp_path))
    legacy = tmp_path / ".cache" / "finagent" / "cache.db"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy-content")

    paths = _reload_paths(tmp_path)
    moved = paths.migrate_legacy_paths()

    assert (tmp_path / ".finagent" / "data_cache.db").read_bytes() == b"legacy-content"
    assert not legacy.exists()
    assert str(legacy) in moved


def test_migrate_legacy_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    paths = _reload_paths(tmp_path)
    # No legacy files exist → no-op, no error
    assert paths.migrate_legacy_paths() == {}
    assert paths.migrate_legacy_paths() == {}


def test_migrate_legacy_does_not_overwrite_existing(tmp_path, monkeypatch):
    """If new path already exists, legacy is left alone (manual cleanup)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    legacy = tmp_path / ".cache" / "finagent" / "cache.db"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy")
    new = tmp_path / ".finagent" / "data_cache.db"
    new.parent.mkdir(parents=True)
    new.write_bytes(b"new")

    paths = _reload_paths(tmp_path)
    moved = paths.migrate_legacy_paths()

    assert new.read_bytes() == b"new"
    assert legacy.read_bytes() == b"legacy"
    assert moved == {}


def test_migrate_legacy_moves_wal_sidecars(tmp_path, monkeypatch):
    """SQLite WAL/SHM files must travel with the main db file."""
    monkeypatch.setenv("HOME", str(tmp_path))
    legacy_dir = tmp_path / ".cache" / "finagent"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "cache.db").write_bytes(b"main")
    (legacy_dir / "cache.db-wal").write_bytes(b"wal")
    (legacy_dir / "cache.db-shm").write_bytes(b"shm")

    paths = _reload_paths(tmp_path)
    paths.migrate_legacy_paths()

    target = tmp_path / ".finagent"
    assert (target / "data_cache.db").read_bytes() == b"main"
    assert (target / "data_cache.db-wal").read_bytes() == b"wal"
    assert (target / "data_cache.db-shm").read_bytes() == b"shm"
