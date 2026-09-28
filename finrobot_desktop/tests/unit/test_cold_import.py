"""Cold-start import guard for the sidecar.

``finrobot serve`` imports ``finrobot.server`` (the FastAPI app) BEFORE uvicorn
binds the port, and uvicorn only starts accepting connections after the lifespan
*startup* completes. So every millisecond spent importing the heavy analytical
stack at module-load time is a millisecond ``/health`` and the local-SQLite
artifact/dashboard reads are unreachable on every app launch.

None of these heavy libs are needed to answer ``/health`` or to read a saved
report from local SQLite. They are pulled lazily — at the lifespan warmup task
that constructs the data layer / agents, or inside the handlers that actually
use them. This test is the mechanical gate that keeps them off the cold-start
import path: a regression (a new module-level ``import`` of any of these reachable
from ``finrobot.server``) silently re-slows every launch, so it fails loudly here.

See docs handoff『sidecar 冷启动根治』.
"""

from __future__ import annotations

import subprocess
import sys

# Heavy libs that dominate the sidecar cold start. edgar (~0.46s) + the
# pydantic_ai ecosystem (pydantic_ai / mcp / fastmcp / beartype / griffe /
# logfire / opentelemetry, ~0.45s together) are the two big stones; pandas /
# matplotlib / yfinance ride in with them. numpy is deliberately NOT forbidden:
# the /api/compute/monte-carlo route needs MonteCarloRequest/Result as real
# Pydantic models at route-registration time, which pulls numpy (~40ms);
# splitting the operator module to defer that is not worth the churn.
_FORBIDDEN = ("edgar", "pydantic_ai", "yfinance", "matplotlib", "pandas")


def test_importing_server_does_not_load_heavy_stack() -> None:
    probe = (
        "import sys\n"
        "import finrobot.server  # noqa: F401\n"
        f"forbidden = {_FORBIDDEN!r}\n"
        "leaked = sorted(m for m in forbidden if m in sys.modules)\n"
        "print(','.join(leaked))\n"
        "sys.exit(1 if leaked else 0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=180,
    )
    leaked = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    assert result.returncode == 0, (
        "Importing finrobot.server pulled heavy modules onto the sidecar "
        f"cold-start path: [{leaked}]. Move the offending module-level import "
        "into the handler / lifespan warmup that actually uses it.\n"
        f"stderr:\n{result.stderr}"
    )
