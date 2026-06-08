"""Integration test: /chat endpoint writes to JSONL transcript.

Covers:
  - session_start + user_msg appear on the JSONL file
  - _extract_user_text supports string-content (legacy), parts-based (modern),
    and mixed list-content message shapes
  - Multi-part messages combine text + file/image placeholders
  - Malformed/empty parts arrays do not raise — they yield empty text
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from finrobot.server import _extract_user_text


@pytest.fixture()
def _reset_transcript_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect TranscriptWriter to a temp directory for isolation."""
    sess_dir = tmp_path / "sessions"
    monkeypatch.setattr(
        "finrobot.audit.transcript._DEFAULT_DIR",
        sess_dir,
    )
    return sess_dir


def _read_user_msg(sess_dir: Path, session_id: str) -> dict[str, object]:
    """Return the user_msg event dict from a session's JSONL file."""
    path = sess_dir / f"{session_id}.jsonl"
    assert path.exists(), f"Transcript file not found at {path}"
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        evt = json.loads(line)
        if evt.get("event") == "user_msg":
            return evt
    raise AssertionError(f"No user_msg event found in {path}")


async def _post_chat(payload: dict[str, object]) -> None:
    """POST /chat without caring about the streaming response (which needs an LLM)."""
    from finrobot.config import get_settings
    from finrobot.engine.deps import FinRobotDeps
    from finrobot.engine.orchestrator import create_lead_agent
    from finrobot.server import app

    settings = get_settings(model_name="test")
    agent = create_lead_agent(settings)
    app.state.agent = agent
    app.state.deps = FinRobotDeps(data_layer=None, settings=settings)  # type: ignore[arg-type]
    app.state.transcript_writers = {}
    app.state.artifact_store = None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        try:
            await c.post("/chat", json=payload)
        except Exception:
            pass  # LLM call failure expected in unit test context


# ---------------------------------------------------------------------------
# Existing integration tests (preserved)
# ---------------------------------------------------------------------------


async def test_chat_writes_session_start_and_user_msg(_reset_transcript_dir: Path) -> None:
    """POST /chat should write session_start + user_msg to JSONL before streaming."""
    session_id = "integration-test-session"
    await _post_chat(
        {
            "id": session_id,
            "model": "test-model",
            "messages": [
                {"role": "user", "parts": [{"type": "text", "text": "What is AAPL?"}]},
            ],
        }
    )

    sess_dir = _reset_transcript_dir
    path = sess_dir / f"{session_id}.jsonl"
    assert path.exists(), f"Transcript file not found at {path}"
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    events = [json.loads(ln) for ln in lines]

    event_types = [e["event"] for e in events]
    assert "session_start" in event_types, f"Missing session_start. Got: {event_types}"
    assert "user_msg" in event_types, f"Missing user_msg. Got: {event_types}"

    user_evt = next(e for e in events if e["event"] == "user_msg")
    assert user_evt["session_id"] == session_id
    # Parts-based message text must round-trip into the JSONL.
    assert user_evt["data"]["text"] == "What is AAPL?"


async def test_chat_missing_session_id_uses_default(_reset_transcript_dir: Path) -> None:
    """When no ``id`` field in body, session_id should fall back to 'default'."""
    await _post_chat({"messages": []})
    sess_dir = _reset_transcript_dir
    assert (sess_dir / "default.jsonl").exists()


# ---------------------------------------------------------------------------
# Three message-shape contract tests (the P0 fix being covered)
# ---------------------------------------------------------------------------


async def test_transcript_captures_string_content(_reset_transcript_dir: Path) -> None:
    """Legacy {"content": "hello"} → user_msg.data.text == "hello"."""
    session_id = "shape-string-content"
    await _post_chat(
        {
            "id": session_id,
            "messages": [{"role": "user", "content": "hello"}],
        }
    )
    evt = _read_user_msg(_reset_transcript_dir, session_id)
    assert evt["data"]["text"] == "hello"


async def test_transcript_captures_parts_text(_reset_transcript_dir: Path) -> None:
    """Modern {"parts": [{"type":"text","text":"hello"}]} → user_msg.data.text == "hello"."""
    session_id = "shape-parts-text"
    await _post_chat(
        {
            "id": session_id,
            "messages": [{"role": "user", "parts": [{"type": "text", "text": "hello"}]}],
        }
    )
    evt = _read_user_msg(_reset_transcript_dir, session_id)
    assert evt["data"]["text"] == "hello"


async def test_transcript_captures_multi_part(_reset_transcript_dir: Path) -> None:
    """Multi-part: text + file → joined with newline + [attached: name] placeholder."""
    session_id = "shape-multi-part"
    await _post_chat(
        {
            "id": session_id,
            "messages": [
                {
                    "role": "user",
                    "parts": [
                        {"type": "text", "text": "分析这个"},
                        {"type": "file", "filename": "10K.pdf"},
                    ],
                }
            ],
        }
    )
    evt = _read_user_msg(_reset_transcript_dir, session_id)
    assert evt["data"]["text"] == "分析这个\n[attached: 10K.pdf]"


# ---------------------------------------------------------------------------
# Five exception-path tests — direct unit tests on _extract_user_text
# (faster and clearer than full HTTP round-trips for negative cases)
# ---------------------------------------------------------------------------


def test_transcript_handles_empty_parts() -> None:
    """``{"parts": []}`` returns empty string without raising."""
    result = _extract_user_text({"role": "user", "parts": []})
    assert result == ""


def test_transcript_handles_missing_text_field() -> None:
    """``{"parts": [{"type":"text"}]}`` (no text key) is skipped, returns ""."""
    result = _extract_user_text({"role": "user", "parts": [{"type": "text"}]})
    assert result == ""


def test_transcript_handles_unknown_part_type() -> None:
    """Unknown part types (``audio``, ``video``, etc.) are silently dropped."""
    result = _extract_user_text(
        {
            "role": "user",
            "parts": [{"type": "audio", "url": "http://example.com/foo.mp3"}],
        }
    )
    assert result == ""


def test_transcript_handles_non_dict_part() -> None:
    """Non-dict items inside ``parts`` (raw strings, ints) are silently skipped."""
    result = _extract_user_text({"role": "user", "parts": ["raw string", 42, None]})
    assert result == ""


def test_transcript_handles_neither_content_nor_parts() -> None:
    """Message with neither ``content`` nor ``parts`` returns ""."""
    result = _extract_user_text({"role": "user"})
    assert result == ""


# ---------------------------------------------------------------------------
# Bonus: mixed-shape contract (list content path) — defensive cross-check
# ---------------------------------------------------------------------------


def test_transcript_handles_list_content() -> None:
    """When ``content`` itself is a list of parts, it is treated like ``parts``."""
    result = _extract_user_text(
        {
            "role": "user",
            "content": [{"type": "text", "text": "from-list-content"}],
        }
    )
    assert result == "from-list-content"


def test_transcript_handles_image_part() -> None:
    """Image parts render as ``[image]`` placeholder."""
    result = _extract_user_text(
        {
            "role": "user",
            "parts": [
                {"type": "text", "text": "see this:"},
                {"type": "image", "url": "data:image/png;base64,xxx"},
            ],
        }
    )
    assert result == "see this:\n[image]"


def test_transcript_file_without_filename_uses_default() -> None:
    """File parts without a ``filename`` field render as ``[attached: file]``."""
    result = _extract_user_text(
        {
            "role": "user",
            "parts": [{"type": "file", "url": "data:..."}],
        }
    )
    assert result == "[attached: file]"


# ---------------------------------------------------------------------------
# BUG-20260602-038 / 048: /chat records locale + context_bundle in transcript
# ---------------------------------------------------------------------------


def _read_events(sess_dir: Path, session_id: str) -> list[dict[str, object]]:
    path = sess_dir / f"{session_id}.jsonl"
    assert path.exists(), f"Transcript file not found at {path}"
    out: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


async def test_chat_records_locale_and_ticker_in_session_start(
    _reset_transcript_dir: Path,
) -> None:
    """A body carrying ``locale`` + ``ticker`` stamps both onto session_start."""
    session_id = "ctx-session-start"
    await _post_chat(
        {
            "id": session_id,
            "model": "test-model",
            "ticker": "AAPL",
            "locale": "zh",
            "messages": [{"role": "user", "parts": [{"type": "text", "text": "估值?"}]}],
        }
    )
    events = _read_events(_reset_transcript_dir, session_id)
    start = next(e for e in events if e["event"] == "session_start")
    assert start["data"]["ticker"] == "AAPL"
    assert start["data"]["locale"] == "zh"


async def test_chat_session_start_model_comes_from_settings_not_body(
    _reset_transcript_dir: Path,
) -> None:
    """session_start records the model from authoritative settings (= what the
    user picked / the agent runs), never the client's ``model`` field — which
    raced the /api/settings fetch and stamped a bogus "unknown" into the audit
    trail (BUG-20260608). ``_post_chat`` configures settings.model_name="test"."""
    session_id = "model-from-settings"
    await _post_chat(
        {
            "id": session_id,
            "model": "unknown",  # client echo — must be ignored
            "messages": [{"role": "user", "parts": [{"type": "text", "text": "hi"}]}],
        }
    )
    events = _read_events(_reset_transcript_dir, session_id)
    start = next(e for e in events if e["event"] == "session_start")
    assert start["data"]["model"] == "test"
    assert start["data"]["model"] != "unknown"


async def test_chat_records_context_bundle_event(_reset_transcript_dir: Path) -> None:
    """A ``context_bundle`` in the body is written as a ``context`` event."""
    session_id = "ctx-bundle"
    bundle = {
        "route": "/stocks/AAPL/runs/art_1",
        "ticker": "AAPL",
        "artifact_id": "art_1",
        "pinned": [{"kind": "report", "id": "art_9", "label": "NVDA DCF"}],
        "selected_text": "operating margin expanded 300bps",
    }
    await _post_chat(
        {
            "id": session_id,
            "model": "test-model",
            "context_bundle": bundle,
            "messages": [{"role": "user", "parts": [{"type": "text", "text": "explain"}]}],
        }
    )
    events = _read_events(_reset_transcript_dir, session_id)
    ctx = next(e for e in events if e["event"] == "context")
    recorded = ctx["data"]["context_bundle"]
    assert recorded["artifact_id"] == "art_1"
    assert recorded["pinned"][0]["label"] == "NVDA DCF"


def test_build_runtime_instructions_locale_and_context() -> None:
    """Locale + bundle compose into one instruction block; empty inputs → None."""
    from finrobot.server import _build_runtime_instructions

    assert _build_runtime_instructions(None, None) is None

    out = _build_runtime_instructions(
        "zh",
        {
            "route": "/stocks/AAPL/runs/art_1",
            "ticker": "aapl",
            "artifact_id": "art_1",
            "pinned": [{"kind": "report", "id": "art_9", "label": "NVDA DCF"}],
            "selected_text": "margin up 300bps",
        },
    )
    assert out is not None
    # Locale directive present, naming the target language.
    assert "Chinese" in out
    # Context surfaced for grounding.
    assert "art_1" in out
    assert "AAPL" in out  # ticker upper-cased
    assert "NVDA DCF" in out
    assert "margin up 300bps" in out


def test_build_runtime_instructions_locale_only() -> None:
    """Locale without a bundle still yields a language directive."""
    from finrobot.server import _build_runtime_instructions

    out = _build_runtime_instructions("en", None)
    assert out is not None
    assert "English" in out
