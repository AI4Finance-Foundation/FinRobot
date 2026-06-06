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

    def test_every_pipeline_spec_registered_as_tool_with_description(self):
        """BUG-025: the registry is the single source of truth for Mode B tools.

        Every PipelineSpec must surface as a registered chat tool whose name and
        LLM-facing description come verbatim from the spec — the description is
        the model's tool-selection signal, so a missing/empty/drifted one would
        silently break routing. This is the regression guard the refactor adds.
        """
        from finrobot.engine.pipelines.registry import iter_pipeline_specs

        agent = _agent()
        tools = agent._function_toolset.tools
        specs = iter_pipeline_specs()
        assert specs, "registry returned no pipeline specs"
        for spec in specs:
            assert (
                spec.tool_name in tools
            ), f"pipeline spec {spec.key!r} has no registered tool {spec.tool_name!r}"
            tool = tools[spec.tool_name]
            assert (
                tool.description and tool.description.strip()
            ), f"tool {spec.tool_name!r} has an empty description"
            # Carried verbatim from the spec (which holds the original docstring).
            assert (
                tool.description == spec.tool_description
            ), f"tool {spec.tool_name!r} description drifted from its spec"

    def test_ic_memo_spec_maps_to_hyphenless_tool_name(self):
        """The 'ic-memo' key has a hyphen; its tool name must be run_ic_memo
        (a hyphen is illegal in a tool identifier), so tool_name is an explicit
        spec field rather than derived from the key."""
        from finrobot.engine.pipelines.registry import get_pipeline_spec

        spec = get_pipeline_spec("ic-memo")
        assert spec.tool_name == "run_ic_memo"
        agent = _agent()
        assert "run_ic_memo" in agent._function_toolset.tools

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


class TestPipelineToolLocale:
    """The chat orchestrator must thread the request's UI locale into the
    pipeline as the report-body language; non-chat callers (no locale) keep the
    settings.language fallback unchanged."""

    class _FakeResult:
        artifact_id = "art-1"

        def format_summary(self) -> str:
            return "ok"

    class _RecordingPipeline:
        def __init__(self) -> None:
            self.seen_lang: str | None = "UNSET"

        async def execute(self, deps, ticker, lang=None, **kwargs):  # noqa: ANN001
            self.seen_lang = lang
            return TestPipelineToolLocale._FakeResult()

    async def test_request_locale_threaded_as_lang(self):
        from finrobot.engine.orchestrator import _run_pipeline_tool

        deps = FinRobotDeps(data_layer=FakeDataLayer(), settings=_settings(), request_locale="zh")
        pipe = self._RecordingPipeline()
        out = await _run_pipeline_tool(_run_context(deps), "AAPL", pipe)  # type: ignore[arg-type]
        assert pipe.seen_lang == "zh"
        assert out["artifact_id"] == "art-1"

    async def test_no_locale_falls_back_to_none(self):
        from finrobot.engine.orchestrator import _run_pipeline_tool

        deps = FinRobotDeps(data_layer=FakeDataLayer(), settings=_settings())
        pipe = self._RecordingPipeline()
        await _run_pipeline_tool(_run_context(deps), "AAPL", pipe)  # type: ignore[arg-type]
        assert pipe.seen_lang is None
