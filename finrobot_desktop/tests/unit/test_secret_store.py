from __future__ import annotations

import logging
import os
import stat
import sys
from pathlib import Path
from typing import Any

import keyring.errors
import pytest

import finrobot.secret_store as secret_store_module
from finrobot.secret_store import (
    FileSecretStore,
    KeychainSecretStore,
    SecretStoreError,
    create_secret_store,
)


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


@pytest.mark.asyncio
async def test_parent_permission_lock_failure_is_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "secrets" / ".secrets"
    store = FileSecretStore(path)
    real_chmod = os.chmod

    def deny_chmod(target: Path | str, mode: int) -> None:
        if Path(target) == path.parent:
            raise OSError("chmod denied")
        real_chmod(target, mode)

    monkeypatch.setattr("finrobot.secret_store.os.chmod", deny_chmod)

    with pytest.raises(SecretStoreError, match="could not be permission-locked"):
        await store.set("k", "v")


# ---------------------------------------------------------------------------
# KeychainSecretStore — runtime keychain refusal must degrade, not crash.
# The boot-time probe only proves the backend worked ONCE; the user can click
# "Deny" on the macOS prompt (KeyringLocked) at any later call. Reads degrade
# to None/False with one warning per key; writes raise SecretStoreError so a
# failed save is never reported as success.
# ---------------------------------------------------------------------------


class _RefusingKeyring:
    """Stand-in for the keyring module whose backend rejects every call."""

    errors = keyring.errors

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def get_password(self, service: str, key: str) -> str | None:
        raise self.exc

    def set_password(self, service: str, key: str, value: str) -> None:
        raise self.exc

    def delete_password(self, service: str, key: str) -> None:
        raise self.exc


def _refusing_store(exc: Exception | None = None) -> KeychainSecretStore:
    """Build a KeychainSecretStore around a refusing backend, skipping the
    constructor probe (which touches the real OS keychain)."""
    store = KeychainSecretStore.__new__(KeychainSecretStore)
    store._keyring = _RefusingKeyring(  # type: ignore[assignment]
        exc or keyring.errors.KeyringLocked("Can't get password: user denied access")
    )
    store._service_name = "FinRobotTest"
    store._degraded_keys = set()
    return store


@pytest.mark.asyncio
async def test_keychain_get_denied_degrades_to_none(caplog: Any) -> None:
    store = _refusing_store()
    with caplog.at_level(logging.WARNING, logger="finrobot.secret_store"):
        assert await store.get("fmp_api_key") is None
        assert await store.get("fmp_api_key") is None  # second read: no new warning
        assert await store.get("finnhub_api_key") is None  # new key: its own warning

    warnings = [r for r in caplog.records if "treating the secret as unset" in r.getMessage()]
    assert len(warnings) == 2  # one per key, not one per call
    assert "fmp_api_key" in warnings[0].getMessage()


@pytest.mark.asyncio
async def test_keychain_has_denied_degrades_to_false() -> None:
    store = _refusing_store()
    assert await store.has("fmp_api_key") is False


@pytest.mark.asyncio
async def test_keychain_set_denied_raises_secret_store_error() -> None:
    store = _refusing_store()
    with pytest.raises(SecretStoreError) as excinfo:
        await store.set("fmp_api_key", "sk-super-secret-value")
    # The error names the key but NEVER carries the secret value.
    assert "fmp_api_key" in str(excinfo.value)
    assert "sk-super-secret-value" not in str(excinfo.value)


@pytest.mark.asyncio
async def test_keychain_delete_missing_key_is_idempotent() -> None:
    store = _refusing_store(keyring.errors.PasswordDeleteError("not found"))
    await store.delete("fmp_api_key")  # must not raise


@pytest.mark.asyncio
async def test_keychain_delete_denied_raises_secret_store_error() -> None:
    store = _refusing_store(keyring.errors.KeyringLocked("keychain locked"))
    with pytest.raises(SecretStoreError):
        await store.delete("fmp_api_key")


# ---------------------------------------------------------------------------
# create_secret_store — platform-aware, prompt-free backend selection.
# macOS has no prompt-free keychain without a stable code signature, so it
# defaults to the file; Windows/Linux use the silent OS credential store.
# ---------------------------------------------------------------------------


def _forbid_keychain(monkeypatch: Any) -> None:
    """Fail loudly if KeychainSecretStore is constructed — proves the macOS and
    dev paths never touch the OS keychain (the whole point of the fix)."""

    def _boom(*_a: Any, **_k: Any) -> None:
        raise AssertionError("KeychainSecretStore must not be constructed here")

    monkeypatch.setattr(secret_store_module, "KeychainSecretStore", _boom)


def test_create_store_dev_mode_uses_file(monkeypatch: Any) -> None:
    monkeypatch.delenv("FINROBOT_DEV_MODE", raising=False)
    _forbid_keychain(monkeypatch)
    store, mode = create_secret_store(dev_mode=True)
    assert isinstance(store, FileSecretStore)
    assert mode == "plaintext"


def test_create_store_dev_mode_via_env(monkeypatch: Any) -> None:
    monkeypatch.setenv("FINROBOT_DEV_MODE", "1")
    _forbid_keychain(monkeypatch)
    _, mode = create_secret_store()
    assert mode == "plaintext"


def test_create_store_macos_defaults_to_file(monkeypatch: Any) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("FINROBOT_DEV_MODE", raising=False)
    monkeypatch.delenv("FINROBOT_USE_KEYCHAIN", raising=False)
    _forbid_keychain(monkeypatch)  # macOS must skip the keychain entirely
    store, mode = create_secret_store()
    assert isinstance(store, FileSecretStore)
    assert mode == "plaintext"


def test_create_store_macos_opt_in_keychain(monkeypatch: Any) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("FINROBOT_DEV_MODE", raising=False)
    monkeypatch.setenv("FINROBOT_USE_KEYCHAIN", "1")
    sentinel = object()
    monkeypatch.setattr(secret_store_module, "KeychainSecretStore", lambda *_a, **_k: sentinel)
    store, mode = create_secret_store()
    assert store is sentinel
    assert mode == "keychain"


def test_create_store_windows_uses_keychain(monkeypatch: Any) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("FINROBOT_DEV_MODE", raising=False)
    sentinel = object()
    monkeypatch.setattr(secret_store_module, "KeychainSecretStore", lambda *_a, **_k: sentinel)
    store, mode = create_secret_store()
    assert store is sentinel
    assert mode == "keychain"


def test_create_store_keychain_unavailable_falls_back_to_file(monkeypatch: Any) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("FINROBOT_DEV_MODE", raising=False)

    def _boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("no functional backend")

    monkeypatch.setattr(secret_store_module, "KeychainSecretStore", _boom)
    store, mode = create_secret_store()
    assert isinstance(store, FileSecretStore)
    assert mode == "plaintext"


@pytest.mark.asyncio
async def test_secret_dir_tightened_to_0700(tmp_path: Path) -> None:
    sub = tmp_path / "nested"
    sub.mkdir(mode=0o755)
    store = FileSecretStore(sub / ".secrets")
    await store.set("k", "v")
    assert stat.S_IMODE(sub.stat().st_mode) == 0o700
