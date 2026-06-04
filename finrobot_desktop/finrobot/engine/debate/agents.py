"""Bull / bear / judge agent factory for the IC debate pipeline (ADR-0007).

Each agent produces a strictly typed output and must never emit raw numbers.
Numbers are only accessible via evidence_id references resolved at render time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic_ai import Agent

from finrobot.config import FinRobotSettings
from finrobot.engine.debate.models import SideCase, Verdict
from finrobot.engine.deps import FinRobotDeps

_INSTRUCTIONS_DIR = Path(__file__).parent.parent / "agents" / "instructions"


def _load_instructions(role: str) -> str:
    path = _INSTRUCTIONS_DIR / f"{role}_agent.md"
    return path.read_text(encoding="utf-8")


def build_debate_agents(settings: FinRobotSettings) -> dict[str, Any]:
    """Create bull, bear, and judge agents for one IC debate session.

    Returns a dict mapping role name to a typed pydantic-ai Agent:
      "bull"  -> Agent[FinRobotDeps, SideCase]
      "bear"  -> Agent[FinRobotDeps, SideCase]
      "judge" -> Agent[FinRobotDeps, Verdict]

    The return annotation is dict[str, Any] because Python's type system
    cannot express a heterogeneous dict with differently-parameterised Agent
    generics in a way that mypy strict accepts without losing all local type
    safety.  Each Agent is constructed with a precise generic annotation
    (local variables below), and the typed contract is verified at test time
    via agent.output_type assertions.

    Each agent:
    - Loads its system instructions from agents/instructions/<role>_agent.md.
    - Runs on the single configured model (settings.model_name) — there are no
      per-role overrides.
    - Carries FinRobotDeps so pipeline code can pass deps at run-time.
    - Is constructed with defer_model_check=True so agent creation never
      triggers a live API call (tests don't need credentials).

    Red-line invariant: bull and bear output SideCase whose Argument fields
    contain no numeric data -- numbers are only reachable via evidence_id lookup.
    Judge outputs Verdict which also carries no raw numbers.
    """
    bull: Agent[FinRobotDeps, SideCase] = Agent(
        settings.create_model(),
        output_type=SideCase,
        deps_type=FinRobotDeps,
        instructions=_load_instructions("bull"),
        defer_model_check=True,
    )
    bear: Agent[FinRobotDeps, SideCase] = Agent(
        settings.create_model(),
        output_type=SideCase,
        deps_type=FinRobotDeps,
        instructions=_load_instructions("bear"),
        defer_model_check=True,
    )
    judge: Agent[FinRobotDeps, Verdict] = Agent(
        settings.create_model(),
        output_type=Verdict,
        deps_type=FinRobotDeps,
        instructions=_load_instructions("judge"),
        defer_model_check=True,
    )

    return {"bull": bull, "bear": bear, "judge": judge}
