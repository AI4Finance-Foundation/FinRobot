from __future__ import annotations

import asyncio
import json
import logging
import os
import stat
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger(__name__)


class SecretStore(ABC):
    """Abstract secret storage.

    Business code calls this interface and never touches the underlying
    storage mechanism directly.
    """

    @abstractmethod
    async def get(self, key: str) -> str | None:
        """Retrieve a secret by key. Returns None if not set."""

    @abstractmethod
    async def set(self, key: str, value: str) -> None:
        """Store a secret."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove a secret."""

    @abstractmethod
    async def has(self, key: str) -> bool:
        """Check if a secret exists without retrieving it."""


class KeychainSecretStore(SecretStore):
    """OS keychain-backed secret storage via the optional keyring package."""

    def __init__(self, service_name: str = "FinAgent") -> None:
        try:
            import keyring
        except ImportError as e:
            raise RuntimeError("keyring package is not available") from e
        # Probe: verify the keyring backend is functional. In headless
        # environments (CI / Docker / WSL) keyring imports fine but raises
        # NoKeyringError on the first real call.
        try:
            keyring.get_password(service_name, "__finagent_probe__")
        except keyring.errors.KeyringError as e:
            raise RuntimeError(f"keyring backend not functional: {e}") from e
        self._keyring = keyring
        self._service_name = service_name

    async def get(self, key: str) -> str | None:
        return await asyncio.to_thread(self._keyring.get_password, self._service_name, key)

    async def set(self, key: str, value: str) -> None:
        try:
            await asyncio.to_thread(self._keyring.set_password, self._service_name, key, value)
        except self._keyring.errors.PasswordSetError:
            # Re-raise without the value to avoid leaking secrets in tracebacks.
            raise RuntimeError(f"Failed to store secret '{key}' in keychain")

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(self._keyring.delete_password, self._service_name, key)
        except self._keyring.errors.PasswordDeleteError:
            return

    async def has(self, key: str) -> bool:
        return await self.get(key) is not None


class FileSecretStore(SecretStore):
    """Development fallback secret store.

    This is intentionally local-only and permission-locked. Production desktop
    builds should use KeychainSecretStore whenever the OS backend is available.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path or Path.home() / ".finagent" / ".secrets")
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> str | None:
        data = await self._read_all()
        return data.get(key)

    async def set(self, key: str, value: str) -> None:
        async with self._lock:
            data = await self._read_all_unlocked()
            data[key] = value
            await self._write_all_unlocked(data)

    async def delete(self, key: str) -> None:
        async with self._lock:
            data = await self._read_all_unlocked()
            data.pop(key, None)
            await self._write_all_unlocked(data)

    async def has(self, key: str) -> bool:
        return await self.get(key) is not None

    async def _read_all(self) -> dict[str, str]:
        async with self._lock:
            return await self._read_all_unlocked()

    async def _read_all_unlocked(self) -> dict[str, str]:
        await asyncio.to_thread(self._ensure_file)
        raw = await asyncio.to_thread(self._path.read_text)
        if not raw.strip():
            return {}
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("Secret file is malformed")
        return {str(k): str(v) for k, v in parsed.items()}

    async def _write_all_unlocked(self, data: dict[str, str]) -> None:
        await asyncio.to_thread(self._ensure_file)
        payload = json.dumps(data, indent=2, sort_keys=True)
        await asyncio.to_thread(self._atomic_write, payload)

    def _atomic_write(self, payload: str) -> None:
        """Write to a temp file then atomically replace to prevent data loss."""
        fd, tmp = tempfile.mkstemp(dir=str(self._path.parent), suffix=".tmp")
        try:
            os.write(fd, payload.encode())
            os.close(fd)
            fd = -1  # mark as closed
            os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
            os.replace(tmp, self._path)
        except BaseException:
            if fd >= 0:
                os.close(fd)
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def _ensure_file(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text("{}")
            os.chmod(self._path, stat.S_IRUSR | stat.S_IWUSR)
            return
        mode = stat.S_IMODE(self._path.stat().st_mode)
        expected = stat.S_IRUSR | stat.S_IWUSR
        if mode != expected:
            raise PermissionError(f"Secret file {self._path} must have 0600 permissions")


def create_secret_store(dev_mode: bool | None = None) -> SecretStore:
    """Create the best available secret store for this runtime."""

    use_dev = dev_mode
    if use_dev is None:
        use_dev = os.environ.get("FINAGENT_DEV_MODE") == "1"
    if use_dev:
        logger.info("Using FileSecretStore (dev mode)")
        return FileSecretStore()
    try:
        store = KeychainSecretStore()
        logger.info("Using KeychainSecretStore (OS keychain)")
        return store
    except RuntimeError as exc:
        logger.warning(
            "Keychain unavailable (%s), falling back to FileSecretStore. "
            "Secrets will be stored as a permission-locked local file.",
            exc,
        )
        return FileSecretStore()
