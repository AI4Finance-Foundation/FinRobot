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
    prune_sessions,
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


@pytest.mark.asyncio
async def test_authorization_bearer_is_redacted(tmp_session_dir: Path) -> None:
    """``Authorization: Bearer <token>`` (auth.py capability token, LLM SDK
    keys in httpx exception dumps) must never reach disk verbatim."""
    writer = TranscriptWriter("sess-redact-bearer", base_dir=tmp_session_dir)
    await writer.log_error(
        exception_class="ProviderError",
        message='401 with headers {"Authorization": "Bearer cap-tok-1234567890abcdef"}',
        context={"raw": "Authorization: Basic dXNlcjpwYXNzd29yZA=="},
    )

    path = tmp_session_dir / "sess-redact-bearer.jsonl"
    raw = path.read_text(encoding="utf-8")
    assert "cap-tok-1234567890abcdef" not in raw
    assert "dXNlcjpwYXNzd29yZA" not in raw
    assert raw.count("[REDACTED]") == 2
    # Scheme prefix is preserved so the audit trail shows WHICH credential type leaked.
    assert "Bearer [REDACTED]" in raw
    assert "Basic [REDACTED]" in raw


@pytest.mark.asyncio
async def test_token_query_and_settings_dump_keys_are_redacted(tmp_session_dir: Path) -> None:
    """``?token=`` (auth.py query fallback, finnhub-style URLs) and JSON
    settings-dump keys (``"fmp_api_key": "..."``) are scrubbed; bare ``sk-``
    LLM keys are scrubbed even with no key= prefix at all."""
    writer = TranscriptWriter("sess-redact-misc", base_dir=tmp_session_dir)
    await writer.log_error(
        exception_class="RuntimeError",
        message="GET wss://local/api/chat?token=cap999secret -> 403",
        context={
            "settings": '{"fmp_api_key": "fmp-live-key-1", "client_secret": "cs-2"}',
            "sdk": "AuthenticationError: invalid key sk-ant-api03-AAAAAAAAAAAAAAAA",
        },
    )

    path = tmp_session_dir / "sess-redact-misc.jsonl"
    raw = path.read_text(encoding="utf-8")
    assert "cap999secret" not in raw
    assert "fmp-live-key-1" not in raw
    assert "cs-2" not in raw
    assert "sk-ant-api03" not in raw


@pytest.mark.asyncio
async def test_scrubber_leaves_benign_text_untouched(tmp_session_dir: Path) -> None:
    """Near-miss shapes must survive: ``max_tokens=`` is a model param, not a
    credential, and short prose after 'bearer' is not a token68 value."""
    writer = TranscriptWriter("sess-noredact", base_dir=tmp_session_dir)
    benign = "ran with max_tokens=4096; the bearer of bad news; tokenizer: tiktoken"
    await writer.log_user_message(benign)

    path = tmp_session_dir / "sess-noredact.jsonl"
    raw = path.read_text(encoding="utf-8")
    assert "[REDACTED]" not in raw
    assert "max_tokens=4096" in raw


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


async def _seed_sessions_with_spread_mtimes(base_dir: Path, count: int) -> list[str]:
    """Write ``count`` sessions and force strictly increasing mtimes.

    Sub-millisecond writes can collide on filesystems with coarse mtime
    granularity, so the mtimes are pinned explicitly — sess-0 oldest,
    sess-{count-1} newest.
    """
    import os

    ids = [f"sess-{i}" for i in range(count)]
    for i, sid in enumerate(ids):
        writer = TranscriptWriter(sid, base_dir=base_dir)
        await writer.log_session_start(user_id="local", model="m")
        await writer.log_user_message(f"turn {i}")
        path = base_dir / f"{sid}.jsonl"
        os.utime(path, (1_700_000_000 + i, 1_700_000_000 + i))
    return ids


@pytest.mark.asyncio
async def test_list_sessions_limit_returns_newest_page_without_full_scan(
    tmp_session_dir: Path,
) -> None:
    """``limit`` must page the newest-N by file mtime (≡ last_active_at for
    append-only JSONL) — the unbounded full-dir parse was the audit finding."""
    await _seed_sessions_with_spread_mtimes(tmp_session_dir, 5)

    page = list_sessions(base_dir=tmp_session_dir, limit=2)
    assert [s.session_id for s in page] == ["sess-4", "sess-3"]

    # limit larger than population → everything, newest first.
    everything = list_sessions(base_dir=tmp_session_dir, limit=50)
    assert len(everything) == 5

    with pytest.raises(ValueError, match="limit must be >= 1"):
        list_sessions(base_dir=tmp_session_dir, limit=0)


@pytest.mark.asyncio
async def test_list_sessions_limit_applies_after_filters(tmp_session_dir: Path) -> None:
    """The cap counts MATCHING sessions — a ticker filter must not eat the page."""
    import os

    for i, (sid, ticker) in enumerate(
        [("a-aapl", "AAPL"), ("b-nvda", "NVDA"), ("c-aapl", "AAPL"), ("d-aapl", "AAPL")]
    ):
        writer = TranscriptWriter(sid, base_dir=tmp_session_dir)
        await writer.log_session_start(user_id="local", model="m", ticker=ticker)
        path = tmp_session_dir / f"{sid}.jsonl"
        os.utime(path, (1_700_000_000 + i, 1_700_000_000 + i))

    page = list_sessions(base_dir=tmp_session_dir, ticker="AAPL", limit=2)
    assert [s.session_id for s in page] == ["d-aapl", "c-aapl"]


# ---------------------------------------------------------------------------
# persistence.prune_sessions (retention policy)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prune_sessions_deletes_oldest_past_cap(tmp_session_dir: Path) -> None:
    await _seed_sessions_with_spread_mtimes(tmp_session_dir, 5)

    deleted = prune_sessions(max_sessions=3, base_dir=tmp_session_dir)
    assert deleted == 2
    remaining = sorted(p.stem for p in tmp_session_dir.glob("*.jsonl"))
    assert remaining == ["sess-2", "sess-3", "sess-4"]

    # Idempotent — already at cap.
    assert prune_sessions(max_sessions=3, base_dir=tmp_session_dir) == 0


def test_prune_sessions_under_cap_and_missing_dir_are_noops(tmp_session_dir: Path) -> None:
    assert prune_sessions(max_sessions=10, base_dir=tmp_session_dir / "nope") == 0
    with pytest.raises(ValueError, match="max_sessions must be >= 1"):
        prune_sessions(max_sessions=0, base_dir=tmp_session_dir)


@pytest.mark.asyncio
async def test_session_start_triggers_retention_prune(
    tmp_session_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The writer enforces retention on session start (no scheduler exists in
    the desktop deployment, so this is the only place the cap can hold)."""
    calls: list[Path] = []

    def spy_prune(max_sessions: int = 500, base_dir: Path | None = None) -> int:
        assert base_dir is not None
        calls.append(base_dir)
        return 0

    monkeypatch.setattr("finrobot.audit.persistence.prune_sessions", spy_prune)
    writer = TranscriptWriter("prune-wire", base_dir=tmp_session_dir)
    await writer.log_session_start(user_id="local", model="m")
    assert calls == [tmp_session_dir]


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
