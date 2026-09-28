"""Read-side helpers for session transcripts.

Scans ``~/.finrobot/sessions/*.jsonl`` files and returns typed
summaries or full event lists for replay / cmd+K search.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from finrobot.audit.transcript import _safe_session_path

logger = logging.getLogger(__name__)

# Retention cap for on-disk chat transcripts. Sessions are append-only JSONL
# files that otherwise accumulate forever; the writer prunes the oldest files
# past this cap on every session start (same constant-on-module precedent as
# ``run_store.RUN_EVENT_RETENTION_DAYS``). 500 sessions at typical transcript
# size keeps months of history while bounding both disk and the list scan.
SESSION_RETENTION_MAX = 500


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
    ticker: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "created_at": self.created_at,
            "last_active_at": self.last_active_at,
            "turn_count": self.turn_count,
            "model": self.model,
            "user_id": self.user_id,
            "ticker": self.ticker,
        }


def _session_path(session_id: str, base_dir: Path | None = None) -> Path:
    # Defense-in-depth (BUG-089): the read side also refuses any session_id
    # whose resolved path escapes the sessions dir, so a traversal stem can
    # never read attacker-chosen files. Raises ValueError on violation.
    return _safe_session_path(base_dir or _default_dir(), session_id)


def list_sessions(
    user_id: str | None = None,
    ticker: str | None = None,
    base_dir: Path | None = None,
    limit: int | None = None,
) -> list[SessionSummary]:
    """Scan disk and return session summaries sorted newest-first.

    Candidate files are visited in mtime-descending order so a ``limit`` stops
    parsing as soon as the page is full — for an append-only JSONL a file's
    mtime is the write time of its last event, i.e. the same order as
    ``last_active_at``, so the page is the true newest-N without summarising
    every transcript on disk on every list call.

    Args:
        user_id: If given, only return sessions that match this user_id.
        ticker: If given, only return sessions tagged with this ticker
            (case-insensitive).
        base_dir: Override the default session directory.
        limit: If given, return at most this many (filtered) summaries.
            ``None`` keeps the full-scan behaviour. Must be >= 1.

    Returns:
        List of ``SessionSummary`` sorted by ``last_active_at`` descending.
    """
    if limit is not None and limit < 1:
        raise ValueError(f"limit must be >= 1, got {limit}")
    base = base_dir or _default_dir()
    if not base.exists():
        return []
    ticker_norm = ticker.upper() if ticker else None
    candidates: list[tuple[float, Path]] = []
    for path in base.glob("*.jsonl"):
        try:
            candidates.append((path.stat().st_mtime, path))
        except OSError as exc:
            logger.warning("Skipping unstatable session file %s: %s", path, exc)
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    summaries: list[SessionSummary] = []
    for _, path in candidates:
        try:
            summary = _summarize_session_file(path)
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            logger.warning("Skipping unreadable session file %s: %s", path, exc)
            continue
        if summary is None:
            continue
        if user_id is not None and summary.user_id != user_id:
            continue
        if ticker_norm is not None and (summary.ticker or "").upper() != ticker_norm:
            continue
        summaries.append(summary)
        if limit is not None and len(summaries) >= limit:
            break
    summaries.sort(key=lambda s: s.last_active_at, reverse=True)
    return summaries


def prune_sessions(
    max_sessions: int = SESSION_RETENTION_MAX,
    base_dir: Path | None = None,
) -> int:
    """Delete the oldest transcript files beyond the ``max_sessions`` cap.

    Retention policy for the otherwise-unbounded sessions dir: keep the
    ``max_sessions`` most recently written files (mtime order — the last-event
    write time for append-only JSONL) and unlink the rest. Called by the write
    side on every session start, so the cap holds without a scheduler. Unlink
    failures are logged and skipped — pruning must never break a chat turn.

    Returns:
        Number of files deleted.
    """
    if max_sessions < 1:
        raise ValueError(f"max_sessions must be >= 1, got {max_sessions}")
    base = base_dir or _default_dir()
    if not base.exists():
        return 0
    files: list[tuple[float, Path]] = []
    for path in base.glob("*.jsonl"):
        try:
            files.append((path.stat().st_mtime, path))
        except OSError:
            continue
    if len(files) <= max_sessions:
        return 0
    files.sort(key=lambda pair: pair[0], reverse=True)
    deleted = 0
    for _, path in files[max_sessions:]:
        try:
            path.unlink()
            deleted += 1
        except OSError as exc:
            logger.warning("Failed to prune session file %s: %s", path, exc)
    if deleted:
        logger.info("Pruned %d chat transcript(s) past the %d-session cap", deleted, max_sessions)
    return deleted


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
    ticker: str | None = None

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
                start_ticker = data.get("ticker")
                if start_ticker:
                    ticker = str(start_ticker)
            elif event_type == "context":
                # ContextBar bundle: pick up the ticker if session_start didn't
                # carry one (e.g. ticker selected mid-session).
                if ticker is None:
                    bundle = data.get("context_bundle")
                    if isinstance(bundle, dict):
                        bundle_ticker = bundle.get("ticker")
                        if bundle_ticker:
                            ticker = str(bundle_ticker)
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
        ticker=ticker,
    )


def delete_session(session_id: str, base_dir: Path | None = None) -> bool:
    """Delete a session's ``.jsonl`` file from disk.

    Uses the same traversal-safe path resolution as the read side
    (:func:`_session_path` → :func:`_safe_session_path`), so a malicious stem
    (``../`` / absolute / separator) whose resolved path escapes the sessions
    dir is rejected before any unlink — a delete can never touch an
    attacker-chosen file outside the sessions dir (BUG-089).

    Args:
        session_id: The session identifier (stem of the ``.jsonl`` filename).
        base_dir: Override the default session directory.

    Returns:
        ``True`` if the file existed and was deleted; ``False`` if it did not
        exist, if ``session_id`` is unsafe (traversal stem), or if the unlink
        failed with an ``OSError`` — mirroring the read side, which logs and
        degrades rather than 500-ing the caller.
    """
    try:
        path = _session_path(session_id, base_dir)
    except ValueError:
        logger.warning("Rejected unsafe session_id for delete: %r", session_id)
        return False
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.warning("Failed to delete session file %s: %s", path, exc)
        return False
    return True


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
        List of event dicts in chronological order.  Empty list if file not
        found or if ``session_id`` is unsafe (traversal stem — BUG-089), so the
        route surfaces a clean 404 rather than reading an attacker-chosen file.
    """
    try:
        path = _session_path(session_id, base_dir)
    except ValueError:
        logger.warning("Rejected unsafe session_id for transcript read: %r", session_id)
        return []
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
