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
        agents[role] = Agent(
            TestModel(custom_output_text=output), deps_type=FinAgentDeps, defer_model_check=True
        )
    return agents


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------


class TestPipelineStructure:
    def test_has_exactly_7_steps(self):
        pipeline = create_equity_research_pipeline(_make_test_agents())
        assert len(pipeline.steps) == 7

    def test_step_names_correct(self):
        pipeline = create_equity_research_pipeline(_make_test_agents())
        names = [s.name for s in pipeline.steps]
        assert names == [
            "data_collection",
            "catalyst_analysis",
            "peer_analysis",
            "financial_modeling",
            "technical_analysis",
            "thesis",
            "report",
        ]

    def test_step_skill_sections(self):
        pipeline = create_equity_research_pipeline(_make_test_agents())
        step_map = {s.name: s.skill_section for s in pipeline.steps}
        assert step_map["data_collection"] is None
        assert step_map["catalyst_analysis"] is None
        assert step_map["peer_analysis"] == "comps-analysis"
        assert step_map["financial_modeling"] == "dcf-model"
        assert step_map["technical_analysis"] is None
        assert step_map["thesis"] == "initiating-coverage"
        assert step_map["report"] is None

    def test_step1_required_data(self):
        pipeline = create_equity_research_pipeline(_make_test_agents())
        step1 = pipeline.steps[0]
        assert "financials" in step1.required_data
        assert "price" in step1.required_data
        assert "news" in step1.required_data
        assert "filings" not in step1.required_data

    def test_steps_2_to_7_required_data_empty(self):
        pipeline = create_equity_research_pipeline(_make_test_agents())
        for step in pipeline.steps[1:]:
            assert step.required_data == []

    def test_step_agents_are_different_instances(self):
        agents = _make_test_agents()
        pipeline = create_equity_research_pipeline(agents)
        agent_ids = [id(s.agent) for s in pipeline.steps]
        # data (used by data_collection + catalyst_analysis), analysis, modeling,
        # synthesis, report -- 5 unique agent objects
        assert len(set(agent_ids)) == 5

    def test_data_collection_uses_data_agent(self):
        agents = _make_test_agents()
        pipeline = create_equity_research_pipeline(agents)
        assert pipeline.steps[0].agent is agents["data"]

    def test_catalyst_analysis_uses_data_agent(self):
        agents = _make_test_agents()
        pipeline = create_equity_research_pipeline(agents)
        assert pipeline.steps[1].agent is agents["data"]

    def test_peer_analysis_uses_analysis_agent(self):
        agents = _make_test_agents()
        pipeline = create_equity_research_pipeline(agents)
        assert pipeline.steps[2].agent is agents["analysis"]


# ---------------------------------------------------------------------------
# Execution tests
# ---------------------------------------------------------------------------


def _make_stub_execute_fn(step_name: str):
    """Return an async stub execute_fn that returns a minimal valid StepOutput."""
    from finagent.engine.models.financial import StepOutput

    async def _stub(agent, deps, prompt, structured_context, ticker):
        return StepOutput(
            text=f"{step_name} stub output revenue ebitda AAPL MSFT GOOG peers buy hold sell risk catalyst price target"
        )

    return _stub


class TestPipelineExecution:
    async def test_execute_produces_result_with_all_7_step_keys(self, capsys):
        """Pipeline orchestration routes through all 7 steps and collects their outputs."""
        pipeline = create_equity_research_pipeline(
            _make_test_agents("revenue 385B ebitda 130B price_history available")
        )
        # Stub executor to avoid real compute in unit test of orchestration
        from finagent.engine.pipelines.base import TextValidator
        from finagent.engine.pipelines.validators import validate_is_non_empty

        for step in pipeline.steps:
            step.executor = _make_stub_execute_fn(step.name)
            step.validator = TextValidator(validate_is_non_empty)
        result = await pipeline.execute(FakeDeps(), "AAPL")
        assert set(result.steps.keys()) == {
            "data_collection",
            "catalyst_analysis",
            "peer_analysis",
            "financial_modeling",
            "technical_analysis",
            "thesis",
            "report",
        }

    async def test_execute_logs_7_progress_messages(self, caplog):
        import logging

        with caplog.at_level(logging.INFO):
            pipeline = create_equity_research_pipeline(
                _make_test_agents("revenue 385B ebitda 130B price_history available")
            )
            # Stub executor to avoid real compute in unit test of orchestration
            from finagent.engine.pipelines.base import TextValidator
            from finagent.engine.pipelines.validators import validate_is_non_empty

            for step in pipeline.steps:
                step.executor = _make_stub_execute_fn(step.name)
                step.validator = TextValidator(validate_is_non_empty)
            await pipeline.execute(FakeDeps(), "AAPL")
        messages = " ".join(r.message for r in caplog.records)
        for i in range(1, 8):
            assert f"Step {i}/7" in messages


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
    from finagent.engine.pipelines._helpers import execute_financial_data_step
    from finagent.engine.models.financial import FinancialData, StepOutput

    fin_result = DataResult(
        data=dict(
            revenue=100e9,
            ebitda=35e9,
            net_income=20e9,
            gross_margin=0.47,
            operating_margin=0.28,
            pe_ratio=28.5,
            market_cap=3e12,
            shares_outstanding=15e9,
            current_price=200.0,
            total_debt=50e9,
            total_cash=20e9,
        ),
        provider="yfinance",
        ticker="AAPL",
        data_type="financials",
        timestamp=datetime.now(tz=timezone.utc),
    )
    price_result = DataResult(
        data={
            "current_price": 200.0,
            "price_history": [
                {"date": "2024-01-01", "close": 180.0},
                {"date": "2024-12-01", "close": 200.0},
            ],
        },
        provider="yfinance",
        ticker="AAPL",
        data_type="price",
        timestamp=datetime.now(tz=timezone.utc),
    )
    mock_agent = MagicMock()
    mock_result = MagicMock()
    mock_result.output = "Analysis text"
    mock_agent.run = AsyncMock(return_value=mock_result)

    async def mock_fetch(data_type, ticker):
        return fin_result if data_type == "financials" else price_result

    mock_deps.data_layer.fetch = mock_fetch

    output = await execute_financial_data_step(mock_agent, mock_deps, "prompt", {}, "AAPL")
    assert isinstance(output, StepOutput)
    assert isinstance(output.structured, FinancialData)
    assert output.structured.income.revenue == 100e9


@pytest.mark.asyncio
async def test_step3_dcf_deterministic(mock_deps):
    """Step 3 with the same FinancialData → same DCFResult (no LLM call).

    Asserts the architectural property after the seed_dcf_inputs refactor
    (CLAUDE.md red-line #5): financial_modeling must be deterministic — it
    does not query an LLM for DCF parameters. Repeated calls with identical
    inputs must produce bit-identical outputs.
    """
    from datetime import datetime, timezone

    from finagent.engine.models.financial import (
        BalanceSheet,
        DCFResult,
        FinancialData,
        HistoricalMetrics,
        IncomeStatement,
        MarketData,
        ValuationMetrics,
    )
    from finagent.engine.pipelines.equity_research import _execute_financial_modeling

    fd = FinancialData(
        ticker="AAPL",
        company_name="Apple Inc.",
        timestamp=datetime.now(tz=timezone.utc),
        income=IncomeStatement(
            revenue=385e9,
            ebitda=130e9,
            net_income=95e9,
            gross_margin=0.43,
            operating_margin=0.30,
            interest_expense=3e9,
        ),
        balance=BalanceSheet(total_debt=120e9, total_cash=60e9),
        market=MarketData(
            market_cap=2.5e12,
            shares_outstanding=15.5e9,
            current_price=150.0,
            industry="Consumer Electronics",
            beta=1.25,
        ),
        valuation=ValuationMetrics(),
    )
    hm = HistoricalMetrics(
        years=[],
        revenue=[],
        revenue_growth_yoy=[],
        cogs=[],
        gross_profit=[],
        gross_margin=[],
        sga=[],
        sga_ratio=[],
        ebitda=[],
        ebitda_margin=[],
        operating_income=[],
        operating_margin=[],
        net_income=[],
        eps=[],
        pe_ratio=[],
        cagr_revenue=None,
        ticker="AAPL",
    )
    ctx = {"data_collection": fd, "historical_metrics": hm}

    mock_agent = MagicMock()
    out1 = await _execute_financial_modeling(mock_agent, mock_deps, "prompt", ctx, "AAPL")
    out2 = await _execute_financial_modeling(mock_agent, mock_deps, "prompt", ctx, "AAPL")

    assert isinstance(out1.structured, DCFResult)
    assert out1.structured.implied_price == out2.structured.implied_price


@pytest.mark.asyncio
async def test_peer_analysis_raises_when_data_collection_missing(mock_deps):
    """_execute_peer_analysis raises ValueError when data_collection not in structured_context."""
    from finagent.engine.pipelines.equity_research import _execute_peer_analysis
    from finagent.engine.models.financial import PeerSelection

    mock_peer_result = MagicMock()
    mock_peer_result.output = PeerSelection(
        tickers=["MSFT", "GOOGL", "META"],
        rationale="Large-cap tech peers",
    )
    mock_agent_instance = MagicMock()
    mock_agent_instance.run = AsyncMock(return_value=mock_peer_result)

    fin_result = DataResult(
        data=dict(
            revenue=50e9,
            ebitda=15e9,
            net_income=10e9,
            gross_margin=0.40,
            operating_margin=0.25,
            pe_ratio=25.0,
            market_cap=1e12,
            shares_outstanding=5e9,
            current_price=100.0,
            total_debt=10e9,
            total_cash=5e9,
        ),
        provider="yfinance",
        ticker="MSFT",
        data_type="financials",
        timestamp=datetime.now(tz=timezone.utc),
    )
    mock_deps.data_layer.fetch = AsyncMock(return_value=fin_result)

    mock_agent = MagicMock()

    with patch("finagent.engine.pipelines.equity_research.Agent", return_value=mock_agent_instance):
        with pytest.raises(ValueError, match="data_collection"):
            await _execute_peer_analysis(mock_agent, mock_deps, "prompt", {}, "AAPL")


def test_build_sensitivity_ranges_returns_valid_ranges():
    """build_sensitivity_ranges returns non-empty tg_range that stays below min(rate_range)."""
    from finagent.engine.pipelines._helpers import build_sensitivity_ranges

    wacc_range, tg_range = build_sensitivity_ranges(0.09, 0.025)

    assert len(wacc_range) == 5
    assert len(tg_range) >= 1
    min_wacc = min(wacc_range)
    assert all(
        g < min_wacc for g in tg_range
    ), f"All tg values must be < min_wacc {min_wacc}, got {tg_range}"


# ---------------------------------------------------------------------------
# Catalyst analysis integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_catalyst_analysis_produces_catalyst_analysis_output(mock_deps):
    """_execute_catalyst_analysis returns StepOutput with CatalystAnalysis."""
    from finagent.engine.pipelines.equity_research import _execute_catalyst_analysis
    from finagent.engine.models.financial import CatalystAnalysis, StepOutput
    from finagent.engine.compute.news import NewsItem

    news_result = DataResult(
        data={
            "news_items": [
                {
                    "title": "AAPL beats earnings estimates",
                    "source": "Reuters",
                    "published": "2024-06-01T10:00:00Z",
                    "url": "https://example.com/1",
                },
                {
                    "title": "New iPhone launch drives revenue growth",
                    "source": "Bloomberg",
                    "published": "2024-06-02T12:00:00Z",
                    "url": "https://example.com/2",
                },
                {
                    "title": "AAPL faces regulatory probe in EU",
                    "source": "FT",
                    "published": "2024-06-03T08:00:00Z",
                    "url": "https://example.com/3",
                },
            ]
        },
        provider="fake",
        ticker="AAPL",
        data_type="news",
        timestamp=datetime.now(tz=timezone.utc),
    )

    # Mock fetch_news to return raw news from our DataResult
    mock_deps.data_layer.fetch = AsyncMock(return_value=news_result)

    # Mock classify_news to return pre-classified items
    classified = [
        NewsItem(
            title="AAPL beats earnings estimates",
            source="Reuters",
            published=datetime(2024, 6, 1, 10, 0, tzinfo=timezone.utc),
            url="https://example.com/1",
            category="earnings",
            sentiment="positive",
            importance=5,
            summary="Apple exceeds analyst expectations for Q2.",
        ),
        NewsItem(
            title="New iPhone launch drives revenue growth",
            source="Bloomberg",
            published=datetime(2024, 6, 2, 12, 0, tzinfo=timezone.utc),
            url="https://example.com/2",
            category="product",
            sentiment="positive",
            importance=4,
            summary="iPhone 16 sales surpass initial projections.",
        ),
        NewsItem(
            title="AAPL faces regulatory probe in EU",
            source="FT",
            published=datetime(2024, 6, 3, 8, 0, tzinfo=timezone.utc),
            url="https://example.com/3",
            category="regulatory",
            sentiment="negative",
            importance=3,
            summary="EU opens antitrust investigation into Apple.",
        ),
    ]

    mock_agent = MagicMock()
    with patch(
        "finagent.engine.pipelines.equity_research.classify_news",
        return_value=classified,
    ):
        output = await _execute_catalyst_analysis(mock_agent, mock_deps, "prompt", {}, "AAPL")

    assert isinstance(output, StepOutput)
    assert isinstance(output.structured, CatalystAnalysis)
    analysis = output.structured

    # 3 items all have importance >= 3, so all should become catalysts
    assert len(analysis.events) == 3
    assert analysis.overall_sentiment in ("bullish", "bearish", "neutral")
    assert -5.0 <= analysis.net_sentiment <= 5.0

    # Verify narrative includes key information
    assert "Catalyst analysis:" in output.text
    assert "events identified" in output.text


@pytest.mark.asyncio
async def test_catalyst_analysis_empty_news(mock_deps):
    """_execute_catalyst_analysis handles no news gracefully."""
    from finagent.engine.pipelines.equity_research import _execute_catalyst_analysis
    from finagent.engine.models.financial import CatalystAnalysis, StepOutput

    empty_news_result = DataResult(
        data={"news_items": []},
        provider="fake",
        ticker="AAPL",
        data_type="news",
        timestamp=datetime.now(tz=timezone.utc),
    )
    mock_deps.data_layer.fetch = AsyncMock(return_value=empty_news_result)

    mock_agent = MagicMock()
    with patch(
        "finagent.engine.pipelines.equity_research.classify_news",
        return_value=[],
    ):
        output = await _execute_catalyst_analysis(mock_agent, mock_deps, "prompt", {}, "AAPL")

    assert isinstance(output, StepOutput)
    assert isinstance(output.structured, CatalystAnalysis)
    assert output.structured.events == []
    assert output.structured.net_sentiment == 0.0
    assert output.structured.overall_sentiment == "neutral"


@pytest.mark.asyncio
async def test_catalyst_analysis_net_sentiment_bullish(mock_deps):
    """Net sentiment > 0.5 maps to bullish overall_sentiment."""
    from finagent.engine.pipelines.equity_research import _execute_catalyst_analysis
    from finagent.engine.compute.news import NewsItem

    classified = [
        NewsItem(
            title="Massive earnings beat",
            source="Reuters",
            published=datetime(2024, 6, 1, tzinfo=timezone.utc),
            url="https://example.com/1",
            category="earnings",
            sentiment="positive",
            importance=5,
            summary="Record profits.",
        ),
    ]
    empty_news_result = DataResult(
        data={"news_items": []},
        provider="fake",
        ticker="AAPL",
        data_type="news",
        timestamp=datetime.now(tz=timezone.utc),
    )
    mock_deps.data_layer.fetch = AsyncMock(return_value=empty_news_result)

    mock_agent = MagicMock()
    with patch(
        "finagent.engine.pipelines.equity_research.classify_news",
        return_value=classified,
    ):
        output = await _execute_catalyst_analysis(mock_agent, mock_deps, "prompt", {}, "AAPL")

    # importance=5, probability=0.7, sentiment=positive -> EI = 5*0.7*1 = 3.5 > 0.5
    assert output.structured.overall_sentiment == "bullish"
    assert output.structured.net_sentiment > 0.5


@pytest.mark.asyncio
async def test_catalyst_analysis_net_sentiment_bearish(mock_deps):
    """Net sentiment < -0.5 maps to bearish overall_sentiment."""
    from finagent.engine.pipelines.equity_research import _execute_catalyst_analysis
    from finagent.engine.compute.news import NewsItem

    classified = [
        NewsItem(
            title="Company faces massive lawsuit",
            source="Reuters",
            published=datetime(2024, 6, 1, tzinfo=timezone.utc),
            url="https://example.com/1",
            category="regulatory",
            sentiment="negative",
            importance=5,
            summary="Major legal action.",
        ),
    ]
    empty_news_result = DataResult(
        data={"news_items": []},
        provider="fake",
        ticker="AAPL",
        data_type="news",
        timestamp=datetime.now(tz=timezone.utc),
    )
    mock_deps.data_layer.fetch = AsyncMock(return_value=empty_news_result)

    mock_agent = MagicMock()
    with patch(
        "finagent.engine.pipelines.equity_research.classify_news",
        return_value=classified,
    ):
        output = await _execute_catalyst_analysis(mock_agent, mock_deps, "prompt", {}, "AAPL")

    # importance=5, probability=0.7, sentiment=negative -> EI = 5*0.7*(-1) = -3.5 < -0.5
    assert output.structured.overall_sentiment == "bearish"
    assert output.structured.net_sentiment < -0.5


@pytest.mark.asyncio
async def test_thesis_includes_catalyst_context(mock_deps):
    """_execute_thesis injects catalyst analysis into prompt when available."""
    from finagent.engine.pipelines.equity_research import _execute_thesis
    from finagent.engine.models.financial import (
        CatalystAnalysis,
        CatalystEvent,
        ThesisResult,
        StepOutput,
    )

    catalyst_analysis = CatalystAnalysis(
        events=[
            CatalystEvent(
                category="earnings",
                headline="Strong Q2 earnings beat",
                sentiment="positive",
                impact_score=5,
                probability=0.8,
                reasoning="Revenue exceeded estimates by 15%",
            ),
        ],
        overall_sentiment="bullish",
        key_catalysts=["Strong Q2 earnings beat"],
        net_sentiment=3.5,
        category_breakdown={"earnings": 1},
        top_positive=[
            CatalystEvent(
                category="earnings",
                headline="Strong Q2 earnings beat",
                sentiment="positive",
                impact_score=5,
                probability=0.8,
                reasoning="Revenue exceeded estimates by 15%",
            ),
        ],
        top_negative=[],
    )

    structured_context = {"catalyst_analysis": catalyst_analysis}

    thesis_output = ThesisResult(
        recommendation="Buy",
        price_target=200.0,
        price_target_basis="DCF + peer analysis",
        catalysts=["Strong earnings momentum"],
        risks=["Regulatory risk"],
        narrative="Bullish thesis based on strong fundamentals.",
    )
    mock_thesis_result = MagicMock()
    mock_thesis_result.output = thesis_output
    mock_agent_instance = MagicMock()
    mock_agent_instance.run = AsyncMock(return_value=mock_thesis_result)

    mock_agent = MagicMock()

    with patch(
        "finagent.engine.pipelines.equity_research.Agent",
        return_value=mock_agent_instance,
    ):
        output = await _execute_thesis(
            mock_agent, mock_deps, "base prompt", structured_context, "AAPL"
        )

    assert isinstance(output, StepOutput)
    assert isinstance(output.structured, ThesisResult)

    # Verify catalyst context was injected into the prompt passed to LLM
    actual_prompt = mock_agent_instance.run.call_args[0][0]
    assert "Catalyst Analysis:" in actual_prompt
    assert "Strong Q2 earnings beat" in actual_prompt
    assert "bullish" in actual_prompt


@pytest.mark.asyncio
async def test_thesis_works_without_catalyst_context(mock_deps):
    """_execute_thesis works fine when catalyst_analysis is not in structured_context."""
    from finagent.engine.pipelines.equity_research import _execute_thesis
    from finagent.engine.models.financial import ThesisResult, StepOutput

    thesis_output = ThesisResult(
        recommendation="Hold",
        price_target=150.0,
        price_target_basis="DCF analysis",
        catalysts=["Stable revenue"],
        risks=["Market uncertainty"],
        narrative="Neutral outlook.",
    )
    mock_thesis_result = MagicMock()
    mock_thesis_result.output = thesis_output
    mock_agent_instance = MagicMock()
    mock_agent_instance.run = AsyncMock(return_value=mock_thesis_result)

    mock_agent = MagicMock()

    with patch(
        "finagent.engine.pipelines.equity_research.Agent",
        return_value=mock_agent_instance,
    ):
        output = await _execute_thesis(mock_agent, mock_deps, "base prompt", {}, "AAPL")

    assert isinstance(output, StepOutput)
    assert isinstance(output.structured, ThesisResult)

    # Without catalyst_analysis, prompt should not contain catalyst section
    actual_prompt = mock_agent_instance.run.call_args[0][0]
    assert "Catalyst Analysis:" not in actual_prompt


# ---------------------------------------------------------------------------
# Catalyst validator tests
# ---------------------------------------------------------------------------


def test_validate_catalyst_analysis_passes_valid():
    """validate_catalyst_analysis passes for valid analysis."""
    from finagent.engine.pipelines.validators import validate_catalyst_analysis
    from finagent.engine.models.financial import CatalystAnalysis, CatalystEvent

    analysis = CatalystAnalysis(
        events=[
            CatalystEvent(
                category="earnings",
                headline="Earnings beat",
                sentiment="positive",
                impact_score=4,
                probability=0.8,
                reasoning="Good quarter.",
            ),
        ],
        overall_sentiment="bullish",
        key_catalysts=["Earnings beat"],
        net_sentiment=2.0,
        category_breakdown={"earnings": 1},
        top_positive=[],
        top_negative=[],
    )
    result = validate_catalyst_analysis(analysis)
    assert result.passed is True


def test_validate_catalyst_analysis_fails_empty_events():
    """validate_catalyst_analysis fails when events list is empty."""
    from finagent.engine.pipelines.validators import validate_catalyst_analysis
    from finagent.engine.models.financial import CatalystAnalysis

    analysis = CatalystAnalysis(
        events=[],
        overall_sentiment="neutral",
        key_catalysts=[],
        net_sentiment=0.0,
    )
    result = validate_catalyst_analysis(analysis)
    assert result.passed is False
    assert "No catalyst events" in result.error
