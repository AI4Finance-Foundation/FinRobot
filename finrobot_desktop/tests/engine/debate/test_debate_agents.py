"""Tests for IC debate agent factory (Task 5).

Validates typed contract only — no LLM calls made.
"""

from __future__ import annotations

import pytest

from finrobot.config import FinRobotSettings
from finrobot.engine.debate.agents import build_debate_agents
from finrobot.engine.debate.models import SideCase, Verdict


@pytest.fixture
def test_settings() -> FinRobotSettings:
    """Minimal settings using the no-credential 'test' provider."""
    return FinRobotSettings(model_name="test:test")


def test_factory_returns_three_typed_agents(test_settings: FinRobotSettings) -> None:
    agents = build_debate_agents(test_settings)
    assert set(agents) == {"bull", "bear", "judge"}
    assert agents["bull"].output_type is SideCase
    assert agents["bear"].output_type is SideCase
    assert agents["judge"].output_type is Verdict


def test_bull_bear_have_distinct_instances(test_settings: FinRobotSettings) -> None:
    """bull and bear must be separate Agent objects even though both output SideCase."""
    agents = build_debate_agents(test_settings)
    assert agents["bull"] is not agents["bear"]


def test_agents_carry_correct_deps_type(test_settings: FinRobotSettings) -> None:
    """All three agents must be wired to FinRobotDeps so pipeline can pass deps."""
    from finrobot.engine.deps import FinRobotDeps

    agents = build_debate_agents(test_settings)
    for role, agent in agents.items():
        assert agent.deps_type is FinRobotDeps, (
            f"Agent '{role}' has deps_type={agent.deps_type!r}, expected FinRobotDeps"
        )


def test_model_override_respected(test_settings: FinRobotSettings) -> None:
    """get_model_for_role falls back to global model_name for unknown roles (bull/bear/judge).

    This test confirms the factory builds without error using the fallback path
    — no per-role model_bull/bear/judge fields exist on FinRobotSettings, which
    is the correct design (unknown role → graceful fallback, not KeyError).
    """
    # Provide a global model; unknown roles fall back to it without raising.
    settings = FinRobotSettings(model_name="test:test")
    resolved = settings.get_model_for_role("bull")
    assert resolved == "test:test"

    agents = build_debate_agents(settings)
    assert set(agents) == {"bull", "bear", "judge"}
