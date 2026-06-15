"""Tests for the SSE event TypedDicts in finrobot.events."""

from __future__ import annotations

from finrobot.events import (
    ArtifactReady,
    RunCompleted,
    RunEvent,
)


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
