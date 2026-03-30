from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from finagent.engine.data.interface import DataResult
from finagent.engine.pipelines.equity_research import create_equity_research_pipeline


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeDataLayer:
    async def fetch(self, data_type: str, ticker: str, **kwargs) -> DataResult:
        return DataResult(
            data={
                "revenue": 385_000_000_000,
                "ebitda": 130_000_000_000,
                "price_history": [{"close": 150.0}],
            },
            provider="fake",
            ticker=ticker,
            data_type=data_type,
            timestamp=datetime.now(tz=timezone.utc),
        )


@dataclass
class FakeDeps:
    data_layer: FakeDataLayer = None
    skill_runtime: object = None

    def __post_init__(self):
        if self.data_layer is None:
            self.data_layer = FakeDataLayer()


class FakeCtx:
    deps = FakeDeps()


def _make_agent(output: str = "analysis output") -> Agent:
    return Agent(TestModel(custom_output_text=output))


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------

class TestPipelineStructure:
    def test_has_exactly_5_steps(self):
        pipeline = create_equity_research_pipeline(_make_agent())
        assert len(pipeline.steps) == 5

    def test_step_names_correct(self):
        pipeline = create_equity_research_pipeline(_make_agent())
        names = [s.name for s in pipeline.steps]
        assert names == ["data_collection", "peer_analysis", "financial_modeling", "thesis", "report"]

    def test_step_skill_sections(self):
        pipeline = create_equity_research_pipeline(_make_agent())
        step_map = {s.name: s.skill_section for s in pipeline.steps}
        assert step_map["data_collection"] is None
        assert step_map["peer_analysis"] == "comps-analysis"
        assert step_map["financial_modeling"] == "dcf-model"
        assert step_map["thesis"] == "initiating-coverage"
        assert step_map["report"] is None

    def test_step1_required_data(self):
        pipeline = create_equity_research_pipeline(_make_agent())
        step1 = pipeline.steps[0]
        assert "financials" in step1.required_data
        assert "price" in step1.required_data
        assert "news" in step1.required_data
        assert "filings" not in step1.required_data   # yfinance doesn't support it in P0

    def test_steps_2_to_5_required_data_empty(self):
        pipeline = create_equity_research_pipeline(_make_agent())
        for step in pipeline.steps[1:]:
            assert step.required_data == []


# ---------------------------------------------------------------------------
# Execution tests
# ---------------------------------------------------------------------------

class TestPipelineExecution:
    async def test_execute_produces_result_with_all_5_step_keys(self, capsys):
        # Step 1 validator checks for "revenue", "ebitda", "price_history"
        # FakeDataLayer returns data containing these fields → to_context_string includes them
        pipeline = create_equity_research_pipeline(_make_agent(
            "revenue 385B ebitda 130B price_history available"
        ))
        result = await pipeline.execute(FakeCtx(), "AAPL")
        assert set(result.steps.keys()) == {
            "data_collection", "peer_analysis", "financial_modeling", "thesis", "report"
        }

    async def test_execute_logs_5_progress_messages(self, capsys):
        pipeline = create_equity_research_pipeline(_make_agent(
            "revenue 385B ebitda 130B price_history available"
        ))
        await pipeline.execute(FakeCtx(), "AAPL")
        out = capsys.readouterr().out
        for i in range(1, 6):
            assert f"Step {i}/5" in out
