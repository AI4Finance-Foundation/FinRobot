from __future__ import annotations

import logging
import stat
from pathlib import Path
from typing import Any

import keyring.errors
import pytest

from finrobot.secret_store import FileSecretStore, KeychainSecretStore, SecretStoreError


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
