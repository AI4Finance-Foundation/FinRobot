"""engine/instructions.md — the lead agent's standing policy.

Regression guards for the report-scope boundary. gpt-4o, told to "proactively
surface movers even if not asked", spliced watchlist names (TSLA/AMD) into an
AAPL deep-dive report body. The fix moves the surfacing policy here and scopes
it: proactive surfacing is for conversational replies; a report body is scoped
strictly to its ticker. These guards keep that boundary from being deleted.
"""

from __future__ import annotations

from pathlib import Path

import finrobot.engine.orchestrator as orchestrator

_RAW = (Path(orchestrator.__file__).parent / "instructions.md").read_text(encoding="utf-8")
# Collapse markdown line-wrapping so guards check semantic content, not where a
# soft wrap happens to fall.
_INSTRUCTIONS = " ".join(_RAW.lower().split())


def test_proactive_mover_surfacing_is_scoped_to_conversation() -> None:
    assert "conversational reply" in _INSTRUCTIONS


def test_report_body_must_not_import_watchlist_context() -> None:
    assert "never inject watchlist" in _INSTRUCTIONS
