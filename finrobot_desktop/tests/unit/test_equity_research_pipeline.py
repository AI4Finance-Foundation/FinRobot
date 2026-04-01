from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

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
        if data_type == "price":
            data = {
                "current_price": 150.0,
                "price_history": [{"close": 150.0}],
            }
        else:
            data = {
                "revenue": 385_000_000_000,
                "ebitda": 130_000_000_000,
                "net_income": 95_000_000_000,
                "market_cap": 2_500_000_000_000,
                "shares_outstanding": 15_500_000_000,
                "current_price": 150.0,
                "gross_margin": 0.43,
                "operating_margin": 0.30,
                "total_debt": 120_000_000_000,
                "total_cash": 60_000_000_000,
                "price_history": [{"close": 150.0}],
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

def _make_stub_execute_fn(step_name: str):
    """Return an async stub execute_fn that returns a minimal valid StepOutput."""
    from finagent.engine.models.financial import StepOutput

    async def _stub(agent, deps, prompt, structured_context, ticker):
        return StepOutput(text=f"{step_name} stub output revenue ebitda AAPL MSFT GOOG peers buy hold sell risk catalyst price target")

    return _stub


class TestPipelineExecution:
    async def test_execute_produces_result_with_all_5_step_keys(self, capsys):
        """Pipeline orchestration routes through all 5 steps and collects their outputs."""
        pipeline = create_equity_research_pipeline(_make_test_agents(
            "revenue 385B ebitda 130B price_history available"
        ))
        # Patch execute_fn to avoid real compute in unit test of orchestration
        for step in pipeline.steps:
            if step.execute_fn is not None:
                step.execute_fn = _make_stub_execute_fn(step.name)
            step.validate_structured = None
        result = await pipeline.execute(FakeDeps(), "AAPL")
        assert set(result.steps.keys()) == {
            "data_collection", "peer_analysis", "financial_modeling", "thesis", "report"
        }

    async def test_execute_logs_5_progress_messages(self, caplog):
        import logging

        with caplog.at_level(logging.INFO):
            pipeline = create_equity_research_pipeline(_make_test_agents(
                "revenue 385B ebitda 130B price_history available"
            ))
            # Patch execute_fn to avoid real compute in unit test of orchestration
            for step in pipeline.steps:
                if step.execute_fn is not None:
                    step.execute_fn = _make_stub_execute_fn(step.name)
                step.validate_structured = None
            await pipeline.execute(FakeDeps(), "AAPL")
        messages = " ".join(r.message for r in caplog.records)
        for i in range(1, 6):
            assert f"Step {i}/5" in messages


# ---------------------------------------------------------------------------
# Fixtures for execute_fn tests
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_deps():
    deps = MagicMock()
    deps.data_layer = MagicMock()
    deps.skill_runtime = None
    deps.settings = MagicMock()
    deps.settings.model_name = "test"
    return deps


# ---------------------------------------------------------------------------
# execute_fn hook tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_step1_produces_financial_data(mock_deps):
    """Step 1 data_collection execute_fn returns StepOutput with FinancialData."""
    from finagent.engine.pipelines.equity_research import _execute_data_collection
    from finagent.engine.models.financial import FinancialData, StepOutput

    fin_result = DataResult(
        data=dict(revenue=100e9, ebitda=35e9, net_income=20e9,
                  gross_margin=0.47, operating_margin=0.28,
                  pe_ratio=28.5, market_cap=3e12, shares_outstanding=15e9,
                  current_price=200.0, total_debt=50e9, total_cash=20e9),
        provider="yfinance", ticker="AAPL", data_type="financials",
        timestamp=datetime.now(tz=timezone.utc),
    )
    price_result = DataResult(
        data={"current_price": 200.0, "price_history": [
            {"date": "2024-01-01", "close": 180.0},
            {"date": "2024-12-01", "close": 200.0},
        ]},
        provider="yfinance", ticker="AAPL", data_type="price",
        timestamp=datetime.now(tz=timezone.utc),
    )
    mock_agent = MagicMock()
    mock_result = MagicMock()
    mock_result.output = "Analysis text"
    mock_agent.run = AsyncMock(return_value=mock_result)

    async def mock_fetch(data_type, ticker):
        return fin_result if data_type == "financials" else price_result

    mock_deps.data_layer.fetch = mock_fetch

    output = await _execute_data_collection(mock_agent, mock_deps, "prompt", {}, "AAPL")
    assert isinstance(output, StepOutput)
    assert isinstance(output.structured, FinancialData)
    assert output.structured.revenue == 100e9


@pytest.mark.asyncio
async def test_step3_dcf_deterministic(mock_deps):
    """Step 3 with same DCFInputs -> same DCFResult."""
    from finagent.engine.models.financial import DCFInputs, DCFResult, StepOutput
    from finagent.engine.pipelines.equity_research import _execute_financial_modeling

    dcf_inputs = DCFInputs(
        revenue_base=100e9, revenue_growth_rates=[0.05, 0.05],
        ebitda_margin=0.35, capex_pct_revenue=0.05, nwc_pct_revenue=0.02,
        tax_rate=0.21, risk_free_rate=0.04, beta=1.2, equity_risk_premium=0.05,
        cost_of_debt=0.04, debt_ratio=0.1, terminal_growth_rate=0.025,
        shares_outstanding=1e9, net_debt=10e9,
    )
    mock_agent = MagicMock()
    mock_param_result = MagicMock()
    mock_param_result.output = dcf_inputs
    mock_agent_instance = MagicMock()
    mock_agent_instance.run = AsyncMock(return_value=mock_param_result)

    with patch("finagent.engine.pipelines.equity_research.PydanticAgent",
               return_value=mock_agent_instance):
        out1 = await _execute_financial_modeling(mock_agent, mock_deps, "prompt", {}, "AAPL")
        out2 = await _execute_financial_modeling(mock_agent, mock_deps, "prompt", {}, "AAPL")

    assert isinstance(out1.structured, DCFResult)
    assert out1.structured.implied_price == out2.structured.implied_price
