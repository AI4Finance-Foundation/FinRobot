"""Pin the SSE event contract between routes/runs.py and desktop/src/stores/runStreamStore.ts.

Spec §5.3 originally listed an aspirational event vocabulary
(``pipeline.start`` / ``step.start`` / ``step.complete`` …) but the running
code uses ``run.X`` / ``step.X`` naming and both halves of the contract
(backend producer + frontend consumer) already agree. The spec note ends with
*"不新增 event 类型"* — so PR4a's job is to pin the existing contract, not
churn the names.

This audit catches silent drift: if anyone renames a backend event without
also updating ``desktop/src/stores/runStreamStore.ts``, the UI would silently
stop receiving progress updates. The contract test makes that a hard CI
failure instead of a debug-friday surprise.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "finrobot" / "routes" / "runs.py"
# The UI lives under desktop/ (the old ui/ path silently skipped the frontend
# half of this contract for months — an audit that can't find its subject must
# fail loudly, hence the hard assert in the test below).
FRONTEND_SRC = REPO_ROOT / "desktop" / "src" / "stores" / "runStreamStore.ts"

# The events both sides must agree on. Adding to this list requires both
# code paths AND this test to update in lockstep — that's the point.
_REQUIRED_EVENTS = (
    "run.started",
    "step.started",
    "step.completed",
    "step.retry",
    "run.completed",
    "run.failed",
    "run.cancelled",
)


def test_backend_emits_every_required_sse_event() -> None:
    src = BACKEND_SRC.read_text()
    missing = [name for name in _REQUIRED_EVENTS if f'"{name}"' not in src]
    assert not missing, (
        f"routes/runs.py is missing SSE event emit for: {missing}. "
        "Either re-add the emit or update _REQUIRED_EVENTS + the frontend store."
    )


def test_frontend_listens_for_every_required_sse_event() -> None:
    # No exists()-guard: the old guard pointed at a stale ui/ path and silently
    # skipped this half of the contract for months. If the store moves, update
    # FRONTEND_SRC — don't let the audit pass vacuously.
    src = FRONTEND_SRC.read_text()
    missing = [
        name
        for name in _REQUIRED_EVENTS
        if not re.search(rf"addEventListener\(\s*['\"]{re.escape(name)}['\"]", src)
    ]
    assert not missing, (
        f"desktop/src/stores/runStreamStore.ts is missing addEventListener for: {missing}. "
        "Add the listener or remove the corresponding backend emit + this entry."
    )


def test_no_aspirational_event_names_leaked_into_either_side() -> None:
    # spec §5.3 originally proposed `pipeline.start` / `step.start` /
    # `step.complete` / `step.failed` / `pipeline.complete` but the runtime
    # uses `run.*` + `step.started/completed/retry`. If both naming schemes
    # appear in the same file, a refactor went half-done — fail loudly.
    aspirational = (
        "pipeline.start",
        "step.start",
        "step.complete",
        "step.failed",
        "pipeline.complete",
    )
    for path in (BACKEND_SRC, FRONTEND_SRC):
        if not path.exists():
            continue
        src = path.read_text()
        # Only flag if the aspirational name appears inside a quoted event string,
        # not a comment / variable name.
        leaks = [name for name in aspirational if re.search(rf"['\"]{re.escape(name)}['\"]", src)]
        assert not leaks, (
            f"{path.relative_to(REPO_ROOT)} mixes aspirational and actual SSE "
            f"event names: {leaks}. Pick one set (currently the runtime uses "
            f"run.*/step.started family) and migrate fully."
        )
