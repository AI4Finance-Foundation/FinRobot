"""Read API for chat session transcripts (history / replay).

The ``/chat`` endpoint side-logs every conversation to a per-session JSONL file
(see ``finrobot.audit.transcript``). The write side has always existed but had
no reader, so past sessions were invisible to the desktop UI
(BUG-20260602-045). These routes expose the existing
``finrobot.audit.persistence`` helpers so the AI panel can list and reopen
prior sessions.

Endpoints:
    GET    /api/chat/sessions          — list session summaries (optional ?ticker=)
    GET    /api/chat/sessions/{id}     — load a session's full transcript
    DELETE /api/chat/sessions/{id}     — permanently delete a session's transcript
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from finrobot.audit.persistence import (
    delete_session,
    list_sessions,
    load_session_transcript,
)
from finrobot.audit.transcript import is_valid_session_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat-sessions"])


class SessionSummaryModel(BaseModel):
    """Lightweight summary of a chat session derived from its JSONL file."""

    session_id: str
    title: str
    created_at: str
    last_active_at: str
    turn_count: int
    model: str
    user_id: str
    ticker: str | None = None


class SessionListResponse(BaseModel):
    sessions: list[SessionSummaryModel]


class TranscriptEvent(BaseModel):
    """One JSONL transcript event. ``data`` is event-specific."""

    timestamp: str
    session_id: str
    event: str
    data: dict[str, object]


class SessionTranscriptResponse(BaseModel):
    session_id: str
    events: list[TranscriptEvent]


@router.get("/sessions", response_model=SessionListResponse)
def get_chat_sessions(
    ticker: str | None = Query(
        default=None,
        description="Filter to sessions focused on this ticker (case-insensitive).",
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
        description="Maximum number of sessions to return (newest first).",
    ),
) -> SessionListResponse:
    """List past chat sessions, newest-first, capped at ``limit``.

    Reads the on-disk JSONL transcripts. Unreadable/corrupt files are skipped
    by the persistence layer rather than 500-ing the whole list. The cap keeps
    the endpoint from parsing every transcript on disk per call (the
    persistence layer stops scanning once the page is full).
    """
    summaries = list_sessions(ticker=ticker, limit=limit)
    return SessionListResponse(
        sessions=[
            SessionSummaryModel(
                session_id=s.session_id,
                title=s.title,
                created_at=s.created_at,
                last_active_at=s.last_active_at,
                turn_count=s.turn_count,
                model=s.model,
                user_id=s.user_id,
                ticker=s.ticker,
            )
            for s in summaries
        ]
    )


@router.get("/sessions/{session_id}", response_model=SessionTranscriptResponse)
def get_chat_session_transcript(session_id: str) -> SessionTranscriptResponse:
    """Load the full transcript for one session.

    404 when the session has no transcript on disk (never started, or evicted).
    """
    events = load_session_transcript(session_id)
    if not events:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    typed: list[TranscriptEvent] = []
    for evt in events:
        # Defensive: skip events missing the core envelope keys rather than
        # 500-ing. A transcript is append-only JSONL written by the live chat
        # path, but a partially-flushed line should not break replay.
        if not isinstance(evt, dict):
            continue
        raw_data = evt.get("data")
        data: dict[str, object] = raw_data if isinstance(raw_data, dict) else {}
        typed.append(
            TranscriptEvent(
                timestamp=str(evt.get("timestamp", "")),
                session_id=str(evt.get("session_id", session_id)),
                event=str(evt.get("event", "")),
                data=data,
            )
        )
    return SessionTranscriptResponse(session_id=session_id, events=typed)


@router.delete("/sessions/{session_id}")
def delete_chat_session(session_id: str) -> dict[str, str]:
    """Permanently delete one session's on-disk transcript.

    The ``session_id`` becomes the stem of ``<sessions>/<session_id>.jsonl``, so
    a traversal stem (``../..``) is gated at the edge with
    :func:`is_valid_session_id` (reject → 404, never a 500 or an unlink outside
    the sessions dir — BUG-089). ``delete_session`` re-checks containment via
    ``resolve()`` as defense-in-depth.

    Returns:
        ``{"status": "deleted", "session_id": session_id}`` on success.

    Raises:
        404: If the ``session_id`` is malformed, or no transcript exists on disk
            (never started, already deleted, or evicted).
    """
    if not is_valid_session_id(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    if not delete_session(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return {"status": "deleted", "session_id": session_id}
