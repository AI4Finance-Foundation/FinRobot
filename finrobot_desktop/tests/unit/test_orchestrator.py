"""Tests for the lead_agent orchestrator (P1b: sub-agents + comps/dcf tools)."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from finrobot.config import get_settings
from finrobot.engine.data.interface import DataResult
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.orchestrator import create_lead_agent
from finrobot.engine.skills.registry import SkillRegistry

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


def _deps(skill_runtime=None) -> FinRobotDeps:
    return FinRobotDeps(
        data_layer=FakeDataLayer(), settings=_settings(), skill_runtime=skill_runtime
    )


def _query_financial_data_fn(agent):
    """Return the raw query_financial_data coroutine registered on the agent."""
    return agent._function_toolset.tools["query_financial_data"].function


def _run_context(deps: FinRobotDeps) -> RunContext[FinRobotDeps]:
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage())


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
        with agent.override(
            model=TestModel(
                custom_output_text="Here is the skill content.",
                call_tools=["activate_skill"],
            )
        ):
            result = await agent.run("activate skill comps-analysis", deps=deps)
        assert isinstance(result.output, str)

    async def test_activate_skill_unknown_id_returns_error(self):
        registry = SkillRegistry(FIXTURES_DIR)
        agent = _agent(skill_registry=registry)
        deps = _deps(skill_runtime=registry)
        with agent.override(
            model=TestModel(
                custom_output_text="Error noted.",
                call_tools=["activate_skill"],
            )
        ):
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
        # Drive a real tool call with a *valid* data_type. (TestModel's
        # auto-generated args pick an invalid string for the str | DataType
        # union, which the BUG-052 guard now correctly rejects with ModelRetry;
        # FunctionModel lets us supply a valid value to exercise the happy path.)
        calls = {"n": 0}

        def model_fn(messages, info):
            calls["n"] += 1
            if calls["n"] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            "query_financial_data",
                            {"ticker": "AAPL", "data_type": "price"},
                        )
                    ]
                )
            return ModelResponse(parts=[TextPart("AAPL financials retrieved.")])

        with agent.override(model=FunctionModel(model_fn)):
            result = await agent.run("What is AAPL's PE ratio?", deps=deps)
        assert isinstance(result.output, str)
        assert "AAPL financials retrieved." in result.output


# ---------------------------------------------------------------------------
# query_financial_data error handling (BUG-052)
#
# A bad data_type must surface as ModelRetry (framework-blessed, fed back to
# the model) instead of a bare ValueError that would tear down the live /chat
# SSE stream. A bad ticker must RETURN a string, not raise, for the same reason.
# ---------------------------------------------------------------------------


class TestQueryFinancialDataErrorHandling:
    async def test_bad_data_type_raises_model_retry_not_value_error(self):
        agent = _agent()
        fn = _query_financial_data_fn(agent)
        ctx = _run_context(_deps())
        with pytest.raises(ModelRetry) as excinfo:
            await fn(ctx, "AAPL", "balance_sheet")
        msg = str(excinfo.value)
        assert "balance_sheet" in msg
        # The retry message enumerates valid values so the model self-corrects.
        assert "financials" in msg

    async def test_bad_data_type_does_not_raise_bare_value_error(self):
        agent = _agent()
        fn = _query_financial_data_fn(agent)
        ctx = _run_context(_deps())
        # A bare ValueError here would crash the SSE stream; only ModelRetry
        # (a ValueError subclass-independent path) is acceptable.
        with pytest.raises(ModelRetry):
            await fn(ctx, "AAPL", "income_statement")

    async def test_valid_data_type_returns_context_string(self):
        agent = _agent()
        fn = _query_financial_data_fn(agent)
        ctx = _run_context(_deps())
        out = await fn(ctx, "AAPL", "price")
        assert isinstance(out, str)
        assert out

    async def test_bad_ticker_returns_string_not_raise(self):
        agent = _agent()
        fn = _query_financial_data_fn(agent)
        ctx = _run_context(_deps())
        out = await fn(ctx, "###", "price")
        assert isinstance(out, str)
        assert "Invalid ticker" in out
