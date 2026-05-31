from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from finrobot.engine.data.interface import DataResult
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.pipelines.equity_research import create_equity_research_pipeline


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

    async def fetch_canonical(self, data_type, ticker, **kwargs):
        """Return NormalizedFinancials / NormalizedPrice (ADR-0006 canonical contract)."""
        from finrobot.engine.data.normalize.financials import normalize_financials
        from finrobot.engine.data.normalize.price import normalize_price
        from finrobot.engine.data.types import DataType

        raw = await self.fetch(str(data_type), ticker, **kwargs)
        if DataType(data_type) == DataType.PRICE:
            return normalize_price(raw)
        return normalize_financials(raw)

    async def fetch_historical(self, data_type: str, ticker: str, years: int = 5, **kwargs):
        return []


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
            TestModel(custom_output_text=output), deps_type=FinRobotDeps, defer_model_check=True
        )
    return agents


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------


class TestPipelineStructure:
    def test_has_exactly_8_steps(self):
        pipeline = create_equity_research_pipeline(_make_test_agents())
        assert len(pipeline.steps) == 8

    def test_step_names_correct(self):
        pipeline = create_equity_research_pipeline(_make_test_agents())
        names = [s.name for s in pipeline.steps]
        assert names == [
            "data_collection",
            "catalyst_analysis",
            "peer_analysis",
            "financial_modeling",
            "ownership_governance_analysis",
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
        assert step_map["ownership_governance_analysis"] is None
        assert step_map["technical_analysis"] is None
        assert step_map["thesis"] == "initiating-coverage"
        assert step_map["report"] is None

    def test_step1_required_data(self):
        # Only FINANCIALS + PRICE feed the narrative prompt. SEC filings are
        # fetched by the executor into structured_context, NOT dumped raw into
        # the prompt (a 10-K's tripled section text overflowed gpt-4o's 128k
        # window and crashed the run). NEWS belongs to catalyst_analysis.
        pipeline = create_equity_research_pipeline(_make_test_agents())
        step1 = pipeline.steps[0]
        assert "financials" in step1.required_data
        assert "price" in step1.required_data
        # Heavyweight / redundant types must NOT be in the prompt-feeding list.
        assert "news" not in step1.required_data
        assert "filings_10k" not in step1.required_data
        assert "filings_10q" not in step1.required_data
        assert "filings_8k" not in step1.required_data
        assert "xbrl_facts" not in step1.required_data

    def test_steps_2_to_8_required_data_empty(self):
        pipeline = create_equity_research_pipeline(_make_test_agents())
        for step in pipeline.steps[1:]:
            assert step.required_data == []

    def test_ownership_step_accepts_structured_model(self):
        from datetime import datetime, timezone

        from finrobot.engine.models.sec import OwnershipGovernanceAnalysis

        pipeline = create_equity_research_pipeline(_make_test_agents())
        step = next(s for s in pipeline.steps if s.name == "ownership_governance_analysis")
        result = step.validator(
            OwnershipGovernanceAnalysis(
                generated_at=datetime.now(tz=timezone.utc),
                degraded_sections=["institutional_holdings"],
            )
        )
        assert result.passed is True

    def test_ownership_step_rejects_empty_structured_model(self):
        from datetime import datetime, timezone

        from finrobot.engine.models.sec import OwnershipGovernanceAnalysis

        pipeline = create_equity_research_pipeline(_make_test_agents())
        step = next(s for s in pipeline.steps if s.name == "ownership_governance_analysis")
        result = step.validator(
            OwnershipGovernanceAnalysis(generated_at=datetime.now(tz=timezone.utc))
        )
        assert result.passed is False
        assert result.error is not None
        assert "no data" in result.error

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
    from finrobot.engine.models.financial import StepOutput

    async def _stub(agent, deps, prompt, structured_context, ticker):
        return StepOutput(
            text=f"{step_name} stub output revenue ebitda AAPL MSFT GOOG peers buy hold sell risk catalyst price target"
        )

    return _stub


class TestPipelineExecution:
    async def test_execute_produces_result_with_all_8_step_keys(self, capsys):
        """Pipeline orchestration routes through all 8 steps and collects their outputs."""
        pipeline = create_equity_research_pipeline(
            _make_test_agents("revenue 385B ebitda 130B price_history available")
        )
        # Stub executor to avoid real compute in unit test of orchestration
        from finrobot.engine.pipelines.base import TextValidator
        from finrobot.engine.pipelines.validators import validate_is_non_empty

        for step in pipeline.steps:
            step.executor = _make_stub_execute_fn(step.name)
            step.validator = TextValidator(validate_is_non_empty)
        result = await pipeline.execute(FakeDeps(), "AAPL")
        assert set(result.steps.keys()) == {
            "data_collection",
            "catalyst_analysis",
            "peer_analysis",
            "financial_modeling",
            "ownership_governance_analysis",
            "technical_analysis",
            "thesis",
            "report",
        }

    async def test_execute_logs_8_progress_messages(self, caplog):
        import logging

        with caplog.at_level(logging.INFO):
            pipeline = create_equity_research_pipeline(
                _make_test_agents("revenue 385B ebitda 130B price_history available")
            )
            # Stub executor to avoid real compute in unit test of orchestration
            from finrobot.engine.pipelines.base import TextValidator
            from finrobot.engine.pipelines.validators import validate_is_non_empty

            for step in pipeline.steps:
                step.executor = _make_stub_execute_fn(step.name)
                step.validator = TextValidator(validate_is_non_empty)
            await pipeline.execute(FakeDeps(), "AAPL")
        messages = " ".join(r.message for r in caplog.records)
        for i in range(1, 9):
            assert f"Step {i}/8" in messages


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
    """Step 1 data_collection execute_fn returns StepOutput with FinancialData.

    ADR-0006 Step 4: execute_financial_data_step calls fetch_canonical, so the
    mock returns NormalizedFinancials / NormalizedPrice (wrapped via normalize_*).
    """
    from finrobot.engine.data.normalize.financials import normalize_financials
    from finrobot.engine.data.normalize.price import normalize_price
    from finrobot.engine.pipelines._helpers import execute_financial_data_step
    from finrobot.engine.models.financial import FinancialData, StepOutput

    fin_raw = DataResult(
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
    price_raw = DataResult(
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
    norm_fin = normalize_financials(fin_raw)
    norm_price = normalize_price(price_raw)

    mock_agent = MagicMock()
    mock_result = MagicMock()
    mock_result.output = "Analysis text"
    mock_agent.run = AsyncMock(return_value=mock_result)

    from finrobot.engine.data.types import DataType

    async def mock_fetch_canonical(data_type, ticker):
        return norm_fin if DataType(data_type) == DataType.FINANCIALS else norm_price

    mock_deps.data_layer.fetch_canonical = mock_fetch_canonical
    # fetch_historical is still raw; return empty to skip HistoricalMetrics build.
    mock_deps.data_layer.fetch_historical = AsyncMock(return_value=[])

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

    from finrobot.engine.models.financial import (
        BalanceSheet,
        DCFResult,
        FinancialData,
        HistoricalMetrics,
        IncomeStatement,
        MarketData,
        ValuationMetrics,
    )
    from finrobot.engine.pipelines.equity_research import _execute_financial_modeling

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
async def test_peer_analysis_raises_when_target_financials_missing(mock_deps):
    """execute_peer_analysis (shared, in _helpers) raises ValueError when no
    target FinancialData is present in structured_context (any step key)."""
    from finrobot.engine.pipelines._helpers import execute_peer_analysis
    from finrobot.engine.models.financial import PeerSelection

    mock_peer_result = MagicMock()
    mock_peer_result.output = PeerSelection(
        tickers=["MSFT", "GOOGL", "META"],
        rationale="Large-cap tech peers",
    )
    mock_agent_instance = MagicMock()
    mock_agent_instance.run = AsyncMock(return_value=mock_peer_result)

    # fetch_canonical returns NormalizedFinancials so _fetch_one_peer succeeds
    # for all 3 tickers; the test expects that the code then raises "target
    # FinancialData" because structured_context is empty (no prior data step).
    from finrobot.engine.data.interface import DataResult
    from finrobot.engine.data.normalize.financials import normalize_financials

    fin_raw = DataResult(
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
    norm_fin = normalize_financials(fin_raw)
    mock_deps.data_layer.fetch_canonical = AsyncMock(return_value=norm_fin)
    # XBRL is still a raw fetch
    mock_deps.data_layer.fetch = AsyncMock(
        return_value=DataResult(
            data={}, provider="fake", ticker="MSFT",
            data_type="xbrl_facts", timestamp=datetime.now(tz=timezone.utc),
        )
    )

    mock_agent = MagicMock()

    with patch("finrobot.engine.pipelines._helpers.Agent", return_value=mock_agent_instance):
        with pytest.raises(ValueError, match="target FinancialData"):
            await execute_peer_analysis(mock_agent, mock_deps, "prompt", {}, "AAPL")


def test_build_sensitivity_ranges_returns_valid_ranges():
    """build_sensitivity_ranges returns non-empty tg_range that stays below min(rate_range)."""
    from finrobot.engine.pipelines._helpers import build_sensitivity_ranges

    wacc_range, tg_range = build_sensitivity_ranges(0.09, 0.025)

    assert len(wacc_range) == 5
    assert len(tg_range) >= 1
    min_wacc = min(wacc_range)
    assert all(g < min_wacc for g in tg_range), (
        f"All tg values must be < min_wacc {min_wacc}, got {tg_range}"
    )


# ---------------------------------------------------------------------------
# Catalyst analysis integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_catalyst_analysis_produces_catalyst_analysis_output(mock_deps):
    """_execute_catalyst_analysis returns StepOutput with CatalystAnalysis."""
    from finrobot.engine.pipelines.equity_research import _execute_catalyst_analysis
    from finrobot.engine.models.financial import CatalystAnalysis, StepOutput
    from finrobot.engine.compute.news import NewsItem

    _now = datetime.now(tz=timezone.utc)
    news_result = DataResult(
        data={
            "news_items": [
                {
                    "title": "AAPL beats earnings estimates",
                    "source": "Reuters",
                    "published": (_now - timedelta(days=1)).isoformat(),
                    "url": "https://example.com/1",
                },
                {
                    "title": "New iPhone launch drives revenue growth",
                    "source": "Bloomberg",
                    "published": (_now - timedelta(days=2)).isoformat(),
                    "url": "https://example.com/2",
                },
                {
                    "title": "AAPL faces regulatory probe in EU",
                    "source": "FT",
                    "published": (_now - timedelta(days=3)).isoformat(),
                    "url": "https://example.com/3",
                },
            ]
        },
        provider="fake",
        ticker="AAPL",
        data_type="news",
        timestamp=_now,
    )

    # Mock fetch_news to return raw news from our DataResult
    mock_deps.data_layer.fetch = AsyncMock(return_value=news_result)

    # Mock classify_news to return pre-classified items
    classified = [
        NewsItem(
            title="AAPL beats earnings estimates",
            source="Reuters",
            published=_now - timedelta(days=1),
            url="https://example.com/1",
            category="earnings",
            sentiment="positive",
            importance=5,
            summary="Apple exceeds analyst expectations for Q2.",
        ),
        NewsItem(
            title="New iPhone launch drives revenue growth",
            source="Bloomberg",
            published=_now - timedelta(days=2),
            url="https://example.com/2",
            category="product",
            sentiment="positive",
            importance=4,
            summary="iPhone 16 sales surpass initial projections.",
        ),
        NewsItem(
            title="AAPL faces regulatory probe in EU",
            source="FT",
            published=_now - timedelta(days=3),
            url="https://example.com/3",
            category="regulatory",
            sentiment="negative",
            importance=3,
            summary="EU opens antitrust investigation into Apple.",
        ),
    ]

    mock_agent = MagicMock()
    with patch(
        "finrobot.engine.pipelines.equity_research.classify_news",
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
    from finrobot.engine.pipelines.equity_research import _execute_catalyst_analysis
    from finrobot.engine.models.financial import CatalystAnalysis, StepOutput

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
        "finrobot.engine.pipelines.equity_research.classify_news",
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
    from finrobot.engine.pipelines.equity_research import _execute_catalyst_analysis
    from finrobot.engine.compute.news import NewsItem

    _now = datetime.now(tz=timezone.utc)
    classified = [
        NewsItem(
            title="Massive earnings beat",
            source="Reuters",
            published=_now - timedelta(days=1),
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
        timestamp=_now,
    )
    mock_deps.data_layer.fetch = AsyncMock(return_value=empty_news_result)

    mock_agent = MagicMock()
    with patch(
        "finrobot.engine.pipelines.equity_research.classify_news",
        return_value=classified,
    ):
        output = await _execute_catalyst_analysis(mock_agent, mock_deps, "prompt", {}, "AAPL")

    # importance=5, probability=0.7, sentiment=positive -> EI = 5*0.7*1 = 3.5 > 0.5
    assert output.structured.overall_sentiment == "bullish"
    assert output.structured.net_sentiment > 0.5


@pytest.mark.asyncio
async def test_catalyst_analysis_net_sentiment_bearish(mock_deps):
    """Net sentiment < -0.5 maps to bearish overall_sentiment."""
    from finrobot.engine.pipelines.equity_research import _execute_catalyst_analysis
    from finrobot.engine.compute.news import NewsItem

    _now = datetime.now(tz=timezone.utc)
    classified = [
        NewsItem(
            title="Company faces massive lawsuit",
            source="Reuters",
            published=_now - timedelta(days=1),
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
        timestamp=_now,
    )
    mock_deps.data_layer.fetch = AsyncMock(return_value=empty_news_result)

    mock_agent = MagicMock()
    with patch(
        "finrobot.engine.pipelines.equity_research.classify_news",
        return_value=classified,
    ):
        output = await _execute_catalyst_analysis(mock_agent, mock_deps, "prompt", {}, "AAPL")

    # importance=5, probability=0.7, sentiment=negative -> EI = 5*0.7*(-1) = -3.5 < -0.5
    assert output.structured.overall_sentiment == "bearish"
    assert output.structured.net_sentiment < -0.5


@pytest.mark.asyncio
async def test_thesis_includes_catalyst_context(mock_deps):
    """_execute_thesis injects catalyst analysis into prompt when available."""
    from finrobot.engine.pipelines.equity_research import _execute_thesis
    from finrobot.engine.models.financial import (
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
        "finrobot.engine.pipelines.equity_research.Agent",
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
async def test_thesis_overrides_llm_target_with_valuation_synthesis(mock_deps):
    """Regression: same inputs MUST produce same target price across runs.

    Before this guard the LLM was free to pick a number, so two consecutive
    runs of the same TSLA pipeline returned $25.37 and $57.96 — DCF mid in
    one, Comps mid in the other, never the actual confidence-weighted
    synthesis. The thesis step now overrides whatever the LLM returned with
    ``valuation_synthesis.weighted_price`` so the artifact's
    ``thesis.price_target`` is traceable to a deterministic function call,
    per the CLAUDE.md core contract.
    """
    from finrobot.engine.pipelines.equity_research import _execute_thesis
    from finrobot.engine.models.financial import (
        ThesisResult,
        StepOutput,
        ValuationMethod,
        ValuationSynthesis,
    )

    # The LLM tries to invent a target. The code must overrule it.
    rogue_thesis = ThesisResult(
        recommendation="Sell",
        price_target=57.96,  # Comps standalone — would be the buggy old output
        price_target_basis="Comps median",
        catalysts=["Catalyst A"],
        risks=["Risk A"],
        narrative="Some narrative.",
    )
    mock_thesis_result = MagicMock()
    mock_thesis_result.output = rogue_thesis
    mock_agent_instance = MagicMock()
    mock_agent_instance.run = AsyncMock(return_value=mock_thesis_result)

    # vs computed by code — the only legitimate source of truth.
    vs = ValuationSynthesis(
        methods=[
            ValuationMethod(
                name="DCF",
                low=20.0,
                mid=25.37,
                high=30.4,
                confidence=0.7,
                source="DCF model",
            ),
            ValuationMethod(
                name="EV/EBITDA Comps",
                low=49.3,
                mid=57.96,
                high=66.7,
                confidence=0.5,
                source="Peer median",
            ),
        ],
        weighted_price=(25.37 * 0.7 + 57.96 * 0.5) / 1.2,  # ≈ 38.95
        current_price=426.01,
        upside_downside=-0.91,
    )

    with patch(
        "finrobot.engine.pipelines.equity_research.Agent",
        return_value=mock_agent_instance,
    ):
        output = await _execute_thesis(
            mock_agent_instance,
            mock_deps,
            "base prompt",
            {"valuation_synthesis": vs},
            "TSLA",
        )

    assert isinstance(output, StepOutput)
    assert isinstance(output.structured, ThesisResult)
    # Target MUST be the weighted synthesis, not the LLM's rogue choice.
    expected = round(vs.weighted_price, 2)
    assert output.structured.price_target == expected, (
        f"thesis.price_target={output.structured.price_target} differs from "
        f"valuation_synthesis.weighted_price={expected} — LLM drift not caught"
    )
    # And the basis must cite the synthesis, not the rogue LLM justification.
    assert "weighted" in output.structured.price_target_basis.lower()
    assert "DCF" in output.structured.price_target_basis
    assert "EV/EBITDA Comps" in output.structured.price_target_basis

    # And the prompt should have carried the canonical number to the LLM.
    actual_prompt = mock_agent_instance.run.call_args[0][0]
    assert "AUTHORITATIVE PRICE TARGET" in actual_prompt
    assert f"${expected:.2f}" in actual_prompt


@pytest.mark.asyncio
async def test_thesis_overrides_llm_recommendation_with_upside_thresholds(mock_deps):
    """Recommendation MUST be a deterministic function of upside vs current.

    Same asymmetry as ``price_target`` — without this guard a strong-SELL
    synthesis (-91% upside) could come back from the LLM as Hold/Buy
    depending on the model's mood, and two consecutive runs of the same
    pipeline would disagree on the verdict. Thresholds (±15%) match
    sell-side equity-research convention.
    """
    from finrobot.engine.pipelines.equity_research import _execute_thesis
    from finrobot.engine.models.financial import (
        ThesisResult,
        StepOutput,
        ValuationMethod,
        ValuationSynthesis,
    )

    rogue_thesis = ThesisResult(
        recommendation="Hold",  # rogue; -91% upside must classify as SELL
        price_target=38.95,
        price_target_basis="Whatever the LLM said",
        catalysts=["X"],
        risks=["Y"],
        narrative="...",
    )
    mock_thesis_result = MagicMock()
    mock_thesis_result.output = rogue_thesis
    mock_agent_instance = MagicMock()
    mock_agent_instance.run = AsyncMock(return_value=mock_thesis_result)

    vs = ValuationSynthesis(
        methods=[
            ValuationMethod(
                name="DCF",
                low=20.0,
                mid=25.37,
                high=30.4,
                confidence=0.7,
                source="DCF",
            ),
        ],
        weighted_price=38.95,
        current_price=426.01,
        upside_downside=-0.9086,  # < -15% → SELL
    )

    with patch(
        "finrobot.engine.pipelines.equity_research.Agent",
        return_value=mock_agent_instance,
    ):
        output = await _execute_thesis(
            mock_agent_instance, mock_deps, "p", {"valuation_synthesis": vs}, "TSLA"
        )

    assert isinstance(output, StepOutput)
    assert isinstance(output.structured, ThesisResult)
    assert output.structured.recommendation == "SELL", (
        f"recommendation={output.structured.recommendation} — LLM drift not caught"
    )
    # And the prompt should have signalled SELL to the LLM.
    actual_prompt = mock_agent_instance.run.call_args[0][0]
    assert "AUTHORITATIVE RECOMMENDATION" in actual_prompt
    assert "SELL" in actual_prompt


@pytest.mark.asyncio
async def test_thesis_recommendation_hold_band(mock_deps):
    """Upside within ±15% must classify as HOLD even if LLM picks BUY/SELL."""
    from finrobot.engine.pipelines.equity_research import _execute_thesis
    from finrobot.engine.models.financial import (
        ThesisResult,
        ValuationMethod,
        ValuationSynthesis,
    )

    rogue_thesis = ThesisResult(
        recommendation="Buy",
        price_target=110.0,
        price_target_basis="X",
        catalysts=["A"],
        risks=["B"],
        narrative="...",
    )
    mock_thesis_result = MagicMock()
    mock_thesis_result.output = rogue_thesis
    mock_agent_instance = MagicMock()
    mock_agent_instance.run = AsyncMock(return_value=mock_thesis_result)

    vs = ValuationSynthesis(
        methods=[
            ValuationMethod(
                name="DCF",
                low=90,
                mid=110,
                high=130,
                confidence=0.7,
                source="DCF",
            )
        ],
        weighted_price=110.0,
        current_price=100.0,
        upside_downside=0.10,  # +10% → HOLD
    )

    with patch(
        "finrobot.engine.pipelines.equity_research.Agent",
        return_value=mock_agent_instance,
    ):
        output = await _execute_thesis(
            mock_agent_instance, mock_deps, "p", {"valuation_synthesis": vs}, "FOO"
        )

    assert output.structured.recommendation == "HOLD"


@pytest.mark.asyncio
async def test_thesis_works_without_catalyst_context(mock_deps):
    """_execute_thesis works fine when catalyst_analysis is not in structured_context."""
    from finrobot.engine.pipelines.equity_research import _execute_thesis
    from finrobot.engine.models.financial import ThesisResult, StepOutput

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
        "finrobot.engine.pipelines.equity_research.Agent",
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
    from finrobot.engine.pipelines.validators import validate_catalyst_analysis
    from finrobot.engine.models.financial import CatalystAnalysis, CatalystEvent

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
    from finrobot.engine.pipelines.validators import validate_catalyst_analysis
    from finrobot.engine.models.financial import CatalystAnalysis

    analysis = CatalystAnalysis(
        events=[],
        overall_sentiment="neutral",
        key_catalysts=[],
        net_sentiment=0.0,
    )
    result = validate_catalyst_analysis(analysis)
    assert result.passed is False
    assert "No catalyst events" in result.error
