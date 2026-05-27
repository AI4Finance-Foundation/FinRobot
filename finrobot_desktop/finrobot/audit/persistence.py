"""Read-side helpers for session transcripts.

Scans ``~/.finrobot/sessions/*.jsonl`` files and returns typed
summaries or full event lists for replay / cmd+K search.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# Tests monkey-patch this attribute to redirect reads to a tmp dir.
# Production leaves it None so :func:`_default_dir` resolves to the
# unified sessions location at call time.
_DEFAULT_DIR: Path | None = None


def _default_dir() -> Path:
    if _DEFAULT_DIR is not None:
        return _DEFAULT_DIR
    from finrobot.paths import SESSIONS_DIR

    return SESSIONS_DIR


@dataclass
class SessionSummary:
    """Lightweight summary derived from a single ``.jsonl`` session file."""

    session_id: str
    title: str
    created_at: str
    last_active_at: str
    turn_count: int
    model: str
    user_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "created_at": self.created_at,
            "last_active_at": self.last_active_at,
            "turn_count": self.turn_count,
            "model": self.model,
            "user_id": self.user_id,
        }


def _session_path(session_id: str, base_dir: Path | None = None) -> Path:
    return (base_dir or _default_dir()) / f"{session_id}.jsonl"


def list_sessions(
    user_id: str | None = None,
    base_dir: Path | None = None,
) -> list[SessionSummary]:
    """Scan disk and return session summaries sorted newest-first.

    Args:
        user_id: If given, only return sessions that match this user_id.
        base_dir: Override the default session directory.

    Returns:
        List of ``SessionSummary`` sorted by ``last_active_at`` descending.
    """
    base = base_dir or _default_dir()
    if not base.exists():
        return []
    summaries: list[SessionSummary] = []
    for path in sorted(base.glob("*.jsonl")):
        try:
            summary = _summarize_session_file(path)
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            logger.warning("Skipping unreadable session file %s: %s", path, exc)
            continue
        if summary is None:
            continue
        if user_id is not None and summary.user_id != user_id:
            continue
        summaries.append(summary)
    summaries.sort(key=lambda s: s.last_active_at, reverse=True)
    return summaries


def _summarize_session_file(path: Path) -> SessionSummary | None:
    """Parse a ``.jsonl`` file into a ``SessionSummary``.

    Returns ``None`` if the file has no ``session_start`` event (incomplete
    or corrupt file that should be skipped without raising).
    """
    session_id = path.stem
    title = ""
    created_at = ""
    last_active_at = ""
    turn_count = 0
    model = "unknown"
    user_id = "local"

    with open(path, encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed JSONL line in %s", path)
                continue
            event_type = evt.get("event")
            ts: str = evt.get("timestamp", "")
            data: dict[str, object] = evt.get("data", {})
            last_active_at = ts
            if event_type == "session_start":
                created_at = ts
                model = str(data.get("model", model))
                user_id = str(data.get("user_id", user_id))
            elif event_type == "user_msg":
                turn_count += 1
                if not title:
                    title = str(data.get("text") or "")[:60]

    if not created_at:
        return None
    return SessionSummary(
        session_id=session_id,
        title=title or "(无标题)",
        created_at=created_at,
        last_active_at=last_active_at,
        turn_count=turn_count,
        model=model,
        user_id=user_id,
    )


def load_session_transcript(
    session_id: str,
    base_dir: Path | None = None,
) -> list[dict[str, object]]:
    """Load all events from a session's ``.jsonl`` file.

    Malformed lines are skipped with a debug log; they never raise.

    Args:
        session_id: The session identifier (stem of the ``.jsonl`` filename).
        base_dir: Override the default session directory.

    Returns:
        List of event dicts in chronological order.  Empty list if file not found.
    """
    path = _session_path(session_id, base_dir)
    if not path.exists():
        return []
    events: list[dict[str, object]] = []
    with open(path, encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                logger.debug("Skipping malformed JSONL line in session %s", session_id)
    return events
