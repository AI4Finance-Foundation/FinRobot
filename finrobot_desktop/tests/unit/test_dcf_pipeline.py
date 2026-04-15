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
class FakeSettings:
    model_name: object = None

    def __post_init__(self):
        if self.model_name is None:
            self.model_name = TestModel()


@dataclass
class FakeDeps:
    data_layer: FakeDataLayer = None
    skill_runtime: object = None
    settings: FakeSettings = None

    def __post_init__(self):
        if self.data_layer is None:
            self.data_layer = FakeDataLayer()
        if self.settings is None:
            self.settings = FakeSettings()


def _make_test_agents(output: str = "analysis output") -> dict[str, Agent]:
    agents = {}
    for role in ["data", "analysis", "modeling", "synthesis", "report"]:
        agents[role] = Agent(TestModel(custom_output_text=output), deps_type=FinAgentDeps, defer_model_check=True)
    return agents


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------

class TestDcfPipelineStructure:
    def test_has_exactly_3_steps(self):
        pipeline = create_dcf_pipeline(_make_test_agents())
        assert len(pipeline.steps) == 3

    def test_step_names_correct(self):
        pipeline = create_dcf_pipeline(_make_test_agents())
        names = [s.name for s in pipeline.steps]
        assert names == [
            "historical_data", "dcf_calc", "output_gen",
        ]

    def test_historical_data_uses_data_agent(self):
        agents = _make_test_agents()
        pipeline = create_dcf_pipeline(agents)
        assert pipeline.steps[0].agent is agents["data"]

    def test_dcf_calc_uses_modeling_agent(self):
        agents = _make_test_agents()
        pipeline = create_dcf_pipeline(agents)
        step = next(s for s in pipeline.steps if s.name == "dcf_calc")
        assert step.agent is agents["modeling"]

    def test_output_gen_uses_report_agent(self):
        agents = _make_test_agents()
        pipeline = create_dcf_pipeline(agents)
        assert pipeline.steps[2].agent is agents["report"]


# ---------------------------------------------------------------------------
# Execution tests
# ---------------------------------------------------------------------------

def _make_stub_execute_fn(step_name: str):
    """Return an async stub execute_fn that returns a minimal valid StepOutput."""
    from finagent.engine.models.financial import StepOutput

    async def _stub(agent, deps, prompt, structured_context, ticker):
        return StepOutput(
            text=(
                f"{step_name} stub output revenue ebitda dcf wacc terminal value "
                f"free cash flow sensitivity implied price"
            )
        )

    return _stub


class TestDcfPipelineExecution:
    async def test_execute_produces_result_with_all_3_step_keys(self, capsys):
        pipeline = create_dcf_pipeline(_make_test_agents(
            "revenue 385B ebitda 130B"
        ))
        # Stub executor to avoid real LLM/compute calls in orchestration test
        from finagent.engine.pipelines.base import TextValidator
        from finagent.engine.pipelines.validators import validate_is_non_empty
        for step in pipeline.steps:
            step.executor = _make_stub_execute_fn(step.name)
            step.validator = TextValidator(validate_is_non_empty)
        result = await pipeline.execute(FakeDeps(), "AAPL")
        assert set(result.steps.keys()) == {
            "historical_data", "dcf_calc", "output_gen",
        }


# ---------------------------------------------------------------------------
# P1.5: execute_fn / validate_structured hook tests
# ---------------------------------------------------------------------------

def test_dcf_pipeline_historical_data_has_custom_executor():
    from finagent.engine.pipelines.dcf import create_dcf_pipeline
    from finagent.engine.pipelines.base import DefaultAgentExecutor, StructuredValidator
    from unittest.mock import MagicMock
    agents = {k: MagicMock() for k in ["data", "modeling", "report"]}
    pipeline = create_dcf_pipeline(agents)
    step = next(s for s in pipeline.steps if s.name == "historical_data")
    assert not isinstance(step.executor, DefaultAgentExecutor)
    assert isinstance(step.validator, StructuredValidator)

def test_dcf_pipeline_dcf_calc_step_has_custom_executor():
    from finagent.engine.pipelines.dcf import create_dcf_pipeline
    from finagent.engine.pipelines.base import DefaultAgentExecutor, StructuredValidator
    from unittest.mock import MagicMock
    agents = {k: MagicMock() for k in ["data", "modeling", "report"]}
    pipeline = create_dcf_pipeline(agents)
    step = next(s for s in pipeline.steps if s.name == "dcf_calc")
    assert not isinstance(step.executor, DefaultAgentExecutor)
    assert isinstance(step.validator, StructuredValidator)
