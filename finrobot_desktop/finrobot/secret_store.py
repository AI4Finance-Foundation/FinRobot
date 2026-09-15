from __future__ import annotations

import asyncio
import json
import logging
import os
import stat
import sys
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

SecretStorageMode = Literal["keychain", "plaintext"]


class SecretStoreError(RuntimeError):
    """A secret could not be written to / deleted from the underlying store.

    Raised instead of the backend's own exception type so route handlers can
    surface ONE stable error to the user (a failed key save must never look
    like success, nor like an opaque 500). The message carries only the key
    name and the backend failure — never the secret value.
    """


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
    """OS keychain-backed secret storage via the optional keyring package.

    The constructor probe only proves the backend worked ONCE at boot — the
    keychain can still refuse at runtime (the user clicks "Deny" on the macOS
    access prompt, the keychain locks, the backend breaks mid-session). Every
    call therefore handles ``keyring.errors.KeyringError`` (keyring's documented
    base — the macOS backend wraps every Security.framework failure into it,
    denial included, as ``KeyringLocked``) plus ``OSError`` for backend file/IPC
    faults on other platforms. Reads degrade (None/False + one warning per key,
    same self-heal-over-crash stance as FileSecretStore's BUG-083 permission
    healing); writes raise :class:`SecretStoreError` so a failed key save is
    never reported as success. ``KeyboardInterrupt`` / ``CancelledError`` are
    BaseException and pass through untouched.
    """

    def __init__(self, service_name: str = "FinRobot") -> None:
        try:
            import keyring
        except ImportError as e:
            raise RuntimeError("keyring package is not available") from e
        # Probe: verify the keyring backend is functional. In headless
        # environments (CI / Docker / WSL) keyring imports fine but raises
        # NoKeyringError on the first real call.
        try:
            keyring.get_password(service_name, "__finrobot_probe__")
        except (keyring.errors.KeyringError, OSError) as e:
            raise RuntimeError(f"keyring backend not functional: {e}") from e
        self._keyring = keyring
        self._service_name = service_name
        # Keys whose reads already logged a degradation warning — one line per
        # key per process, not one per poll (GET /api/settings probes every key).
        self._degraded_keys: set[str] = set()

    def _warn_degraded_once(self, key: str, exc: Exception) -> None:
        if key in self._degraded_keys:
            return
        self._degraded_keys.add(key)
        logger.warning(
            "Keychain read for %r failed (%s: %s) — treating the secret as unset. "
            "Grant FinRobot keychain access (or unlock the keychain), then re-open "
            "Settings; re-enter the key if it stays missing.",
            key,
            type(exc).__name__,
            exc,
        )

    async def get(self, key: str) -> str | None:
        try:
            return await asyncio.to_thread(self._keyring.get_password, self._service_name, key)
        except (self._keyring.errors.KeyringError, OSError) as exc:
            # Denied/locked/broken keychain → behave as "not stored" instead of
            # crashing the caller: boot hydration then proceeds without keys
            # (validate_runtime_config surfaces THAT via the startup_error
            # banner) and GET /api/settings keeps answering instead of 500-ing.
            self._warn_degraded_once(key, exc)
            return None

    async def set(self, key: str, value: str) -> None:
        try:
            await asyncio.to_thread(self._keyring.set_password, self._service_name, key, value)
        except (self._keyring.errors.KeyringError, OSError) as exc:
            # Unlike reads, a failed WRITE must be loud — pretending the key was
            # saved strands the user with a config that dies on next boot. The
            # message carries the key name and backend error, never the value.
            raise SecretStoreError(
                f"Failed to store secret '{key}' in the OS keychain ({type(exc).__name__}: {exc})"
            ) from exc

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(self._keyring.delete_password, self._service_name, key)
        except self._keyring.errors.PasswordDeleteError:
            # Key absent — delete is idempotent. (On macOS a denied prompt also
            # lands here: the backend folds every delete failure into
            # PasswordDeleteError. The follow-up GET /api/settings re-reads the
            # keychain, so the UI reflects the real stored state either way.)
            return
        except (self._keyring.errors.KeyringError, OSError) as exc:
            # Backends that DO distinguish (locked keychain, IPC fault): the
            # secret is still stored, so the clear must not pretend success.
            raise SecretStoreError(
                f"Failed to delete secret '{key}' from the OS keychain "
                f"({type(exc).__name__}: {exc})"
            ) from exc

    async def has(self, key: str) -> bool:
        return await self.get(key) is not None


class FileSecretStore(SecretStore):
    """Local-file secret store — permission-locked JSON at ~/.finrobot/.secrets.

    Used whenever no prompt-free OS credential store is available: macOS without
    a stable code signature (an unsigned/ad-hoc app re-prompts on every keychain
    item, so we avoid the keychain there — see :func:`create_secret_store`),
    Linux with no Secret Service backend, and explicit dev mode. Secrets are
    stored in PLAINTEXT, protected by 0600 file perms (+ full-disk encryption
    like FileVault if the user has it on). Callers surface this honestly as
    ``secret_storage_mode="plaintext"``.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path or Path.home() / ".finrobot" / ".secrets")
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
        """Write to a temp file then atomically replace, fsync'ing both the file
        and the parent directory.

        Without the fsyncs, a crash right after the rename can leave a truncated
        or missing secrets file — and the Tauri shell SIGKILLs the sidecar on
        every app quit, so that crash window is hit routinely, not rarely.
        """
        fd, tmp = tempfile.mkstemp(dir=str(self._path.parent), suffix=".tmp")
        try:
            os.write(fd, payload.encode())
            os.fsync(fd)  # flush contents to disk before the rename
            os.close(fd)
            fd = -1  # mark as closed
            os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
            os.replace(tmp, self._path)
            self._fsync_parent_dir()  # make the rename itself durable
        except BaseException:
            if fd >= 0:
                os.close(fd)
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def _fsync_parent_dir(self) -> None:
        try:
            dir_fd = os.open(str(self._path.parent), os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(dir_fd)
        except OSError:
            # Some filesystems (and Windows) don't support directory fsync.
            pass
        finally:
            os.close(dir_fd)

    def _ensure_file(self) -> None:
        parent = self._path.parent
        parent.mkdir(parents=True, exist_ok=True)
        # mkdir honours the process umask (often 0755 → world-readable). Secrets
        # live here, so tighten the directory to 0700 — other local users must
        # not be able to list it or plant a symlink for us to follow.
        try:
            if stat.S_IMODE(parent.stat().st_mode) != 0o700:
                os.chmod(parent, 0o700)
        except OSError as exc:
            raise SecretStoreError(
                f"Secret directory {parent} could not be permission-locked to 0700"
            ) from exc
        if not self._path.exists():
            # Use O_CREAT|O_WRONLY|O_EXCL|O_NOFOLLOW with mode 0o600 to create the
            # file atomically: the permission bits are set by the kernel on the
            # same syscall that creates the inode (no write-then-chmod race), and
            # O_NOFOLLOW refuses to follow a pre-planted symlink at the path.
            try:
                fd = os.open(
                    str(self._path),
                    os.O_CREAT | os.O_WRONLY | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
                try:
                    os.write(fd, b"{}")
                finally:
                    os.close(fd)
            except FileExistsError:
                # Another coroutine raced us and already created the file.
                # Fall through to the permission check below.
                pass
        mode = stat.S_IMODE(self._path.stat().st_mode)
        expected = stat.S_IRUSR | stat.S_IWUSR
        if mode != expected:
            # Self-heal instead of crashing. The file is user-owned and local,
            # so tightening its mode back to 0600 is always safe — drift to a
            # looser mode happens via backup/restore (tar/zip drop 0600),
            # editor rewrites under the default umask, or sync tools. Crashing
            # server startup over recoverable permission drift is the wrong call
            # (BUG-083). Only an *un-healable* chmod failure is fatal.
            logger.warning(
                "Secret file %s had mode %#o, expected 0600; tightening permissions.",
                self._path,
                mode,
            )
            os.chmod(self._path, expected)


def create_secret_store(
    dev_mode: bool | None = None,
) -> tuple[SecretStore, SecretStorageMode]:
    """Create the best prompt-free secret store for this runtime.

    Returns a ``(store, mode)`` pair so callers can surface the storage mode to
    the user without probing the store again.  ``mode`` is:
    - ``"keychain"``  — secrets held in the OS credential store (Windows
                        Credential Manager / Linux Secret Service); encrypted at
                        rest by the OS, no password prompt.
    - ``"plaintext"`` — secrets in a permission-locked JSON file at
                        ``~/.finrobot/.secrets``; the caller must warn the user.

    Platform policy:
    - **macOS**: default to the file. The keychain binds each item's access ACL
      to the calling app's code-signing Designated Requirement; an unsigned or
      ad-hoc-signed app (every dev rebuild, every unsigned release) fails to
      match, so macOS re-prompts *per keychain item, every launch* — even after
      "Always Allow". Until the app ships a stable Developer ID signature there
      is no prompt-free keychain, so we don't use it. A signed build opts back
      in with ``FINROBOT_USE_KEYCHAIN=1``.
    - **Windows / Linux**: use the OS credential store (Credential Manager via
      DPAPI / Secret Service). These are silent and need no code-signing
      certificate; fall back to the file if the backend is unavailable.
    - **dev mode** (``FINROBOT_DEV_MODE=1``): always the file, every platform.
    """
    use_dev = dev_mode
    if use_dev is None:
        use_dev = os.environ.get("FINROBOT_DEV_MODE") == "1"
    if use_dev:
        logger.info("Using FileSecretStore (dev mode)")
        return FileSecretStore(), "plaintext"
    if sys.platform == "darwin" and os.environ.get("FINROBOT_USE_KEYCHAIN") != "1":
        logger.info(
            "Using FileSecretStore (macOS without a stable code signature — "
            "avoids the per-item keychain prompt storm). Set "
            "FINROBOT_USE_KEYCHAIN=1 on a Developer ID-signed build to use the "
            "keychain instead."
        )
        return FileSecretStore(), "plaintext"
    try:
        store = KeychainSecretStore()
        logger.info("Using KeychainSecretStore (OS credential store)")
        return store, "keychain"
    except RuntimeError as exc:
        logger.warning(
            "OS credential store unavailable (%s), falling back to FileSecretStore. "
            "Secrets will be stored as a permission-locked local file.",
            exc,
        )
        return FileSecretStore(), "plaintext"
