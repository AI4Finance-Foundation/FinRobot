"""FinRobot — financial AI agent platform with code-enforced analysis pipelines."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from finrobot.engine.pipelines.base import PipelineResult
    from finrobot.sdk import FinRobot

__all__ = ["FinRobot", "PipelineResult"]
__version__ = "0.1.0"


def __getattr__(name: str) -> object:
    # Lazy re-exports (PEP 562). Importing `finrobot` — which happens on *any*
    # `import finrobot.<submodule>`, since Python runs this package __init__ —
    # must NOT eagerly drag in the heavy engine: `PipelineResult` pulls
    # pydantic_ai (~0.45s) via pipelines, `FinRobot` pulls edgartools (~0.46s)
    # via sdk→deps→data.layer. Those ~0.9s gated /health and the artifacts
    # SQLite routes behind the full analytical stack on every sidecar cold
    # start. Resolve these names only when actually accessed.
    if name == "FinRobot":
        from finrobot.sdk import FinRobot

        return FinRobot
    if name == "PipelineResult":
        from finrobot.engine.pipelines.base import PipelineResult

        return PipelineResult
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
