from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from finagent.engine.data.interface import DataResult
from finagent.engine.deps import FinAgentDeps
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


def _make_test_agents(output: str = "analysis output") -> dict[str, Agent]:
    """Create agents dict with TestModel for unit testing."""
    agents = {}
    for role in ["data", "analysis", "modeling", "synthesis", "report"]:
        agents[role] = Agent(TestModel(custom_output_text=output), deps_type=FinAgentDeps, defer_model_check=True)
    return agents


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------

class TestPipelineStructure:
    def test_has_exactly_5_steps(self):
        pipeline = create_equity_research_pipeline(_make_test_agents())
        assert len(pipeline.steps) == 5

    def test_step_names_correct(self):
        pipeline = create_equity_research_pipeline(_make_test_agents())
        names = [s.name for s in pipeline.steps]
        assert names == ["data_collection", "peer_analysis", "financial_modeling", "thesis", "report"]

    def test_step_skill_sections(self):
        pipeline = create_equity_research_pipeline(_make_test_agents())
        step_map = {s.name: s.skill_section for s in pipeline.steps}
        assert step_map["data_collection"] is None
        assert step_map["peer_analysis"] == "comps-analysis"
        assert step_map["financial_modeling"] == "dcf-model"
        assert step_map["thesis"] == "initiating-coverage"
        assert step_map["report"] is None

    def test_step1_required_data(self):
        pipeline = create_equity_research_pipeline(_make_test_agents())
        step1 = pipeline.steps[0]
        assert "financials" in step1.required_data
        assert "price" in step1.required_data
        assert "news" in step1.required_data
        assert "filings" not in step1.required_data

    def test_steps_2_to_5_required_data_empty(self):
        pipeline = create_equity_research_pipeline(_make_test_agents())
        for step in pipeline.steps[1:]:
            assert step.required_data == []

    def test_step_agents_are_different_instances(self):
        agents = _make_test_agents()
        pipeline = create_equity_research_pipeline(agents)
        agent_ids = [id(s.agent) for s in pipeline.steps]
        # data, analysis, modeling, synthesis, report — all different
        assert len(set(agent_ids)) == 5

    def test_data_collection_uses_data_agent(self):
        agents = _make_test_agents()
        pipeline = create_equity_research_pipeline(agents)
        assert pipeline.steps[0].agent is agents["data"]

    def test_peer_analysis_uses_analysis_agent(self):
        agents = _make_test_agents()
        pipeline = create_equity_research_pipeline(agents)
        assert pipeline.steps[1].agent is agents["analysis"]


# ---------------------------------------------------------------------------
# Execution tests
# ---------------------------------------------------------------------------

class TestPipelineExecution:
    async def test_execute_produces_result_with_all_5_step_keys(self, capsys):
        # Step 1 validator checks for "revenue", "ebitda", "price_history"
        pipeline = create_equity_research_pipeline(_make_test_agents(
            "revenue 385B ebitda 130B price_history available"
        ))
        result = await pipeline.execute(FakeDeps(), "AAPL")
        assert set(result.steps.keys()) == {
            "data_collection", "peer_analysis", "financial_modeling", "thesis", "report"
        }

    async def test_execute_logs_5_progress_messages(self, capsys):
        pipeline = create_equity_research_pipeline(_make_test_agents(
            "revenue 385B ebitda 130B price_history available"
        ))
        await pipeline.execute(FakeDeps(), "AAPL")
        out = capsys.readouterr().out
        for i in range(1, 6):
            assert f"Step {i}/5" in out
