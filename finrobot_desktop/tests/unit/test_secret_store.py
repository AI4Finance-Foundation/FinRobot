from __future__ import annotations

import stat
from pathlib import Path

import pytest

from finrobot.secret_store import FileSecretStore


@pytest.mark.asyncio
async def test_file_secret_store_roundtrip(tmp_path: Path) -> None:
    store = FileSecretStore(tmp_path / ".secrets")
    await store.set("FMP_API_KEY", "abc123")
    assert await store.get("FMP_API_KEY") == "abc123"
    assert await store.has("FMP_API_KEY") is True
    await store.delete("FMP_API_KEY")
    assert await store.get("FMP_API_KEY") is None


@pytest.mark.asyncio
async def test_new_secret_file_is_created_0600(tmp_path: Path) -> None:
    path = tmp_path / ".secrets"
    store = FileSecretStore(path)
    await store.set("k", "v")
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == stat.S_IRUSR | stat.S_IWUSR


@pytest.mark.asyncio
async def test_perms_drift_self_heals_instead_of_crashing(tmp_path: Path) -> None:
    """BUG-083: mode != 0600 must self-heal (chmod back to 0600), not raise.

    Permission drift to a looser mode is a recoverable, real-world event
    (backup/restore, editor rewrite under umask, sync tools). Reading must
    tighten the file back to 0600 and continue rather than crash startup.
    """
    path = tmp_path / ".secrets"
    store = FileSecretStore(path)
    await store.set("FMP_API_KEY", "abc123")

    # Simulate external drift: editor rewrite / restored backup leaves 0644.
    path.chmod(0o644)
    assert stat.S_IMODE(path.stat().st_mode) == 0o644

    # Must NOT raise — self-heals and still returns the value.
    value = await store.get("FMP_API_KEY")
    assert value == "abc123"

    # File was tightened back to 0600.
    assert stat.S_IMODE(path.stat().st_mode) == stat.S_IRUSR | stat.S_IWUSR


@pytest.mark.asyncio
async def test_perms_drift_group_world_readable_self_heals(tmp_path: Path) -> None:
    path = tmp_path / ".secrets"
    store = FileSecretStore(path)
    await store.set("k", "v")

    path.chmod(0o666)  # world-writable drift
    # A subsequent write path also runs _ensure_file and must not crash.
    await store.set("k2", "v2")

    assert await store.get("k") == "v"
    assert await store.get("k2") == "v2"
    assert stat.S_IMODE(path.stat().st_mode) == stat.S_IRUSR | stat.S_IWUSR
