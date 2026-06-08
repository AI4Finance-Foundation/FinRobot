"""Unit tests for the /chat non-streaming fallback (Claude-Code-style).

The streaming path (`run_stream_native` → `transform_stream` → SSE) is the
norm. When the model/proxy fails mid-stream or returns an *empty* stream
(HTTP 200 but no usable SSE body), `pydantic_ai`'s `transform_stream` swallows
the failure into an envelope of control frames (``start`` … ``error`` … or just
``start`` … ``finish``) — verified empirically. `_stream_with_fallback` detects
that "no content frame ever arrived" case and, when no tool executed this turn,
re-issues the SAME request once via a non-streaming `agent.run`, emitting the
whole answer as a single Vercel AI message so the desktop renders it unchanged.

These tests drive `_stream_with_fallback` directly with fake chunk streams and
a fake agent — no real LLM calls. They assert:
  - happy path: chunk bytes are emitted unchanged, no fallback fires;
  - empty stream: fallback emits the full single-message frame sequence once;
  - error stream: the ``error`` frame is swallowed and replaced by the fallback;
  - tool-executed guard: an empty turn that ran a tool does NOT fall back.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pydantic_ai.ui.vercel_ai._event_stream import VercelAIEventStream
from pydantic_ai.ui.vercel_ai.response_types import (
    DoneChunk,
    ErrorChunk,
    FinishChunk,
    FinishStepChunk,
    StartChunk,
    StartStepChunk,
    TextDeltaChunk,
    TextEndChunk,
    TextStartChunk,
)

from finrobot.audit.transcript import TranscriptWriter
from finrobot.server import _stream_with_fallback


# --------------------------------------------------------------------------- #
# Fakes                                                                        #
# --------------------------------------------------------------------------- #


class _FakeResponse:
    def __init__(self, finish_reason: str | None) -> None:
        self.finish_reason = finish_reason


class _FakeRunResult:
    def __init__(self, output: str, finish_reason: str | None = "stop") -> None:
        self.output = output
        self.response = _FakeResponse(finish_reason)


class _FakeAgent:
    """Records that `run` was called once and with what message_history."""

    def __init__(self, output: str = "fallback answer") -> None:
        self._output = output
        self.run_calls: list[dict[str, Any]] = []

    async def run(self, **kwargs: Any) -> _FakeRunResult:
        self.run_calls.append(kwargs)
        return _FakeRunResult(self._output)


async def _achunks(*chunks: Any) -> Any:
    """Yield the given chunk objects as an async iterator (a fake event stream)."""
    for c in chunks:
        yield c


def _encoder() -> VercelAIEventStream:
    """A real Vercel event-stream instance used purely as the chunk encoder."""
    return VercelAIEventStream(run_input=None, accept=None, sdk_version=5)


async def _collect(agen: Any) -> list[str]:
    return [frame async for frame in agen]


def _types(frames: list[str]) -> list[str]:
    """Extract the chunk ``type`` discriminator from each encoded SSE frame."""
    import json

    out: list[str] = []
    for f in frames:
        payload = f.removeprefix("data: ").rstrip("\n")
        if payload == "[DONE]":
            out.append("done")
        else:
            out.append(json.loads(payload)["type"])
    return out


@pytest.fixture()
def writer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TranscriptWriter:
    monkeypatch.setattr("finrobot.audit.transcript._DEFAULT_DIR", tmp_path / "sessions")
    return TranscriptWriter("fallback-test")


def _read_assistant_texts(writer: TranscriptWriter) -> list[str]:
    import json

    path = writer._path  # noqa: SLF001 — test reads the writer's resolved JSONL path
    if not Path(path).exists():
        return []
    texts: list[str] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        evt = json.loads(line)
        if evt.get("event") == "assistant_text":
            texts.append(evt["data"]["text"])
    return texts


# --------------------------------------------------------------------------- #
# Happy path: streaming bytes are unchanged, no fallback                       #
# --------------------------------------------------------------------------- #


async def test_happy_path_streams_unchanged_no_fallback(writer: TranscriptWriter) -> None:
    """A stream with a content frame is forwarded byte-for-byte; agent.run unused."""
    agent = _FakeAgent()
    enc = _encoder()
    # Canonical one-text streaming turn.
    happy = _achunks(
        StartChunk(),
        StartStepChunk(),
        TextStartChunk(id="m1"),
        TextDeltaChunk(id="m1", delta="Hello world"),
        TextEndChunk(id="m1"),
        FinishStepChunk(),
        FinishChunk(finish_reason="stop"),
        DoneChunk(),
    )
    frames = await _collect(
        _stream_with_fallback(
            event_stream=happy,
            encoder=enc,
            agent=agent,
            message_history=[],
            deferred_tool_results=None,
            instructions=None,
            deps=None,
            writer=writer,
            tool_state={},
        )
    )

    # Byte-for-byte identical to plain encoding of the same chunks.
    expected_enc = _encoder()
    expected = [
        expected_enc.encode_event(c)
        for c in [
            StartChunk(),
            StartStepChunk(),
            TextStartChunk(id="m1"),
            TextDeltaChunk(id="m1", delta="Hello world"),
            TextEndChunk(id="m1"),
            FinishStepChunk(),
            FinishChunk(finish_reason="stop"),
            DoneChunk(),
        ]
    ]
    assert frames == expected
    assert agent.run_calls == [], "fallback must not run agent.run on the happy path"


# --------------------------------------------------------------------------- #
# Empty stream → fallback                                                       #
# --------------------------------------------------------------------------- #


async def test_empty_stream_triggers_nonstreaming_fallback(writer: TranscriptWriter) -> None:
    """A content-free envelope (start → finish → done) is replaced by the fallback."""
    agent = _FakeAgent(output="recovered answer")
    # What transform_stream emits for an EMPTY native stream (no start-step).
    empty = _achunks(
        StartChunk(),
        FinishStepChunk(),
        FinishChunk(finish_reason="stop"),
        DoneChunk(),
    )
    frames = await _collect(
        _stream_with_fallback(
            event_stream=empty,
            encoder=_encoder(),
            agent=agent,
            message_history=[{"sentinel": "history"}],
            deferred_tool_results=None,
            instructions="instr",
            deps="deps",
            writer=writer,
            tool_state={},
        )
    )

    # Exactly one agent.run, re-issued with the SAME history/instructions/deps.
    assert len(agent.run_calls) == 1
    call = agent.run_calls[0]
    assert call["message_history"] == [{"sentinel": "history"}]
    assert call["instructions"] == "instr"
    assert call["deps"] == "deps"
    assert call["deferred_tool_results"] is None

    # The fallback emits the canonical single-message frame sequence.
    assert _types(frames) == [
        "start",
        "start-step",
        "text-start",
        "text-delta",
        "text-end",
        "finish-step",
        "finish",
        "done",
    ]
    # The full answer rides in the single text-delta.
    import json

    delta_frame = next(f for f in frames if '"type":"text-delta"' in f)
    assert json.loads(delta_frame.removeprefix("data: "))["delta"] == "recovered answer"

    # Transcript side-log is preserved for the fallback path.
    assert _read_assistant_texts(writer) == ["recovered answer"]


async def test_error_stream_triggers_fallback_and_swallows_error(
    writer: TranscriptWriter,
) -> None:
    """A failed turn (envelope containing an ``error`` frame) falls back; no error leaks."""
    agent = _FakeAgent(output="answer after retry")
    # What transform_stream emits for a RAISING native stream.
    errored = _achunks(
        StartChunk(),
        ErrorChunk(error_text="boom: proxy 200 no SSE"),
        FinishStepChunk(),
        FinishChunk(finish_reason="error"),
        DoneChunk(),
    )
    frames = await _collect(
        _stream_with_fallback(
            event_stream=errored,
            encoder=_encoder(),
            agent=agent,
            message_history=[],
            deferred_tool_results=None,
            instructions=None,
            deps=None,
            writer=writer,
            tool_state={},
        )
    )

    assert len(agent.run_calls) == 1
    # The error frame must NOT reach the client; only the clean fallback message.
    assert "error" not in _types(frames)
    assert "boom" not in "".join(frames)
    assert _types(frames) == [
        "start",
        "start-step",
        "text-start",
        "text-delta",
        "text-end",
        "finish-step",
        "finish",
        "done",
    ]


# --------------------------------------------------------------------------- #
# Guard: a tool executed → never fall back                                     #
# --------------------------------------------------------------------------- #


async def test_tool_executed_empty_turn_does_not_fall_back(writer: TranscriptWriter) -> None:
    """If a tool ran but the model produced no text, replay the envelope; no agent.run."""
    agent = _FakeAgent()
    empty = _achunks(
        StartChunk(),
        FinishStepChunk(),
        FinishChunk(finish_reason="stop"),
        DoneChunk(),
    )
    frames = await _collect(
        _stream_with_fallback(
            event_stream=empty,
            encoder=_encoder(),
            agent=agent,
            message_history=[],
            deferred_tool_results=None,
            instructions=None,
            deps=None,
            writer=writer,
            tool_state={"tool_executed": True},
        )
    )

    assert agent.run_calls == [], "must not re-run agent.run after a tool executed"
    # The held envelope is replayed so the stream is still well-formed/terminated.
    assert _types(frames) == ["start", "finish-step", "finish", "done"]


async def test_content_stream_with_tool_is_unchanged(writer: TranscriptWriter) -> None:
    """A turn that ran a tool AND produced text streams unchanged, no fallback."""
    agent = _FakeAgent()
    streamed = _achunks(
        StartChunk(),
        StartStepChunk(),
        TextStartChunk(id="m1"),
        TextDeltaChunk(id="m1", delta="from tool result"),
        TextEndChunk(id="m1"),
        FinishStepChunk(),
        FinishChunk(finish_reason="stop"),
        DoneChunk(),
    )
    frames = await _collect(
        _stream_with_fallback(
            event_stream=streamed,
            encoder=_encoder(),
            agent=agent,
            message_history=[],
            deferred_tool_results=None,
            instructions=None,
            deps=None,
            writer=writer,
            tool_state={"tool_executed": True},
        )
    )
    assert agent.run_calls == []
    assert _types(frames)[2] == "text-start"
