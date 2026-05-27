"""Tests for finrobot.audit.transcript and finrobot.audit.persistence."""

from __future__ import annotations

import asyncio
import json
import stat
import sys
from pathlib import Path

import pytest

from finrobot.audit.persistence import (
    _summarize_session_file,
    list_sessions,
    load_session_transcript,
)
from finrobot.audit.transcript import TranscriptWriter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_session_dir(tmp_path: Path) -> Path:
    return tmp_path / "sessions"


# ---------------------------------------------------------------------------
# TranscriptWriter: basic write → read round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_writer_creates_file_and_roundtrip(tmp_session_dir: Path) -> None:
    writer = TranscriptWriter("sess-001", base_dir=tmp_session_dir)
    await writer.log_session_start(user_id="alice", model="deepseek")
    await writer.log_user_message("hello world")
    await writer.log_assistant_text("hi there")
    await writer.log_session_end()

    path = tmp_session_dir / "sess-001.jsonl"
    assert path.exists()

    events = load_session_transcript("sess-001", base_dir=tmp_session_dir)
    assert len(events) == 4

    assert events[0]["event"] == "session_start"
    assert events[0]["data"]["user_id"] == "alice"
    assert events[0]["data"]["model"] == "deepseek"

    assert events[1]["event"] == "user_msg"
    assert events[1]["data"]["text"] == "hello world"

    assert events[2]["event"] == "assistant_text"
    assert events[2]["data"]["text"] == "hi there"

    assert events[3]["event"] == "session_end"


@pytest.mark.asyncio
async def test_writer_tool_call_and_result(tmp_session_dir: Path) -> None:
    writer = TranscriptWriter("sess-002", base_dir=tmp_session_dir)
    await writer.log_session_start(user_id="local", model="test")
    await writer.log_tool_call(
        tool_name="run_dcf_valuation",
        tool_use_id="tc-abc",
        args={"ticker": "AAPL"},
    )
    await writer.log_tool_result(
        tool_use_id="tc-abc",
        tool_name="run_dcf_valuation",
        result={"summary": "DCF done", "artifact_id": "art_123"},
        is_error=False,
        artifact_id="art_123",
    )

    events = load_session_transcript("sess-002", base_dir=tmp_session_dir)
    tc = events[1]
    assert tc["event"] == "tool_call"
    assert tc["data"]["tool_name"] == "run_dcf_valuation"
    assert tc["data"]["tool_use_id"] == "tc-abc"
    assert tc["data"]["args"] == {"ticker": "AAPL"}

    tr = events[2]
    assert tr["event"] == "tool_result"
    assert tr["data"]["artifact_id"] == "art_123"
    assert tr["data"]["is_error"] is False


@pytest.mark.asyncio
async def test_writer_error_event(tmp_session_dir: Path) -> None:
    writer = TranscriptWriter("sess-003", base_dir=tmp_session_dir)
    await writer.log_error(
        exception_class="ValueError",
        message="bad input",
        context={"ticker": "NOPE"},
    )
    events = load_session_transcript("sess-003", base_dir=tmp_session_dir)
    assert events[0]["event"] == "error"
    assert events[0]["data"]["exception_class"] == "ValueError"
    assert events[0]["data"]["context"]["ticker"] == "NOPE"


# ---------------------------------------------------------------------------
# Concurrent safety: 100 parallel writes must not corrupt the file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_writes_produce_100_lines(tmp_session_dir: Path) -> None:
    writer = TranscriptWriter("sess-concurrent", base_dir=tmp_session_dir)
    await asyncio.gather(*[writer.log_user_message(f"msg-{i}") for i in range(100)])
    path = tmp_session_dir / "sess-concurrent.jsonl"
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    # All 100 lines must be valid JSON
    assert len(lines) == 100
    for line in lines:
        parsed = json.loads(line)  # raises if corrupt
        assert parsed["event"] == "user_msg"


# ---------------------------------------------------------------------------
# File permission check (skipped on Windows)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions only")
@pytest.mark.asyncio
async def test_file_permission_is_0o600(tmp_session_dir: Path) -> None:
    writer = TranscriptWriter("sess-perm", base_dir=tmp_session_dir)
    await writer.log_session_start(user_id="local", model="test")
    path = tmp_session_dir / "sess-perm.jsonl"
    file_mode = stat.S_IMODE(path.stat().st_mode)
    assert file_mode == 0o600


# ---------------------------------------------------------------------------
# persistence.list_sessions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sessions_sorted_newest_first(tmp_session_dir: Path) -> None:
    for sid, model in [("old-sess", "gpt-4"), ("new-sess", "deepseek")]:
        writer = TranscriptWriter(sid, base_dir=tmp_session_dir)
        await writer.log_session_start(user_id="local", model=model)
        await writer.log_user_message("turn one")

    sessions = list_sessions(base_dir=tmp_session_dir)
    assert len(sessions) >= 2
    # newest should be second writer (later timestamp)
    assert sessions[0].session_id == "new-sess"
    assert sessions[1].session_id == "old-sess"


@pytest.mark.asyncio
async def test_list_sessions_user_id_filter(tmp_session_dir: Path) -> None:
    for uid, sid in [("alice", "alice-sess"), ("bob", "bob-sess")]:
        writer = TranscriptWriter(sid, base_dir=tmp_session_dir)
        await writer.log_session_start(user_id=uid, model="test")
        await writer.log_user_message("hi")

    alice_sessions = list_sessions(user_id="alice", base_dir=tmp_session_dir)
    assert all(s.user_id == "alice" for s in alice_sessions)


@pytest.mark.asyncio
async def test_list_sessions_empty_dir_returns_empty(tmp_session_dir: Path) -> None:
    result = list_sessions(base_dir=tmp_session_dir / "nonexistent")
    assert result == []


# ---------------------------------------------------------------------------
# Corrupt / malformed JSONL handling
# ---------------------------------------------------------------------------


def test_corrupt_jsonl_lines_skipped_with_warning(
    tmp_session_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    tmp_session_dir.mkdir(parents=True, exist_ok=True)
    path = tmp_session_dir / "corrupt-sess.jsonl"
    # Mix valid + invalid lines
    path.write_text(
        '{"timestamp": "2026-01-01T00:00:00+00:00", "session_id": "corrupt-sess", "event": "session_start", "data": {"user_id": "local", "model": "x"}}\n'
        "NOT VALID JSON\n"
        '{"timestamp": "2026-01-01T00:01:00+00:00", "session_id": "corrupt-sess", "event": "user_msg", "data": {"text": "hi"}}\n',
        encoding="utf-8",
    )
    events = load_session_transcript("corrupt-sess", base_dir=tmp_session_dir)
    # Only the two valid lines should be returned
    assert len(events) == 2
    assert events[0]["event"] == "session_start"
    assert events[1]["event"] == "user_msg"


def test_corrupt_summarize_skips_bad_json(
    tmp_session_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    tmp_session_dir.mkdir(parents=True, exist_ok=True)
    path = tmp_session_dir / "bad-json.jsonl"
    path.write_text("{{{{ NOT JSON\n", encoding="utf-8")
    # Session has no session_start → should return None without crashing
    result = _summarize_session_file(path)
    assert result is None


# ---------------------------------------------------------------------------
# Summary fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_title_derived_from_first_user_msg(tmp_session_dir: Path) -> None:
    writer = TranscriptWriter("title-sess", base_dir=tmp_session_dir)
    await writer.log_session_start(user_id="local", model="deepseek")
    await writer.log_user_message("A" * 80)  # longer than 60 chars

    sessions = list_sessions(base_dir=tmp_session_dir)
    assert len(sessions) == 1
    assert len(sessions[0].title) == 60


@pytest.mark.asyncio
async def test_summary_turn_count(tmp_session_dir: Path) -> None:
    writer = TranscriptWriter("turns-sess", base_dir=tmp_session_dir)
    await writer.log_session_start(user_id="local", model="test")
    for i in range(5):
        await writer.log_user_message(f"turn {i}")

    sessions = list_sessions(base_dir=tmp_session_dir)
    assert sessions[0].turn_count == 5
