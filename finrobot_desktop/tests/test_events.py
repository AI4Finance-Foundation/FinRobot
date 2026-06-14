"""Tests for debate SSE event TypedDicts added to finrobot.events."""

from __future__ import annotations

from finrobot.events import (
    ArtifactReady,
    DebateEvidence,
    DebatePoint,
    DebateVerdict,
    RunCompleted,
    RunEvent,
)


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
        "swing_factor": "Whether peer multiples apply to this issuer's earnings quality",
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


def test_debate_evidence_fields() -> None:
    """DebateEvidence carries ticker, current_price, confidence, withheld flag, items."""
    ev: DebateEvidence = {
        "event": "debate.evidence",
        "run_id": "run-001",
        "ticker": "AAPL",
        "current_price": 195.0,
        "confidence": "high",
        "valuation_withheld": False,
        "items": [
            {
                "evidence_id": "dcf.fair_value",
                "label": "DCF Fair Value",
                "value": 210.5,
                "unit": "$",
                "formula_id": "dcf_v1",
            }
        ],
    }
    assert ev["event"] == "debate.evidence"
    assert ev["ticker"] == "AAPL"
    assert ev["current_price"] == 195.0
    assert ev["confidence"] == "high"
    assert ev["valuation_withheld"] is False
    assert ev["items"][0]["evidence_id"] == "dcf.fair_value"


def test_debate_evidence_in_runevent() -> None:
    """DebateEvidence is a valid member of RunEvent (type-level check via annotation)."""
    ev: RunEvent = {
        "event": "debate.evidence",
        "run_id": "run-002",
        "ticker": "NVDA",
        "current_price": 900.0,
        "confidence": "very_low",
        "valuation_withheld": True,
        "items": [],
    }
    assert ev["event"] == "debate.evidence"


def test_debate_evidence_empty_items() -> None:
    """DebateEvidence with an empty items list is valid (low-confidence / withheld case)."""
    ev: DebateEvidence = {
        "event": "debate.evidence",
        "run_id": "run-003",
        "ticker": "X",
        "current_price": 10.0,
        "confidence": "very_low",
        "valuation_withheld": True,
        "items": [],
    }
    assert ev["items"] == []
    assert ev["confidence"] == "very_low"


def test_artifact_ready_carries_artifact_id() -> None:
    """ArtifactReady now exposes the persisted artifact's id + type so a consumer
    can open THIS run's product instead of guessing the ticker's latest one."""
    ev: ArtifactReady = {
        "event": "artifact.ready",
        "run_id": "run-100",
        "artifact_type": "dcf",
        "format": "json",
        "artifact_id": "art_2026-06-02_AAPL_dcf",
    }
    assert ev["artifact_id"] == "art_2026-06-02_AAPL_dcf"
    assert ev["artifact_type"] == "dcf"


def test_artifact_ready_back_compat_without_artifact_id() -> None:
    """artifact_id is optional — older stored events (pre-field) stay valid."""
    ev: ArtifactReady = {
        "event": "artifact.ready",
        "run_id": "run-101",
        "artifact_type": "artifact",
        "format": "json",
    }
    assert "artifact_id" not in ev


def test_run_completed_carries_artifact_identity() -> None:
    """RunCompleted carries artifact_id + artifact_type so the completion CTA
    routes to the exact artifact regardless of pipeline type."""
    ev: RunCompleted = {
        "event": "run.completed",
        "run_id": "run-200",
        "ticker": "AAPL",
        "duration_s": 12.3,
        "result_url": "/api/artifacts/art_2026-06-02_AAPL_lbo",
        "artifact_id": "art_2026-06-02_AAPL_lbo",
        "artifact_type": "lbo",
    }
    assert ev["artifact_id"] == "art_2026-06-02_AAPL_lbo"
    assert ev["artifact_type"] == "lbo"
    assert ev["result_url"].endswith("art_2026-06-02_AAPL_lbo")


def test_run_completed_back_compat_without_artifact() -> None:
    """A run that produced no artifact omits the optional identity fields."""
    ev: RunCompleted = {
        "event": "run.completed",
        "run_id": "run-201",
        "ticker": "AAPL",
        "duration_s": 3.0,
        "result_url": "/api/runs/run-201",
    }
    assert "artifact_id" not in ev
    assert "artifact_type" not in ev


def test_completion_events_in_runevent_union() -> None:
    """ArtifactReady / RunCompleted with the new fields remain valid RunEvents."""
    ready: RunEvent = {
        "event": "artifact.ready",
        "run_id": "r",
        "artifact_type": "comps",
        "format": "json",
        "artifact_id": "art_x",
    }
    done: RunEvent = {
        "event": "run.completed",
        "run_id": "r",
        "ticker": "T",
        "duration_s": 1.0,
        "result_url": "/api/artifacts/art_x",
        "artifact_id": "art_x",
        "artifact_type": "comps",
    }
    assert ready["event"] == "artifact.ready"
    assert done["event"] == "run.completed"
