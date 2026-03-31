from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from finagent.engine.data.interface import DataResult
from finagent.engine.deps import FinAgentDeps
from finagent.engine.pipelines.comps import create_comps_pipeline


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeDataLayer:
    async def fetch(self, data_type: str, ticker: str, **kwargs) -> DataResult:
        return DataResult(
            data={"revenue": 385_000_000_000, "ebitda": 130_000_000_000},
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
    agents = {}
    for role in ["data", "analysis", "modeling", "synthesis", "report"]:
        agents[role] = Agent(TestModel(custom_output_text=output), deps_type=FinAgentDeps, defer_model_check=True)
    return agents


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------

class TestCompsPipelineStructure:
    def test_has_exactly_6_steps(self):
        pipeline = create_comps_pipeline(_make_test_agents())
        assert len(pipeline.steps) == 6

    def test_step_names_correct(self):
        pipeline = create_comps_pipeline(_make_test_agents())
        names = [s.name for s in pipeline.steps]
        assert names == [
            "target_data", "peer_selection", "peer_data",
            "multiples_calc", "statistical_bench", "output_gen",
        ]

    def test_target_data_uses_data_agent(self):
        agents = _make_test_agents()
        pipeline = create_comps_pipeline(agents)
        assert pipeline.steps[0].agent is agents["data"]

    def test_peer_selection_uses_analysis_agent(self):
        agents = _make_test_agents()
        pipeline = create_comps_pipeline(agents)
        assert pipeline.steps[1].agent is agents["analysis"]

    def test_peer_data_uses_data_agent(self):
        agents = _make_test_agents()
        pipeline = create_comps_pipeline(agents)
        assert pipeline.steps[2].agent is agents["data"]

    def test_output_gen_uses_report_agent(self):
        agents = _make_test_agents()
        pipeline = create_comps_pipeline(agents)
        assert pipeline.steps[5].agent is agents["report"]


# ---------------------------------------------------------------------------
# Execution tests
# ---------------------------------------------------------------------------

class TestCompsPipelineExecution:
    async def test_execute_produces_result_with_all_6_step_keys(self, capsys):
        pipeline = create_comps_pipeline(_make_test_agents(
            "revenue 385B ebitda 130B"
        ))
        result = await pipeline.execute(FakeDeps(), "AAPL")
        assert set(result.steps.keys()) == {
            "target_data", "peer_selection", "peer_data",
            "multiples_calc", "statistical_bench", "output_gen",
        }
