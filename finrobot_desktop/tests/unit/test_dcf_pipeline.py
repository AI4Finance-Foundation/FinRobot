from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from finagent.engine.data.interface import DataResult
from finagent.engine.deps import FinAgentDeps
from finagent.engine.pipelines.dcf import create_dcf_pipeline


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

class TestDcfPipelineStructure:
    def test_has_exactly_6_steps(self):
        pipeline = create_dcf_pipeline(_make_test_agents())
        assert len(pipeline.steps) == 6

    def test_step_names_correct(self):
        pipeline = create_dcf_pipeline(_make_test_agents())
        names = [s.name for s in pipeline.steps]
        assert names == [
            "historical_data", "projection", "wacc",
            "terminal_value", "sensitivity", "output_gen",
        ]

    def test_historical_data_uses_data_agent(self):
        agents = _make_test_agents()
        pipeline = create_dcf_pipeline(agents)
        assert pipeline.steps[0].agent is agents["data"]

    def test_projection_wacc_terminal_sensitivity_use_modeling_agent(self):
        agents = _make_test_agents()
        pipeline = create_dcf_pipeline(agents)
        for step in pipeline.steps[1:5]:
            assert step.agent is agents["modeling"], \
                f"Step '{step.name}' should use modeling agent"

    def test_output_gen_uses_report_agent(self):
        agents = _make_test_agents()
        pipeline = create_dcf_pipeline(agents)
        assert pipeline.steps[5].agent is agents["report"]


# ---------------------------------------------------------------------------
# Execution tests
# ---------------------------------------------------------------------------

class TestDcfPipelineExecution:
    async def test_execute_produces_result_with_all_6_step_keys(self, capsys):
        pipeline = create_dcf_pipeline(_make_test_agents(
            "revenue 385B ebitda 130B"
        ))
        result = await pipeline.execute(FakeDeps(), "AAPL")
        assert set(result.steps.keys()) == {
            "historical_data", "projection", "wacc",
            "terminal_value", "sensitivity", "output_gen",
        }
