"""Integration test: /chat endpoint writes to JSONL transcript.

We only test the user_msg write because the rest of the stream (assistant_text,
tool_call, tool_result) requires a live LLM call.  The key assertion is that
``session_start`` and ``user_msg`` events appear in the JSONL file before any
model interaction happens.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture()
def _reset_transcript_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect TranscriptWriter to a temp directory for isolation."""
    sess_dir = tmp_path / "sessions"
    monkeypatch.setattr(
        "finagent.audit.transcript._DEFAULT_DIR",
        sess_dir,
    )
    return sess_dir


async def test_chat_writes_session_start_and_user_msg(
    tmp_path: Path, _reset_transcript_dir: Path
) -> None:
    """POST /chat should write session_start + user_msg to JSONL before streaming."""
    from pydantic_ai.models.test import TestModel

    from finagent.config import get_settings
    from finagent.engine.deps import FinAgentDeps
    from finagent.engine.orchestrator import create_lead_agent
    from finagent.server import app

    settings = get_settings(model_name="test")
    agent = create_lead_agent(settings)

    # Pre-populate app state to bypass lifespan
    app.state.agent = agent
    app.state.deps = FinAgentDeps(
        data_layer=None,  # type: ignore[arg-type]
        settings=settings,
    )
    app.state.transcript_writers = {}
    app.state.artifact_store = None

    session_id = "integration-test-session"
    payload = {
        "id": session_id,
        "model": "test-model",
        "messages": [
            {"role": "user", "parts": [{"type": "text", "text": "What is AAPL?", "state": "done"}]},
        ],
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # The response may fail (no real LLM) — we only care about transcript writes.
        try:
            resp = await c.post("/chat", json=payload)
        except Exception:
            pass  # LLM call failure is expected in unit test context

    sess_dir = _reset_transcript_dir
    path = sess_dir / f"{session_id}.jsonl"

    # File must exist with at least session_start + user_msg
    assert path.exists(), f"Transcript file not found at {path}"
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    events = [json.loads(ln) for ln in lines]

    event_types = [e["event"] for e in events]
    assert "session_start" in event_types, f"Missing session_start. Got: {event_types}"
    assert "user_msg" in event_types, f"Missing user_msg. Got: {event_types}"

    user_evt = next(e for e in events if e["event"] == "user_msg")
    # The user message content from a Vercel AI SDK body is extracted from messages[-1].content
    # For parts-based messages the content key may be absent; the test verifies the event exists.
    assert user_evt["session_id"] == session_id


async def test_chat_missing_session_id_uses_default(
    tmp_path: Path, _reset_transcript_dir: Path
) -> None:
    """When no ``id`` field in body, session_id should fall back to 'default'."""
    from finagent.config import get_settings
    from finagent.engine.deps import FinAgentDeps
    from finagent.engine.orchestrator import create_lead_agent
    from finagent.server import app

    settings = get_settings(model_name="test")
    agent = create_lead_agent(settings)

    app.state.agent = agent
    app.state.deps = FinAgentDeps(data_layer=None, settings=settings)  # type: ignore[arg-type]
    app.state.transcript_writers = {}
    app.state.artifact_store = None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        try:
            await c.post("/chat", json={"messages": []})
        except Exception:
            pass

    sess_dir = _reset_transcript_dir
    # 'default' session file should be created
    assert (sess_dir / "default.jsonl").exists()
