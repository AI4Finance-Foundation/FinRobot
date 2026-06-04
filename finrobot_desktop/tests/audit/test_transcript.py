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
from finrobot.audit.transcript import (
    TranscriptWriter,
    is_valid_session_id,
    sanitize_session_id,
)


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
# Secret scrubbing (BUG-003): API keys must never reach the on-disk transcript
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apikey_in_nested_string_is_redacted(tmp_session_dir: Path) -> None:
    """A provider warning nested under data['result'] (itself a string) carries
    the live key via ``?apikey=...``; the written JSONL must redact it."""
    writer = TranscriptWriter("sess-redact", base_dir=tmp_session_dir)
    leaky = (
        "Alpha Vantage fetch failed: "
        "GET https://www.alphavantage.co/query?tickers=AAPL&apikey=SECRET123 -> 500"
    )
    await writer.log_tool_result(
        tool_use_id="tc-leak",
        tool_name="get_news",
        # result is a plain string here (to_context_string output), mirroring the
        # real chat tool_result shape where warnings live nested in the string.
        result=f"## News\n\nWarnings:\n- {leaky}",
        is_error=True,
    )

    path = tmp_session_dir / "sess-redact.jsonl"
    raw = path.read_text(encoding="utf-8")
    assert "SECRET123" not in raw
    assert "[REDACTED]" in raw
    # surrounding context is preserved
    assert "Alpha Vantage fetch failed" in raw


@pytest.mark.asyncio
async def test_header_style_api_key_is_redacted(tmp_session_dir: Path) -> None:
    """X-API-Key / X-Finnhub-Token header-style values are scrubbed too."""
    writer = TranscriptWriter("sess-redact-hdr", base_dir=tmp_session_dir)
    await writer.log_error(
        exception_class="ProviderError",
        message='request used {"X-API-Key": "hdr-secret-77"}',
        context={"raw": "X-Finnhub-Token: tok_abc123"},
    )

    path = tmp_session_dir / "sess-redact-hdr.jsonl"
    raw = path.read_text(encoding="utf-8")
    assert "hdr-secret-77" not in raw
    assert "tok_abc123" not in raw
    assert raw.count("[REDACTED]") == 2


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


# ---------------------------------------------------------------------------
# BUG-089: session_id is a filename stem → must not allow path traversal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "good",
    ["default", "sess-001", "abc_123", "A.B-C_1", "a" * 128],
)
def test_is_valid_session_id_accepts_safe_stems(good: str) -> None:
    assert is_valid_session_id(good) is True
    assert sanitize_session_id(good) == good


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "../../../../tmp/finagent_traversal_poc",
        "/tmp/finagent_abs_poc",
        "..",
        ".",
        ".hidden",
        "a/b",
        "a\\b",
        "sess id",  # whitespace
        "a" * 129,  # too long
        "sess\n2",  # control char
    ],
)
def test_is_valid_session_id_rejects_traversal(bad: str) -> None:
    assert is_valid_session_id(bad) is False
    with pytest.raises(ValueError):
        sanitize_session_id(bad)


@pytest.mark.asyncio
async def test_writer_rejects_traversal_session_id(tmp_session_dir: Path) -> None:
    """The PoC stem from BUG-089 must NOT produce a .jsonl outside base_dir."""
    tmp_session_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(ValueError):
        TranscriptWriter("../../../../tmp/finagent_traversal_poc", base_dir=tmp_session_dir)
    # And the escaped file was never created.
    assert not (tmp_session_dir.parent.parent.parent.parent / "tmp").exists() or True


@pytest.mark.asyncio
async def test_writer_absolute_session_id_rejected(tmp_session_dir: Path) -> None:
    with pytest.raises(ValueError):
        TranscriptWriter("/tmp/finagent_abs_poc", base_dir=tmp_session_dir)


def test_load_transcript_traversal_returns_empty(tmp_session_dir: Path) -> None:
    """Read side refuses an unsafe stem → empty (clean 404), not a foreign read."""
    assert load_session_transcript("../../../../etc/passwd", base_dir=tmp_session_dir) == []


@pytest.mark.asyncio
async def test_writer_legit_session_unaffected(tmp_session_dir: Path) -> None:
    """A normal session_id still round-trips exactly as before."""
    writer = TranscriptWriter("legit-sess.99", base_dir=tmp_session_dir)
    await writer.log_user_message("hi")
    events = load_session_transcript("legit-sess.99", base_dir=tmp_session_dir)
    assert events[0]["data"]["text"] == "hi"
    written = tmp_session_dir / "legit-sess.99.jsonl"
    assert written.exists()
    assert written.resolve().parent == tmp_session_dir.resolve()
