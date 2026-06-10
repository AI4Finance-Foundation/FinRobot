"""Integration tests for the chat-session read API (BUG-20260602-045).

The ``/chat`` endpoint side-logs transcripts to per-session JSONL files; these
routes expose them so the desktop AI panel can list + reopen past sessions.

We write transcripts through the real ``TranscriptWriter`` (redirected to a
temp dir) and read them back through the routes, so the test exercises the
actual write→persist→read round-trip rather than a hand-rolled JSONL fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from finrobot.audit.transcript import TranscriptWriter
from finrobot.routes.chat_sessions import router as chat_sessions_router


@pytest.fixture()
def _sessions_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect both the writer and the reader to a temp sessions dir."""
    sess_dir = tmp_path / "sessions"
    monkeypatch.setattr("finrobot.audit.transcript._DEFAULT_DIR", sess_dir)
    monkeypatch.setattr("finrobot.audit.persistence._DEFAULT_DIR", sess_dir)
    return sess_dir


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(chat_sessions_router)
    return TestClient(app)


async def _seed_session(
    session_id: str,
    *,
    model: str,
    ticker: str | None,
    locale: str | None,
    user_text: str,
) -> None:
    writer = TranscriptWriter(session_id)
    await writer.log_session_start(user_id="local", model=model, ticker=ticker, locale=locale)
    if ticker or locale:
        await writer.log_context({"ticker": ticker, "locale": locale, "route": f"/stocks/{ticker}"})
    await writer.log_user_message(user_text)
    await writer.log_assistant_text("answer body")


async def test_list_sessions_returns_summaries_newest_first(
    _sessions_dir: Path, client: TestClient
) -> None:
    await _seed_session("sess-aapl", model="m1", ticker="AAPL", locale="en", user_text="AAPL DCF?")
    await _seed_session("sess-nvda", model="m2", ticker="NVDA", locale="zh", user_text="英伟达估值")

    resp = client.get("/api/chat/sessions")
    assert resp.status_code == 200
    body = resp.json()
    sessions = body["sessions"]
    assert len(sessions) == 2
    ids = {s["session_id"] for s in sessions}
    assert ids == {"sess-aapl", "sess-nvda"}

    by_id = {s["session_id"]: s for s in sessions}
    assert by_id["sess-aapl"]["ticker"] == "AAPL"
    assert by_id["sess-aapl"]["title"] == "AAPL DCF?"
    assert by_id["sess-aapl"]["turn_count"] == 1
    assert by_id["sess-nvda"]["model"] == "m2"


async def test_list_sessions_limit_caps_page_and_rejects_out_of_range(
    _sessions_dir: Path, client: TestClient
) -> None:
    """``?limit=`` bounds the page (newest first); 0 / >500 are 422s, matching
    the list_runs cap style — the endpoint must never parse the whole dir for
    one dropdown render."""
    import os

    for i, sid in enumerate(["sess-old", "sess-mid", "sess-new"]):
        await _seed_session(sid, model="m", ticker=None, locale=None, user_text=f"q{i}")
        os.utime(_sessions_dir / f"{sid}.jsonl", (1_700_000_000 + i, 1_700_000_000 + i))

    resp = client.get("/api/chat/sessions", params={"limit": 1})
    assert resp.status_code == 200
    sessions = resp.json()["sessions"]
    assert [s["session_id"] for s in sessions] == ["sess-new"]

    assert client.get("/api/chat/sessions", params={"limit": 0}).status_code == 422
    assert client.get("/api/chat/sessions", params={"limit": 501}).status_code == 422


async def test_list_sessions_ticker_filter(_sessions_dir: Path, client: TestClient) -> None:
    await _seed_session("sess-aapl", model="m1", ticker="AAPL", locale="en", user_text="q1")
    await _seed_session("sess-nvda", model="m2", ticker="NVDA", locale="en", user_text="q2")

    # Case-insensitive filter.
    resp = client.get("/api/chat/sessions", params={"ticker": "aapl"})
    assert resp.status_code == 200
    sessions = resp.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "sess-aapl"


async def test_list_sessions_empty_when_no_dir(_sessions_dir: Path, client: TestClient) -> None:
    # No transcripts written → empty list (dir may not even exist yet).
    resp = client.get("/api/chat/sessions")
    assert resp.status_code == 200
    assert resp.json()["sessions"] == []


async def test_load_session_transcript(_sessions_dir: Path, client: TestClient) -> None:
    await _seed_session("sess-load", model="m1", ticker="AAPL", locale="zh", user_text="问题")

    resp = client.get("/api/chat/sessions/sess-load")
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == "sess-load"
    events = body["events"]
    event_types = [e["event"] for e in events]
    assert "session_start" in event_types
    assert "context" in event_types
    assert "user_msg" in event_types
    assert "assistant_text" in event_types

    start = next(e for e in events if e["event"] == "session_start")
    assert start["data"]["ticker"] == "AAPL"
    assert start["data"]["locale"] == "zh"

    ctx = next(e for e in events if e["event"] == "context")
    assert ctx["data"]["context_bundle"]["ticker"] == "AAPL"


def test_load_missing_session_404(_sessions_dir: Path, client: TestClient) -> None:
    resp = client.get("/api/chat/sessions/does-not-exist")
    assert resp.status_code == 404


async def test_delete_session_removes_file_and_second_delete_404(
    _sessions_dir: Path, client: TestClient
) -> None:
    await _seed_session("sess-del", model="m1", ticker="AAPL", locale="en", user_text="delete me")
    session_file = _sessions_dir / "sess-del.jsonl"
    assert session_file.exists()

    resp = client.delete("/api/chat/sessions/sess-del")
    assert resp.status_code == 200
    assert resp.json() == {"status": "deleted", "session_id": "sess-del"}
    assert not session_file.exists()

    # Idempotent: a second delete of the now-gone session is a clean 404.
    resp_again = client.delete("/api/chat/sessions/sess-del")
    assert resp_again.status_code == 404


def test_delete_missing_session_404(_sessions_dir: Path, client: TestClient) -> None:
    resp = client.delete("/api/chat/sessions/never-existed")
    assert resp.status_code == 404


def test_delete_rejects_path_traversal_id(_sessions_dir: Path, client: TestClient) -> None:
    # A traversal stem is gated at the edge by is_valid_session_id → 404, and
    # must never unlink a file outside the sessions dir (BUG-089). Plant a file
    # one level up that a naive join would target, and prove it survives.
    outside = _sessions_dir.parent / "victim.jsonl"
    outside.write_text("keep me", encoding="utf-8")

    # URL-encoded so the path segment reaches the handler as the raw stem
    # rather than being collapsed by the HTTP client's path normalisation.
    resp = client.delete("/api/chat/sessions/..%2Fvictim")
    assert resp.status_code == 404
    assert outside.exists()
    assert outside.read_text(encoding="utf-8") == "keep me"
