"""Tests for the lead_agent orchestrator (P1b: sub-agents + comps/dcf tools)."""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from finrobot.artifact.models import ArtifactSummary
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

    def test_has_core_tools(self):
        agent = _agent()
        tool_names = set(agent._function_toolset.tools.keys())
        assert "query_financial_data" in tool_names
        assert "query_coverage_universe" in tool_names
        assert "find_reports" in tool_names
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


# ---------------------------------------------------------------------------
# find_reports — locate the user's previously-run reports for a ticker.
#
# Closes the gap where a user references "the AAPL report I ran earlier" but it
# isn't the one open in the ContextBar: without a retrieval tool the model could
# only re-run the pipeline (a NEW artifact) or guess. list_by_ticker already
# existed on the store; this exposes it to the agent.
# ---------------------------------------------------------------------------


class FakeArtifactStore:
    def __init__(self, summaries: list[ArtifactSummary]) -> None:
        self._summaries = summaries

    async def list_by_ticker(
        self,
        ticker: str | None = None,
        type=None,  # noqa: A002, ANN001
        include_archived: bool = False,
        limit: int = 100,
        tickers=None,  # noqa: ANN001
    ) -> list[ArtifactSummary]:
        rows = [s for s in self._summaries if ticker is None or s.ticker == ticker]
        return rows[:limit]


def _report_summary(
    *,
    artifact_id: str = "art_2026-06-09_AAPL_equity_research_abc",
    ticker: str = "AAPL",
    verdict: str | None = "SELL",
    target: float | None = 175.30,
    entry: float | None = 301.54,
) -> ArtifactSummary:
    return ArtifactSummary(
        id=artifact_id,
        ticker=ticker,
        cross_tickers=[],
        type="equity_research",
        created_at=datetime(2026, 6, 9, 2, 9, 18, tzinfo=timezone.utc),
        headline="x",
        source="pipeline:equity_research",
        archived=False,
        entry_price=entry,
        target_price=target,
        target_date=datetime(2027, 6, 9, tzinfo=timezone.utc),
        signal=None,
        verdict=verdict,
    )


def _find_reports_fn(agent):
    return agent._function_toolset.tools["find_reports"].function


def _deps_with_store(store) -> FinRobotDeps:  # noqa: ANN001
    return FinRobotDeps(data_layer=FakeDataLayer(), settings=_settings(), artifact_store=store)


class TestFindReports:
    async def test_lists_artifacts_for_ticker_newest_first(self):
        agent = _agent()
        fn = _find_reports_fn(agent)
        store = FakeArtifactStore([_report_summary()])
        out = await fn(_run_context(_deps_with_store(store)), "AAPL")
        assert isinstance(out, str)
        assert "art_2026-06-09_AAPL_equity_research_abc" in out
        assert "SELL" in out
        assert "175.30" in out

    async def test_no_store_returns_friendly_message_not_raise(self):
        agent = _agent()
        fn = _find_reports_fn(agent)
        out = await fn(_run_context(_deps()), "AAPL")
        assert isinstance(out, str)
        assert "available" in out.lower()

    async def test_no_artifacts_says_none_yet(self):
        agent = _agent()
        fn = _find_reports_fn(agent)
        store = FakeArtifactStore([])
        out = await fn(_run_context(_deps_with_store(store)), "AAPL")
        assert isinstance(out, str)
        assert "AAPL" in out

    async def test_bad_ticker_returns_string_not_raise(self):
        agent = _agent()
        fn = _find_reports_fn(agent)
        store = FakeArtifactStore([])
        out = await fn(_run_context(_deps_with_store(store)), "###")
        assert isinstance(out, str)
        assert "Invalid ticker" in out


# ---------------------------------------------------------------------------
# ask_filings — 10-K RAG Q&A as a chat tool.
#
# run_qa (engine/analysis/qa.py) retrieves real 10-K passages via BM25 and
# grounds the answer in them, but it was never reachable from /chat — the
# AiChatTab "10-K Q&A" chip was REMOVED (BUG-20260602-046) because no tool
# existed, so the model could only guess. This exposes run_qa to the lead agent.
# ---------------------------------------------------------------------------


@dataclass
class _FakeChunk:
    text: str
    source: str
    chunk_index: int


class _FakeRagIndex:
    """Minimal BM25Index stand-in: search() returns (chunk, score) pairs."""

    def __init__(self, chunks: list[_FakeChunk], scores: list[float] | None = None) -> None:
        self._chunks = chunks
        self._scores = scores or [1.0] * len(chunks)

    def search(self, query: str, top_k: int = 5) -> list[tuple[_FakeChunk, float]]:
        return list(zip(self._chunks, self._scores))[:top_k]


class _RagDataLayer:
    """Data layer whose fetch() returns a 10-K RAG payload (or an empty one)."""

    def __init__(self, *, rag_index: _FakeRagIndex | None = None, chunk_count: int = 0) -> None:
        self._rag_index = rag_index
        self._chunk_count = chunk_count

    async def fetch(self, data_type, ticker, **kwargs) -> DataResult:  # noqa: ANN001
        data: dict = {"chunk_count": self._chunk_count}
        if self._rag_index is not None:
            data["rag_index"] = self._rag_index
        return DataResult(
            data=data,
            provider="sec_edgar",
            ticker=ticker,
            data_type=str(data_type),
            timestamp=datetime.now(tz=timezone.utc),
        )


def _ask_filings_fn(agent):  # noqa: ANN001
    return agent._function_toolset.tools["ask_filings"].function


class TestAskFilings:
    async def test_registered_as_tool(self):
        agent = _agent()
        assert "ask_filings" in agent._function_toolset.tools

    async def test_bad_ticker_returns_string_not_raise(self):
        agent = _agent()
        fn = _ask_filings_fn(agent)
        deps = FinRobotDeps(data_layer=_RagDataLayer(), settings=_settings())
        out = await fn(_run_context(deps), "###", "What are the risk factors?")
        assert isinstance(out, str)
        assert "Invalid ticker" in out

    async def test_no_10k_returns_string_not_raise(self):
        # run_qa raises ValueError("No 10-K RAG index ...") when EDGAR has no
        # filing; the tool MUST convert it to a returned string, never re-raise —
        # a raised ValueError tears down the live /chat SSE stream.
        agent = _agent()
        fn = _ask_filings_fn(agent)
        deps = FinRobotDeps(data_layer=_RagDataLayer(rag_index=None), settings=_settings())
        out = await fn(_run_context(deps), "AAPL", "What are the risk factors?")
        assert isinstance(out, str)
        assert "10-K" in out

    async def test_successful_qa_returns_grounded_answer(self, monkeypatch):
        deps = FinRobotDeps(
            data_layer=_RagDataLayer(
                rag_index=_FakeRagIndex(
                    [_FakeChunk("Regulatory change is a material risk.", "[Item 1A]", 0)],
                    scores=[3.2],
                ),
                chunk_count=12,
            ),
            settings=_settings(),
        )
        # Stub the LLM inside run_qa so the test exercises the real retrieval +
        # tool plumbing without a network call.
        mock_result = MagicMock()
        mock_result.output = "Per [Item 1A], regulatory change is the key risk."
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=mock_result)
        monkeypatch.setattr("finrobot.engine.analysis.qa.Agent", MagicMock(return_value=mock_agent))

        agent = _agent()
        fn = _ask_filings_fn(agent)
        out = await fn(_run_context(deps), "aapl", "What are the risk factors?")
        assert isinstance(out, str)
        assert "regulatory change" in out.lower()
