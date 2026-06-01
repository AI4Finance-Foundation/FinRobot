"""Tests for debate SSE event TypedDicts added to finrobot.events."""

from __future__ import annotations

from finrobot.events import DebatePoint, DebateVerdict, RunEvent


def test_debate_events_in_runevent_union() -> None:
    p: DebatePoint = {
        "event": "debate.point",
        "run_id": "r",
        "side": "bull",
        "claim": "x",
        "evidence_ids": [],
        "verified": False,
        "reason": "z",
    }
    v: DebateVerdict = {
        "event": "debate.verdict",
        "run_id": "r",
        "call": "HOLD",
        "conviction": 0.5,
        "swing_factor": "s",
        "change_my_mind": "c",
    }
    assert p["event"] == "debate.point" and v["call"] == "HOLD"


def test_debate_point_fields() -> None:
    """All required fields are accessible by key."""
    p: DebatePoint = {
        "event": "debate.point",
        "run_id": "run-123",
        "side": "bear",
        "claim": "Revenue growth is decelerating",
        "evidence_ids": ["ev-1", "ev-2"],
        "verified": True,
        "reason": "Two consecutive quarters of YoY deceleration",
    }
    assert p["side"] == "bear"
    assert p["evidence_ids"] == ["ev-1", "ev-2"]
    assert p["verified"] is True


def test_debate_verdict_fields() -> None:
    """Verdict fields including nullable conviction are accessible."""
    v: DebateVerdict = {
        "event": "debate.verdict",
        "run_id": "run-456",
        "call": "SELL",
        "conviction": None,
        "swing_factor": "Unreliable data — gate tripped",
        "change_my_mind": "Confirmed revenue rebound in Q3",
    }
    assert v["call"] == "SELL"
    assert v["conviction"] is None


def test_debate_verdict_in_runevent() -> None:
    """DebateVerdict is a valid member of RunEvent (type-level check via annotation)."""
    verdict: RunEvent = {
        "event": "debate.verdict",
        "run_id": "r",
        "call": "BUY",
        "conviction": 0.8,
        "swing_factor": "Strong FCF",
        "change_my_mind": "Multiple compression",
    }
    assert verdict["event"] == "debate.verdict"


def test_debate_point_in_runevent() -> None:
    """DebatePoint is a valid member of RunEvent (type-level check via annotation)."""
    point: RunEvent = {
        "event": "debate.point",
        "run_id": "r",
        "side": "bull",
        "claim": "Margins expanding",
        "evidence_ids": [],
        "verified": True,
        "reason": "Gross margin up 200bps YoY",
    }
    assert point["event"] == "debate.point"
