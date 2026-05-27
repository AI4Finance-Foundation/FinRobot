from dataclasses import dataclass
from datetime import datetime, timezone

from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from finrobot.engine.data.interface import DataResult
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.pipelines.comps import create_comps_pipeline


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeDataLayer:
    async def fetch(self, data_type: str, ticker: str, **kwargs) -> DataResult:
        if data_type == "price":
            data = {
                "current_price": 180.0,
                "price_history": [{"close": 170.0}, {"close": 180.0}, {"close": 190.0}],
            }
        else:
            data = {
                "revenue": 385_000_000_000,
                "ebitda": 130_000_000_000,
                "net_income": 100_000_000_000,
                "market_cap": 2_800_000_000_000,
                "total_debt": 110_000_000_000,
                "total_cash": 60_000_000_000,
                "gross_margin": 0.44,
                "operating_margin": 0.30,
                "shares_outstanding": 15_500_000_000,
                "current_price": 180.0,
            }
        return DataResult(
            data=data,
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
        agents[role] = Agent(
            TestModel(custom_output_text=output), deps_type=FinRobotDeps, defer_model_check=True
        )
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
            "target_data",
            "peer_selection",
            "peer_data",
            "multiples_calc",
            "statistical_bench",
            "output_gen",
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
        pipeline = create_comps_pipeline(_make_test_agents("revenue 385B ebitda 130B"))
        result = await pipeline.execute(FakeDeps(), "AAPL")
        assert set(result.steps.keys()) == {
            "target_data",
            "peer_selection",
            "peer_data",
            "multiples_calc",
            "statistical_bench",
            "output_gen",
        }


# ---------------------------------------------------------------------------
# P1.5: execute_fn / validate_structured hook tests
# ---------------------------------------------------------------------------


def test_comps_pipeline_has_structured_validator_on_target_data():
    from finrobot.engine.pipelines.comps import create_comps_pipeline
    from finrobot.engine.pipelines.base import DefaultAgentExecutor, StructuredValidator
    from unittest.mock import MagicMock

    agents = {k: MagicMock() for k in ["data", "analysis", "modeling", "report"]}
    pipeline = create_comps_pipeline(agents)
    step = next(s for s in pipeline.steps if s.name == "target_data")
    assert not isinstance(step.executor, DefaultAgentExecutor)
    assert isinstance(step.validator, StructuredValidator)


