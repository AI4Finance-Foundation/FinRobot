"""Tests for the lead_agent orchestrator (P1b: sub-agents + comps/dcf tools)."""

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
from finrobot.artifact.semantic_diff import (
    Attribution,
    AttributionItem,
    DataFootnote,
    DeltaItem,
    SemanticDelta,
)
from finrobot.config import get_settings
from finrobot.engine.backtest.engine import BacktestResult
from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.types import DataType
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.models.financial import DCFInputs
from finrobot.engine.orchestrator import create_lead_agent
from finrobot.engine.skills.registry import SkillRegistry
from tests.unit.test_pipeline_methodology import INTERACTIVE_CHECKPOINT_PHRASES

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "skills"
# The repo's real skills tree — used to exercise activate_skill against an actual
# interactive Claude-Code skill (the fixtures are inert stubs).
REAL_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"


# ---------------------------------------------------------------------------
# Fake deps
# ---------------------------------------------------------------------------


class FakeCanonical:
    """Stub for the normalized canonical contract objects."""

    def model_dump_json(self, indent: int | None = None) -> str:
        return '{"current_price": 123.45}'


class FakeDataLayer:
    async def fetch(self, data_type: str, ticker: str, **kwargs) -> DataResult:
        return DataResult(
            data={"revenue": 385_000_000_000, "pe_ratio": 28.3},
            provider="fake",
            ticker=ticker,
            data_type=data_type,
            timestamp=datetime.now(tz=timezone.utc),
        )

    async def fetch_canonical(self, data_type, ticker: str, **kwargs) -> FakeCanonical:
        return FakeCanonical()


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


def _activate_skill_fn(agent):
    """Return the raw activate_skill coroutine registered on the agent."""
    return agent._function_toolset.tools["activate_skill"].function


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
            assert spec.tool_name in tools, (
                f"pipeline spec {spec.key!r} has no registered tool {spec.tool_name!r}"
            )
            tool = tools[spec.tool_name]
            assert tool.description and tool.description.strip(), (
                f"tool {spec.tool_name!r} has an empty description"
            )
            # Carried verbatim from the spec (which holds the original docstring).
            assert tool.description == spec.tool_description, (
                f"tool {spec.tool_name!r} description drifted from its spec"
            )

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

    async def test_activate_skill_returns_pipeline_safe_rendering(self):
        """activate_skill (Mode A) must return the pipeline-safe methodology, not
        the raw SKILL.md body — symmetric with Mode B's _resolve_step_methodology.

        For a whitelisted skill the tool returns the distilled '### {id}: {name}'
        block, never the original body. The fixture 'test-skill' is unknown, so it
        falls back to its body but still carries the rendered header — confirming
        the call routes through render_pipeline_methodology rather than full_content.
        """
        registry = SkillRegistry(FIXTURES_DIR)
        agent = _agent(skill_registry=registry)
        deps = _deps(skill_runtime=registry)
        activate_skill = _activate_skill_fn(agent)

        result = await activate_skill(_run_context(deps), "test-skill")

        assert result.startswith("### test-skill: Test Skill")

    async def test_activate_skill_interactive_skill_is_checkpoint_free(self):
        """A known-interactive real skill (strip-profile: 'STOP and wait for
        explicit user approval', 'one slide at a time') must come back through
        activate_skill stripped of every checkpoint directive."""
        if not REAL_SKILLS_DIR.is_dir():
            pytest.skip("real skills tree not present")
        registry = SkillRegistry(REAL_SKILLS_DIR)
        assert registry.get("strip-profile") is not None, "expected interactive skill missing"
        agent = _agent(skill_registry=registry)
        deps = _deps(skill_runtime=registry)
        activate_skill = _activate_skill_fn(agent)

        rendered = (await activate_skill(_run_context(deps), "strip-profile")).lower()

        assert "pipeline-safe company strip-profile framework" in rendered
        leaked = [p for p in INTERACTIVE_CHECKPOINT_PHRASES if p in rendered]
        assert not leaked, f"activate_skill leaked checkpoint phrases: {leaked}"

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


class TestQueryFinancialDataCanonicalRouting:
    """Mode A twin of the sub-agent contract (agents/factory.py): PRICE /
    FINANCIALS must route through fetch_canonical so chat narrates the SAME
    validated quote the pipeline's structured fields use — bare fetch() was a
    second, un-validated price source (the orchestrator was the unsynced
    sibling of the 2026-06-09 TSLA two-prices fix)."""

    async def test_price_routes_through_canonical(self):
        agent = _agent()
        fn = _query_financial_data_fn(agent)
        ctx = _run_context(_deps())
        ctx.deps.data_layer = MagicMock()
        normalized = MagicMock(spec_set=["model_dump_json"])
        normalized.model_dump_json.return_value = '{"current_price": 408.95}'
        ctx.deps.data_layer.fetch_canonical = AsyncMock(return_value=normalized)
        ctx.deps.data_layer.fetch = AsyncMock()

        out = await fn(ctx, "TSLA", "price")

        ctx.deps.data_layer.fetch_canonical.assert_awaited_once_with(DataType.PRICE, "TSLA")
        ctx.deps.data_layer.fetch.assert_not_awaited()
        assert "canonical" in out and "408.95" in out

    async def test_financials_route_through_canonical_and_news_stays_raw(self):
        agent = _agent()
        fn = _query_financial_data_fn(agent)
        ctx = _run_context(_deps())
        ctx.deps.data_layer = MagicMock()
        normalized = MagicMock(spec_set=["model_dump_json"])
        normalized.model_dump_json.return_value = '{"revenue": 1}'
        ctx.deps.data_layer.fetch_canonical = AsyncMock(return_value=normalized)
        ctx.deps.data_layer.fetch = AsyncMock(
            return_value=MagicMock(to_context_string=lambda: "news text")
        )

        out_fin = await fn(ctx, "TSLA", "financials")
        ctx.deps.data_layer.fetch_canonical.assert_awaited_once_with(DataType.FINANCIALS, "TSLA")
        assert "canonical" in out_fin

        out_news = await fn(ctx, "TSLA", "news")
        ctx.deps.data_layer.fetch.assert_awaited_once_with(DataType.NEWS, "TSLA")
        assert out_news == "news text"


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


def _rag_chunk(text: str, source: str, chunk_index: int = 0) -> dict:
    """A serialized Chunk, exactly as the EDGAR provider now stores it."""
    return {"text": text, "source": source, "chunk_index": chunk_index, "char_start": 0}


class _RagDataLayer:
    """Data layer whose fetch() returns a 10-K RAG payload (serializable chunks).

    Mirrors the post-fix provider shape: ``rag_chunks`` (dicts), never a live
    BM25Index — run_qa rebuilds the index, so the payload stays cache-safe.
    """

    def __init__(self, *, rag_chunks: list[dict] | None = None) -> None:
        self._rag_chunks = rag_chunks

    async def fetch(self, data_type, ticker, **kwargs) -> DataResult:  # noqa: ANN001
        data: dict = {}
        if self._rag_chunks is not None:
            data["rag_chunks"] = self._rag_chunks
            data["chunk_count"] = len(self._rag_chunks)
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
        # run_qa raises ValueError("No 10-K RAG data ...") when EDGAR has no
        # filing; the tool MUST convert it to a returned string, never re-raise —
        # a raised ValueError tears down the live /chat SSE stream.
        agent = _agent()
        fn = _ask_filings_fn(agent)
        deps = FinRobotDeps(data_layer=_RagDataLayer(rag_chunks=None), settings=_settings())
        out = await fn(_run_context(deps), "AAPL", "What are the risk factors?")
        assert isinstance(out, str)
        assert "10-K" in out

    async def test_successful_qa_returns_grounded_answer(self, monkeypatch):
        # A realistic multi-chunk corpus so BM25 IDF gives the "regulatory" term
        # positive weight (a 1-2 doc corpus is degenerate — IDF ≤ 0).
        deps = FinRobotDeps(
            data_layer=_RagDataLayer(
                rag_chunks=[
                    _rag_chunk(
                        "Regulatory change is a material risk to operations.", "[Item 1A]", 0
                    ),
                    _rag_chunk("Revenue grew on services strength.", "[Item 7 - MD&A]", 1),
                    _rag_chunk("The company designs and sells consumer hardware.", "[Item 1]", 2),
                    _rag_chunk("Gross margin expanded on product mix.", "[Item 7]", 3),
                ]
            ),
            settings=_settings(),
        )
        # Stub the LLM inside run_qa so the test exercises the real retrieval +
        # tool plumbing (real BM25 rebuild) without a network call.
        mock_result = MagicMock()
        mock_result.output = "Per [Item 1A], regulatory change is the key risk."
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=mock_result)
        monkeypatch.setattr("finrobot.engine.analysis.qa.Agent", MagicMock(return_value=mock_agent))

        agent = _agent()
        fn = _ask_filings_fn(agent)
        out = await fn(_run_context(deps), "aapl", "What are the regulatory risk factors?")
        assert isinstance(out, str)
        assert "regulatory change" in out.lower()


# ---------------------------------------------------------------------------
# diff_reports — semantic version diff as a chat tool.
#
# build_semantic_delta (artifact/semantic_diff.py) turns two artifacts into a
# decision-oriented delta with deterministic single-factor attribution, but it
# was never a /chat tool — the AiChatTab "diff" chip was REMOVED
# (BUG-20260602-046) because the agent could not run it. This exposes it so the
# user can ask "what changed between my two AAPL reports / why did the target
# move" and get the real attribution rather than a guess.
# ---------------------------------------------------------------------------


class _ArtifactGetStore:
    """ArtifactStore stub exposing only get(id) -> Artifact | None."""

    def __init__(self, artifacts: dict[str, object]) -> None:
        self._artifacts = artifacts

    async def get(self, artifact_id: str):  # noqa: ANN201
        return self._artifacts.get(artifact_id)


def _diff_reports_fn(agent):  # noqa: ANN001
    return agent._function_toolset.tools["diff_reports"].function


def _semantic_delta(*, identical: bool = False) -> SemanticDelta:
    return SemanticDelta(
        a_id="art_a",
        b_id="art_b",
        a_label="dcf · 2026-05-01 10:00",
        b_label="dcf · 2026-06-01 10:00",
        report_type="dcf",
        identical=identical,
        conclusion=[
            DeltaItem(
                key="target_price",
                label_zh="目标价",
                label_en="Target price",
                old_value=175.3,
                new_value=198.0,
                formatted_old="$175.30",
                formatted_new="$198.00",
                pct_change=0.129,
                formatted_pct_change="+12.9%",
                direction="up",
                sentiment="positive",
            ),
        ],
        attribution=Attribution(
            available=True,
            items=[
                AttributionItem(
                    driver_key="wacc",
                    label_zh="WACC",
                    label_en="WACC",
                    contribution=15.0,
                    formatted_contribution="+$15.00",
                )
            ],
            total_change=22.7,
            formatted_total="+$22.70",
            residual=2.7,
            formatted_residual="+$2.70",
            summary_en="Fair value moved +$22.70, driven by WACC (+$15.00); "
            "the remaining +$2.70 is interaction terms and data re-basing.",
            summary_zh="公允价值变化 +$22.70。",
        ),
        drivers=[
            DeltaItem(
                key="wacc",
                label_zh="WACC",
                label_en="WACC",
                old_value=0.092,
                new_value=0.085,
                formatted_old="9.2%",
                formatted_new="8.5%",
                direction="down",
                sentiment="positive",
            ),
        ],
        comparability=[],
        data_footnote=DataFootnote(
            a_source="fmp",
            b_source="fmp",
            a_fetched_at="2026-05-01T10:00:00+00:00",
            b_fetched_at="2026-06-01T10:00:00+00:00",
            currency="USD",
            currency_assumed=False,
        ),
    )


class TestFormatDeltaForTool:
    def test_renders_conclusion_drivers_and_attribution(self):
        from finrobot.engine.orchestrator import _format_delta_for_tool

        out = _format_delta_for_tool(_semantic_delta())
        assert "Target price" in out
        assert "$175.30" in out
        assert "$198.00" in out
        assert "+12.9%" in out
        assert "WACC" in out
        assert "9.2%" in out and "8.5%" in out
        # The deterministic attribution summary must be surfaced verbatim.
        assert "Fair value moved +$22.70" in out

    def test_identical_versions_say_no_change(self):
        from finrobot.engine.orchestrator import _format_delta_for_tool

        out = _format_delta_for_tool(_semantic_delta(identical=True))
        assert "identical" in out.lower()


class TestDiffReports:
    async def test_registered_as_tool(self):
        agent = _agent()
        assert "diff_reports" in agent._function_toolset.tools

    async def test_no_store_returns_friendly_message_not_raise(self):
        agent = _agent()
        fn = _diff_reports_fn(agent)
        out = await fn(_run_context(_deps()), "art_a", "art_b")
        assert isinstance(out, str)
        assert "available" in out.lower()

    async def test_missing_artifact_returns_message_not_raise(self):
        agent = _agent()
        fn = _diff_reports_fn(agent)
        store = _ArtifactGetStore({"art_a": object()})  # art_b absent
        deps = FinRobotDeps(data_layer=FakeDataLayer(), settings=_settings(), artifact_store=store)
        out = await fn(_run_context(deps), "art_a", "art_b")
        assert isinstance(out, str)
        assert "art_b" in out
        assert "not found" in out.lower()

    async def test_both_present_runs_diff_and_formats(self, monkeypatch):
        store = _ArtifactGetStore({"art_a": object(), "art_b": object()})
        deps = FinRobotDeps(data_layer=FakeDataLayer(), settings=_settings(), artifact_store=store)
        monkeypatch.setattr(
            "finrobot.engine.orchestrator.build_semantic_delta",
            lambda a, b: _semantic_delta(),
        )
        agent = _agent()
        fn = _diff_reports_fn(agent)
        out = await fn(_run_context(deps), "art_a", "art_b")
        assert isinstance(out, str)
        assert "Fair value moved +$22.70" in out
        assert "Target price" in out


# ---------------------------------------------------------------------------
# run_monte_carlo — Monte Carlo DCF fair-value distribution as a chat tool.
#
# run_monte_carlo (compute/operators/monte_carlo.py) runs thousands of
# randomized DCF valuations into a price distribution, but it was never a /chat
# tool — the AiChatTab "Monte Carlo" chip was REMOVED (BUG-20260602-046). This
# wires it via the shared seed_dcf_inputs_for_ticker coordinator (the same path
# the REST /compute/dcf-seed endpoint uses) so the model can answer "run a monte
# carlo on AAPL / how uncertain is the fair value".
# ---------------------------------------------------------------------------


def _mc_inputs() -> DCFInputs:
    # Mirrors tests/unit/test_monte_carlo.py::_inputs — a converging AAPL-shaped
    # assumption set so the real operator runs (this exercises genuine MC math,
    # only the data-fetch boundary is stubbed).
    return DCFInputs(
        revenue_base=400_000_000_000.0,
        revenue_growth_rates=[0.06, 0.05, 0.04, 0.04, 0.03],
        ebitda_margin=0.30,
        capex_pct_revenue=0.06,
        nwc_pct_revenue=0.02,
        da_pct_revenue=0.05,
        tax_rate=0.21,
        risk_free_rate=0.04,
        beta=1.2,
        equity_risk_premium=0.05,
        cost_of_debt=0.04,
        debt_ratio=0.25,
        terminal_growth_rate=0.025,
        shares_outstanding=15_500_000_000.0,
        net_debt=60_000_000_000.0,
    )


class _PriceOnlyFinancials:
    """Stub standing in for FinancialData — the tool reads only .market.current_price."""

    class _Market:
        current_price = 160.0

    market = _Market()


def _run_monte_carlo_fn(agent):  # noqa: ANN001
    return agent._function_toolset.tools["run_monte_carlo"].function


class TestRunMonteCarlo:
    async def test_registered_as_tool(self):
        agent = _agent()
        assert "run_monte_carlo" in agent._function_toolset.tools

    async def test_bad_ticker_returns_string_not_raise(self):
        agent = _agent()
        fn = _run_monte_carlo_fn(agent)
        out = await fn(_run_context(_deps()), "###")
        assert isinstance(out, str)
        assert "Invalid ticker" in out

    async def test_runs_real_simulation_and_formats(self, monkeypatch):
        async def _fake_seed(data_layer, ticker, *, fmp_api_key=None):  # noqa: ANN001
            return _PriceOnlyFinancials(), _mc_inputs()

        monkeypatch.setattr("finrobot.engine.orchestrator.seed_dcf_inputs_for_ticker", _fake_seed)
        agent = _agent()
        fn = _run_monte_carlo_fn(agent)
        out = await fn(_run_context(_deps()), "aapl")
        assert isinstance(out, str)
        assert "Monte Carlo" in out
        assert "Median" in out
        # the current price's standing in the distribution is the analyst payload
        assert "percentile" in out.lower()
        assert "$160.00" in out  # current price echoed

    async def test_seed_failure_returns_string_not_raise(self, monkeypatch):
        async def _boom(data_layer, ticker, *, fmp_api_key=None):  # noqa: ANN001
            raise ValueError("no financials available for ZZZZ")

        monkeypatch.setattr("finrobot.engine.orchestrator.seed_dcf_inputs_for_ticker", _boom)
        agent = _agent()
        fn = _run_monte_carlo_fn(agent)
        out = await fn(_run_context(_deps()), "ZZZZ")
        assert isinstance(out, str)
        assert "ZZZZ" in out


# ---------------------------------------------------------------------------
# run_backtest — SMA-crossover backtest as a chat tool.
#
# BackTraderAdapter (engine/backtest/) was reachable only via CLI/SDK, never
# from /chat. This exposes it so the user can ask "backtest a 10/30 SMA
# crossover on AAPL for 2023". Tests stub the adapter so they never require
# backtrader to be installed — the tool's job is config-build + error-handling
# + summary formatting, which is what we lock here.
# ---------------------------------------------------------------------------


class _StubBacktestAdapter:
    """Stands in for BackTraderAdapter: returns a fixed BacktestResult."""

    def __init__(self, data_layer) -> None:  # noqa: ANN001
        pass

    async def run(self, config) -> BacktestResult:  # noqa: ANN001
        return BacktestResult(
            initial_value=100_000.0,
            final_value=128_500.0,
            total_return=0.285,
            annualized_return=0.131,
            sharpe_ratio=0.92,
            max_drawdown=-0.18,
            total_trades=14,
            winning_trades=9,
            losing_trades=5,
            warnings=["Sharpe ratio assumes risk-free rate of 4.0%."],
        )


def _run_backtest_fn(agent):  # noqa: ANN001
    return agent._function_toolset.tools["run_backtest"].function


class TestRunBacktest:
    async def test_registered_as_tool(self):
        agent = _agent()
        assert "run_backtest" in agent._function_toolset.tools

    async def test_bad_ticker_returns_string_not_raise(self):
        agent = _agent()
        fn = _run_backtest_fn(agent)
        out = await fn(_run_context(_deps()), "###", "2023-01-01", "2024-01-01")
        assert isinstance(out, str)
        assert "Invalid ticker" in out

    async def test_bad_date_window_returns_string_not_raise(self):
        # start >= end is rejected by BacktestConfig; the tool must convert the
        # ValidationError to a returned string, never let it crash the SSE stream.
        agent = _agent()
        fn = _run_backtest_fn(agent)
        out = await fn(_run_context(_deps()), "AAPL", "2024-01-01", "2023-01-01")
        assert isinstance(out, str)
        assert "Invalid backtest request" in out
        assert "before" in out.lower()

    async def test_runs_and_formats_summary(self, monkeypatch):
        monkeypatch.setattr("finrobot.engine.orchestrator.BackTraderAdapter", _StubBacktestAdapter)
        agent = _agent()
        fn = _run_backtest_fn(agent)
        out = await fn(_run_context(_deps()), "aapl", "2023-01-01", "2024-01-01")
        assert isinstance(out, str)
        assert "AAPL" in out  # header echoes the ticker/window
        assert "Sharpe" in out
        assert "128,500" in out  # final value from the summary

    async def test_run_failure_returns_string_not_raise(self, monkeypatch):
        class _BoomAdapter:
            def __init__(self, data_layer) -> None:  # noqa: ANN001
                pass

            async def run(self, config):  # noqa: ANN001, ANN201
                raise ValueError("No price data for ZZZZ in the requested window")

        monkeypatch.setattr("finrobot.engine.orchestrator.BackTraderAdapter", _BoomAdapter)
        agent = _agent()
        fn = _run_backtest_fn(agent)
        out = await fn(_run_context(_deps()), "AAPL", "2023-01-01", "2024-01-01")
        assert isinstance(out, str)
        assert "No price data" in out


# ---------------------------------------------------------------------------
# web search — PydanticAI's own duckduckgo_search_tool (keyless, provider-
# agnostic) registered on the lead agent.
#
# The chat had NO web search, so "联网搜一下今天的ai热点新闻" mis-fired
# query_financial_data(ticker="AI", data_type="news") — treating "ai" as the
# C3.ai ticker and returning that company's feed instead of real web results.
# We register the FRAMEWORK's common tool rather than hand-rolling ddgs. Tests
# stub DDGS (where the common tool builds its client) so they never hit the net.
# ---------------------------------------------------------------------------


class TestWebSearch:
    def test_duckduckgo_tool_registered(self):
        # The lead agent must carry a live web-search tool so topic/news queries
        # don't degrade to query_financial_data on a guessed ticker.
        assert "duckduckgo_search" in _agent()._function_toolset.tools

    async def test_returns_results_from_ddg(self, monkeypatch):
        class _FakeDDGS:
            def text(self, query, max_results=None):  # noqa: ANN001, ARG002
                return [
                    {
                        "title": "AI News | Reuters",
                        "href": "https://reuters.com/ai",
                        "body": "Latest AI developments and headlines.",
                    }
                ]

        # Patch DDGS where the framework common tool constructs its client.
        monkeypatch.setattr("pydantic_ai.common_tools.duckduckgo.DDGS", _FakeDDGS)
        agent = _agent()
        fn = agent._function_toolset.tools["duckduckgo_search"].function
        results = await fn("today AI news")
        assert isinstance(results, list)
        assert results[0]["href"] == "https://reuters.com/ai"
        assert results[0]["title"] == "AI News | Reuters"
