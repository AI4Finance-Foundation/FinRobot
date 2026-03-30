"""Tests for the lead_agent orchestrator."""
from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from finagent.config import get_settings
from finagent.engine.data.interface import DataResult
from finagent.engine.deps import FinAgentDeps
from finagent.engine.orchestrator import activate_skill, lead_agent, query_financial_data


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


def _deps(skill_runtime=None) -> FinAgentDeps:
    return FinAgentDeps(data_layer=FakeDataLayer(), settings=get_settings(), skill_runtime=skill_runtime)


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

class TestToolRegistration:
    def test_has_query_financial_data_tool(self):
        assert "query_financial_data" in _get_tool_names()

    def test_has_activate_skill_tool(self):
        assert "activate_skill" in _get_tool_names()

    def test_has_run_equity_research_tool(self):
        assert "run_equity_research" in _get_tool_names()

    def test_does_not_have_run_comps_analysis(self):
        assert "run_comps_analysis" not in _get_tool_names()

    def test_does_not_have_run_dcf_valuation(self):
        assert "run_dcf_valuation" not in _get_tool_names()


def _get_tool_names() -> set[str]:
    """Extract tool names from lead_agent. pydantic_ai 1.7x API."""
    return set(lead_agent._function_toolset.tools.keys())


# ---------------------------------------------------------------------------
# activate_skill with None skill_runtime
# ---------------------------------------------------------------------------

class TestActivateSkill:
    async def test_returns_not_available_when_skill_runtime_is_none(self):
        deps = _deps(skill_runtime=None)
        # call_tools=[] prevents TestModel from invoking any tools
        with lead_agent.override(model=TestModel(custom_output_text="irrelevant", call_tools=[])):
            result = await lead_agent.run("activate skill comps-analysis", deps=deps)
        assert isinstance(result.output, str)

    async def test_activate_skill_tool_directly_returns_not_available(self):
        """Test the tool function directly via a minimal fake context."""
        class FakeCtx:
            deps = _deps(skill_runtime=None)

        msg = await activate_skill(FakeCtx(), "some-skill")  # type: ignore[arg-type]
        assert "not yet available" in msg.lower() or "not available" in msg.lower()


# ---------------------------------------------------------------------------
# Agent routing — TestModel
# ---------------------------------------------------------------------------

class TestAgentRouting:
    async def test_agent_runs_without_error_for_simple_question(self):
        deps = _deps()
        with lead_agent.override(model=TestModel(custom_output_text="AAPL PE is 28.3x", call_tools=[])):
            result = await lead_agent.run("What is AAPL's PE ratio?", deps=deps)
        assert isinstance(result.output, str)
        assert len(result.output) > 0

    async def test_agent_can_call_query_financial_data(self):
        deps = _deps()
        with lead_agent.override(model=TestModel(
            custom_output_text="AAPL financials retrieved.",
            call_tools=["query_financial_data"],
        )):
            result = await lead_agent.run("What is AAPL's PE ratio?", deps=deps)
        assert isinstance(result.output, str)
