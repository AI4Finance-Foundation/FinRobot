"""Per-session JSONL transcript for audit and replay.

Each FinRobot conversation is appended to:
  ~/.finrobot/sessions/<session_id>.jsonl

Append-only, mode 0o600 on first write. One JSON event per line.

Event schema:
    {
        "timestamp": ISO-8601 UTC,
        "session_id": str,
        "event": "user_msg" | "assistant_text" | "tool_call" | "tool_result"
                | "error" | "session_start" | "session_end",
        "data": dict   # event-specific payload
    }
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Defense-in-depth secret scrubber. Even though providers no longer interpolate
# raw httpx exceptions (whose str() leaks ``?apikey=<key>``), the transcript is
# the last line before secrets become permanent on disk, so it scrubs every
# event payload itself. Patterns are anchored on the *value* so the redacted
# string still shows which credential was present.
#   1. query-string keys:   ...?apikey=SECRET   ...&api_key=SECRET
#   2. header-style keys:    "X-API-Key": "SECRET"  /  X-Finnhub-Token: SECRET
_QUERY_KEY_RE = re.compile(r"(?i)(api[_-]?key=)[^&\s\"']+")
_HEADER_KEY_RE = re.compile(r"(?i)(x-(?:api-key|finnhub-token)['\"]?\s*[:=]\s*['\"]?)[^&\s,}\"']+")


def _scrub_secrets(text: str) -> str:
    """Redact API-key-shaped substrings from a single string."""
    text = _QUERY_KEY_RE.sub(r"\1[REDACTED]", text)
    return _HEADER_KEY_RE.sub(r"\1[REDACTED]", text)


def _scrub_data(value: Any) -> Any:
    """Recursively walk ``str`` leaves of an event payload and scrub secrets.

    Returns a scrubbed copy; containers are rebuilt so the original payload is
    not mutated. Cheap: only ``str`` leaves are touched (regex with no match is
    near-free), so large non-string blobs pass through untouched.
    """
    if isinstance(value, str):
        return _scrub_secrets(value)
    if isinstance(value, dict):
        return {k: _scrub_data(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_scrub_data(v) for v in value)
    return value


# Tests monkey-patch this attribute to redirect writes. Production leaves
# it None so :func:`_default_dir` falls through to the unified location
# resolved at call time (so ``monkeypatch.setenv('HOME', ...)`` + paths
# reload also works).
_DEFAULT_DIR: Path | None = None


def _default_dir() -> Path:
    if _DEFAULT_DIR is not None:
        return _DEFAULT_DIR
    from finrobot.paths import SESSIONS_DIR

    return SESSIONS_DIR


class TranscriptWriter:
    """One writer per session.  Concurrent-safe via asyncio.Lock.

    The file is opened in append mode on every write — no persistent file
    handle held — so there is no explicit close/flush step needed.  The
    ``close()`` method exists for symmetry and future use.

    Args:
        session_id: Identifier for the chat session (used as filename stem).
        base_dir: Override the default session directory.
    """

    def __init__(self, session_id: str, base_dir: Path | None = None) -> None:
        self.session_id = session_id
        self._base_dir = base_dir or _default_dir()
        self._path = self._base_dir / f"{session_id}.jsonl"
        self._lock = asyncio.Lock()
        self._first_write_done = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_parent_dir(self) -> None:
        self._base_dir.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            self._base_dir.chmod(0o700)

    def _build_line(self, event: str, data: dict[str, Any]) -> str:
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "session_id": self.session_id,
            "event": event,
            "data": data,
        }
        return json.dumps(record, ensure_ascii=False)

    async def _write_event(self, event: str, data: dict[str, Any]) -> None:
        """Append one JSONL event line.  Never raises — errors are logged.

        Every payload is run through :func:`_scrub_data` first so an API key
        that slipped into any nested string (e.g. a provider warning nested
        under ``data['result']``) is redacted before it is written to disk.
        """
        try:
            self._ensure_parent_dir()
            scrubbed: dict[str, Any] = _scrub_data(data)
            line = self._build_line(event, scrubbed)
            async with self._lock:
                with open(self._path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
                if not self._first_write_done:
                    with contextlib.suppress(OSError):
                        self._path.chmod(0o600)
                    self._first_write_done = True
        except OSError as exc:
            logger.exception(
                "TranscriptWriter._write_event OSError (session=%s): %s", self.session_id, exc
            )

    # ------------------------------------------------------------------
    # Public logging API
    # ------------------------------------------------------------------

    async def log_session_start(
        self,
        user_id: str,
        model: str,
        ticker: str | None = None,
        locale: str | None = None,
    ) -> None:
        """Emit a ``session_start`` event with user and model metadata.

        ``ticker`` and ``locale`` are optional audit hints recorded so the
        history UI can filter by symbol and so the language policy of a session
        is reconstructable (BUG-20260602-045/048).
        """
        data: dict[str, Any] = {"user_id": user_id, "model": model}
        if ticker:
            data["ticker"] = ticker
        if locale:
            data["locale"] = locale
        await self._write_event("session_start", data)

    async def log_context(self, context: dict[str, Any]) -> None:
        """Emit a ``context`` event recording the ContextBar bundle sent with a
        turn (current route, artifact id, pinned items, selection, locale).

        Keeps the audit trail honest: the transcript shows exactly what extra
        context the model was given for a turn (BUG-20260602-038)."""
        await self._write_event("context", {"context_bundle": context})

    async def log_user_message(self, text: str) -> None:
        """Emit a ``user_msg`` event for the latest user turn."""
        await self._write_event("user_msg", {"text": text})

    async def log_assistant_text(self, text: str) -> None:
        """Emit an ``assistant_text`` event for a completed assistant text part."""
        await self._write_event("assistant_text", {"text": text})

    async def log_tool_call(
        self,
        tool_name: str,
        tool_use_id: str,
        args: dict[str, Any],
    ) -> None:
        """Emit a ``tool_call`` event when the LLM requests a tool invocation."""
        await self._write_event(
            "tool_call",
            {"tool_name": tool_name, "tool_use_id": tool_use_id, "args": args},
        )

    async def log_tool_result(
        self,
        tool_use_id: str,
        tool_name: str,
        result: Any,
        is_error: bool,
        artifact_id: str | None = None,
    ) -> None:
        """Emit a ``tool_result`` event after a tool returns.

        Pydantic models are serialised via ``model_dump()``.  The optional
        ``artifact_id`` links the result to an ArtifactStore entry.
        """
        if hasattr(result, "model_dump"):
            payload: Any = result.model_dump()
        else:
            payload = result
        await self._write_event(
            "tool_result",
            {
                "tool_use_id": tool_use_id,
                "tool_name": tool_name,
                "result": payload,
                "is_error": is_error,
                "artifact_id": artifact_id,
            },
        )

    async def log_error(
        self,
        exception_class: str,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Emit an ``error`` event for exceptions encountered during a run."""
        await self._write_event(
            "error",
            {
                "exception_class": exception_class,
                "message": message,
                "context": context or {},
            },
        )

    async def log_session_end(self) -> None:
        """Emit a ``session_end`` event.  Should be called on server shutdown."""
        await self._write_event("session_end", {})

    async def close(self) -> None:
        """No-op: no persistent file handle is held.  Exists for symmetry."""
        return
