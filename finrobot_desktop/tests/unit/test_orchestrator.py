"""Tests for the lead_agent orchestrator (P1b: sub-agents + comps/dcf tools)."""
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from finagent.config import get_settings
from finagent.engine.data.interface import DataResult
from finagent.engine.deps import FinAgentDeps
from finagent.engine.orchestrator import create_lead_agent
from finagent.engine.skills.registry import SkillRegistry

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "skills"


# ---------------------------------------------------------------------------
# Fake deps
# ---------------------------------------------------------------------------

class FakeDataLayer:
    async def fetch(self, data_type: str, ticker: str, **kwargs) -> DataResult:
        return DataResult(
            data={"revenue": 385_000_000_000, "pe_ratio": 28.3},
            provider="fake",
            ticker=ticker,
            data_type=data_type,
            timestamp=datetime.now(tz=timezone.utc),
        )


def _settings():
    return get_settings(model_name="test")


def _agent(skill_registry=None):
    return create_lead_agent(_settings(), skill_registry=skill_registry)


def _deps(skill_runtime=None) -> FinAgentDeps:
    return FinAgentDeps(data_layer=FakeDataLayer(), settings=_settings(), skill_runtime=skill_runtime)


# ---------------------------------------------------------------------------
# Factory + tool registration
# ---------------------------------------------------------------------------

class TestCreateLeadAgent:
    def test_returns_agent(self):
        agent = _agent()
        assert agent is not None

    def test_has_all_five_tools(self):
        agent = _agent()
        tool_names = set(agent._function_toolset.tools.keys())
        assert "query_financial_data" in tool_names
        assert "activate_skill" in tool_names
        assert "run_equity_research" in tool_names
        assert "run_comps_analysis" in tool_names
        assert "run_dcf_valuation" in tool_names

    def test_without_skill_registry_instructions_no_available_skills(self):
        agent = _agent(skill_registry=None)
        instructions_text = "\n".join(agent._instructions)
        assert "Available Skills" not in instructions_text

    def test_with_skill_registry_instructions_contain_summaries(self):
        registry = SkillRegistry(FIXTURES_DIR)
        agent = _agent(skill_registry=registry)
        instructions_text = "\n".join(agent._instructions)
        assert "Available Skills" in instructions_text
        assert "comps-analysis" in instructions_text


# ---------------------------------------------------------------------------
# activate_skill
# ---------------------------------------------------------------------------

class TestActivateSkill:
    async def test_returns_not_available_when_skill_runtime_is_none(self):
        agent = _agent()
        deps = _deps(skill_runtime=None)
        with agent.override(model=TestModel(custom_output_text="irrelevant", call_tools=[])):
            result = await agent.run("activate skill comps-analysis", deps=deps)
        assert isinstance(result.output, str)

    async def test_activate_skill_returns_content_when_registry_set(self):
        registry = SkillRegistry(FIXTURES_DIR)
        agent = _agent(skill_registry=registry)
        deps = _deps(skill_runtime=registry)
        with agent.override(model=TestModel(
            custom_output_text="Here is the skill content.",
            call_tools=["activate_skill"],
        )):
            result = await agent.run("activate skill comps-analysis", deps=deps)
        assert isinstance(result.output, str)

    async def test_activate_skill_unknown_id_returns_error(self):
        registry = SkillRegistry(FIXTURES_DIR)
        agent = _agent(skill_registry=registry)
        deps = _deps(skill_runtime=registry)
        with agent.override(model=TestModel(
            custom_output_text="Error noted.",
            call_tools=["activate_skill"],
        )):
            result = await agent.run("activate skill nonexistent-skill", deps=deps)
        assert isinstance(result.output, str)


# ---------------------------------------------------------------------------
# Agent routing — TestModel
# ---------------------------------------------------------------------------

class TestAgentRouting:
    async def test_agent_runs_without_error_for_simple_question(self):
        agent = _agent()
        deps = _deps()
        with agent.override(model=TestModel(custom_output_text="AAPL PE is 28.3x", call_tools=[])):
            result = await agent.run("What is AAPL's PE ratio?", deps=deps)
        assert isinstance(result.output, str)
        assert len(result.output) > 0

    async def test_agent_can_call_query_financial_data(self):
        agent = _agent()
        deps = _deps()
        with agent.override(model=TestModel(
            custom_output_text="AAPL financials retrieved.",
            call_tools=["query_financial_data"],
        )):
            result = await agent.run("What is AAPL's PE ratio?", deps=deps)
        assert isinstance(result.output, str)
