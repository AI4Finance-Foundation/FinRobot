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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


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
        """Append one JSONL event line.  Never raises — errors are logged."""
        try:
            self._ensure_parent_dir()
            line = self._build_line(event, data)
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

    async def log_session_start(self, user_id: str, model: str) -> None:
        """Emit a ``session_start`` event with user and model metadata."""
        await self._write_event("session_start", {"user_id": user_id, "model": model})

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
