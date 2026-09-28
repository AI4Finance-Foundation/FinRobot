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
        from finrobot.engine.data.interface import ProviderError
        from finrobot.engine.data.normalize.financials import normalize_financials
        from finrobot.engine.data.normalize.price import normalize_price
        from finrobot.engine.data.types import DataType

        dtype = DataType(data_type)
        if dtype not in (DataType.PRICE, DataType.FINANCIALS):
            # 638a8164: FORWARD_ESTIMATES (and any future type) goes through the
            # canonical gate and is unwrapped via .payload() — this fake only
            # speaks the two snapshot contracts, so refuse honestly and let the
            # caller take its tolerated "unavailable" branch instead of handing
            # back a NormalizedFinancials that lacks .payload().
            raise ProviderError(f"no canonical fake for {dtype}")
        raw = await self.fetch(str(data_type), ticker, **kwargs)
        if dtype == DataType.PRICE:
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
        assert step_map["thesis"] == (
            "initiating-coverage",
            "competitive-analysis",
            "thesis-tracker",
        )
        assert step_map["report"] == ("initiating-coverage", "tear-sheet", "equity-research")

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
    # The thesis step's street-context disclosure awaits this (best-effort);
    # None = street band unavailable → no disclosure, step unaffected.
    deps.data_layer.fetch_price_target = AsyncMock(return_value=None)
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
        dtype = DataType(data_type)
        if dtype == DataType.FINANCIALS:
            return norm_fin
        if dtype == DataType.PRICE:
            return norm_price
        # FORWARD_ESTIMATES etc. (638a8164 canonical gate): refuse honestly —
        # the caller's tolerated branch handles it; returning norm_price here
        # would crash on the .payload() unwrap.
        from finrobot.engine.data.interface import ProviderError

        raise ProviderError(f"no canonical fake for {dtype}")

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

    async def _canon(data_type, ticker, **kw):
        from finrobot.engine.data.interface import ProviderError
        from finrobot.engine.data.types import DataType as _DT

        # FORWARD_ESTIMATES (638a8164 canonical gate) is unwrapped via
        # .payload() — refuse it honestly so the enricher takes its tolerated
        # "forward unavailable" branch instead of crashing on norm_fin.
        if _DT(data_type) != _DT.FINANCIALS:
            raise ProviderError(f"no canonical fake for {data_type}")
        return norm_fin

    mock_deps.data_layer.fetch_canonical = AsyncMock(side_effect=_canon)
    # XBRL is still a raw fetch
    mock_deps.data_layer.fetch = AsyncMock(
        return_value=DataResult(
            data={},
            provider="fake",
            ticker="MSFT",
            data_type="xbrl_facts",
            timestamp=datetime.now(tz=timezone.utc),
        )
    )

    mock_agent = MagicMock()

    with pytest.raises(ValueError, match="target FinancialData"):
        await execute_peer_analysis(
            mock_agent, mock_deps, "prompt", {}, "AAPL", peers=["MSFT", "GOOGL", "META"]
        )


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


def test_sensitivity_center_equals_discount_rate_normal():
    """Center cell (index 2) must equal the base discount_rate so the heatmap
    center matches the narrative base-case implied price (BUG-013)."""
    from finrobot.engine.pipelines._helpers import build_sensitivity_ranges

    wacc_range, _ = build_sensitivity_ranges(0.09, 0.025)
    assert wacc_range[2] == pytest.approx(0.09)


def test_sensitivity_center_preserved_for_low_wacc():
    """The old absolute 3% floor clobbered the center when WACC < 3%; the
    terminal-growth-relative floor keeps the center exact (BUG-013)."""
    from finrobot.engine.pipelines._helpers import build_sensitivity_ranges

    # WACC 2%, terminal growth 1% — valid (WACC > g) but below the old 3% floor.
    wacc_range, tg_range = build_sensitivity_ranges(0.02, 0.01)
    assert len(wacc_range) == 5
    assert wacc_range[2] == pytest.approx(0.02), (
        f"center must equal base WACC 0.02, got {wacc_range[2]} (range={wacc_range})"
    )
    # Gordon validity preserved: every terminal-growth candidate stays below the
    # lowest discount rate.
    assert tg_range and all(g < min(wacc_range) for g in tg_range)


# ---------------------------------------------------------------------------
# Catalyst analysis integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_catalyst_analysis_produces_catalyst_analysis_output(mock_deps):
    """_execute_catalyst_analysis returns StepOutput with CatalystAnalysis."""
    from finrobot.engine.pipelines.equity_research import _execute_catalyst_analysis
    from finrobot.engine.models.financial import CatalystAnalysis, StepOutput
    from finrobot.engine.compute.coordinators.news import NewsItem

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
    from finrobot.engine.compute.coordinators.news import NewsItem

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
    from finrobot.engine.compute.coordinators.news import NewsItem

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
                name="dcf",
                low=20.0,
                mid=25.37,
                high=30.4,
                confidence=0.7,
                source="DCF model",
            ),
            ValuationMethod(
                name="ev_ebitda",
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
    # Canonical method ids render as human-readable labels (_method_label), the same
    # labels the football field shows — not the raw snake_case keys.
    assert "DCF" in output.structured.price_target_basis
    assert "EV/EBITDA" in output.structured.price_target_basis

    # And the prompt should have carried the canonical number to the LLM.
    actual_prompt = mock_agent_instance.run.call_args[0][0]
    assert "AUTHORITATIVE PRICE TARGET" in actual_prompt
    assert f"${expected:.2f}" in actual_prompt


def _street_thesis_fixtures():
    """A cooperative LLM thesis + a two-method synthesis whose canonical target
    lands at the weighted price (≈38.95) — reused by the street-context tests."""
    from finrobot.engine.models.financial import (
        ThesisResult,
        ValuationMethod,
        ValuationSynthesis,
    )

    thesis = ThesisResult(
        recommendation="Sell",
        price_target=38.95,
        price_target_basis="synthesis",
        catalysts=["Catalyst A"],
        risks=["Risk A"],
        narrative="Some narrative.",
    )
    vs = ValuationSynthesis(
        methods=[
            ValuationMethod(name="dcf", low=20.0, mid=25.37, high=30.4, confidence=0.7, source="s"),
            ValuationMethod(
                name="ev_ebitda", low=49.3, mid=57.96, high=66.7, confidence=0.5, source="s"
            ),
        ],
        weighted_price=(25.37 * 0.7 + 57.96 * 0.5) / 1.2,  # ≈ 38.95
        current_price=426.01,
        upside_downside=-0.91,
    )
    return thesis, vs


@pytest.mark.asyncio
async def test_thesis_discloses_street_context_when_target_out_of_band(mock_deps):
    """Standing street-context line (2026-07-08, widened 2026-07-09 — BACKLOG
    A9/B1): canonical target entirely below the sell-side range → the fact line
    PLUS the out-of-consensus clause rides the step's warnings (→ report
    compute-warnings section). Verdict/target untouched — disclosure, not gate."""
    from finrobot.engine.pipelines.equity_research import _execute_thesis
    from finrobot.engine.models.financial import StepOutput

    thesis, vs = _street_thesis_fixtures()
    mock_thesis_result = MagicMock()
    mock_thesis_result.output = thesis
    mock_agent_instance = MagicMock()
    mock_agent_instance.run = AsyncMock(return_value=mock_thesis_result)

    street = MagicMock()
    street.data = {"low": 360.0, "high": 480.0, "analyst_count": 42, "consensus": 420.0}
    mock_deps.data_layer.fetch_price_target = AsyncMock(return_value=street)

    with patch(
        "finrobot.engine.pipelines.equity_research.Agent",
        return_value=mock_agent_instance,
    ):
        output = await _execute_thesis(
            mock_agent_instance, mock_deps, "base prompt", {"valuation_synthesis": vs}, "GOOGL"
        )

    assert isinstance(output, StepOutput)
    blob = " ".join(output.warnings)
    assert "Street context" in blob and "below" in blob and "42 analysts" in blob
    assert "consensus $420.00" in blob
    # Pure disclosure: the canonical target is still the weighted synthesis.
    assert output.structured.price_target == round(vs.weighted_price, 2)


@pytest.mark.asyncio
async def test_thesis_street_context_always_on_in_band_silent_when_unavailable(mock_deps):
    """In-band target still shows the standing fact line (no judgment words, no
    out-of-consensus clause); only a failed street fetch stays silent."""
    from finrobot.engine.pipelines.equity_research import _execute_thesis

    thesis, vs = _street_thesis_fixtures()
    mock_thesis_result = MagicMock()
    mock_thesis_result.output = thesis
    mock_agent_instance = MagicMock()
    mock_agent_instance.run = AsyncMock(return_value=mock_thesis_result)

    # In-band: canonical ≈38.95 sits inside the street range → fact line still
    # renders, but with no directional/out-of-consensus language.
    street = MagicMock()
    street.data = {"low": 20.0, "high": 60.0, "analyst_count": 10, "consensus": 40.0}
    mock_deps.data_layer.fetch_price_target = AsyncMock(return_value=street)
    with patch(
        "finrobot.engine.pipelines.equity_research.Agent",
        return_value=mock_agent_instance,
    ):
        output = await _execute_thesis(
            mock_agent_instance, mock_deps, "base prompt", {"valuation_synthesis": vs}, "GOOGL"
        )
    blob = " ".join(output.warnings)
    assert "Street context" in blob and "10 analysts" in blob and "consensus $40.00" in blob
    assert "out-of-consensus" not in blob

    # Unavailable (fetch → None, the augmentation route's degrade contract).
    mock_deps.data_layer.fetch_price_target = AsyncMock(return_value=None)
    with patch(
        "finrobot.engine.pipelines.equity_research.Agent",
        return_value=mock_agent_instance,
    ):
        output = await _execute_thesis(
            mock_agent_instance, mock_deps, "base prompt", {"valuation_synthesis": vs}, "GOOGL"
        )
    assert not any("Street context" in w for w in output.warnings)


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


# ---------------------------------------------------------------------------
# BUG-014: DCF graceful-degrade must not be self-defeated by technical_analysis
# ---------------------------------------------------------------------------


def _low_wacc_financial_data():
    """FinancialData whose seeded DCF degrades (terminal_growth ≥ WACC).

    A low-beta, cash-rich, low-debt profile pushes WACC toward the risk-free
    floor while seed_dcf_inputs picks a terminal growth that meets/exceeds it,
    so calculate_dcf raises (Gordon undefined) and financial_modeling degrades.
    """
    from finrobot.engine.models.financial import (
        BalanceSheet,
        FinancialData,
        IncomeStatement,
        MarketData,
        ValuationMetrics,
    )

    return FinancialData(
        ticker="LOWW",
        company_name="Low WACC Co.",
        timestamp=datetime.now(tz=timezone.utc),
        income=IncomeStatement(
            revenue=10e9,
            ebitda=4e9,
            net_income=3e9,
            gross_margin=0.60,
            operating_margin=0.40,
            interest_expense=1e6,
        ),
        balance=BalanceSheet(total_debt=1e6, total_cash=5e9),
        market=MarketData(
            market_cap=100e9,
            shares_outstanding=1e9,
            current_price=100.0,
            industry="Utilities—Regulated Electric",
            beta=0.05,
        ),
        valuation=ValuationMetrics(),
    )


@pytest.mark.asyncio
async def test_technical_analysis_degrades_when_dcf_unavailable(mock_deps):
    """BUG-014: when financial_modeling degraded (no DCFResult), technical_analysis
    must NOT raise — it returns a degraded TechnicalAnalysis carrying the
    DCF-unavailable marker, so the run continues to a relative-valuation report.
    """
    from finrobot.engine.compute.coordinators.technical_payload import (
        TECHNICAL_DCF_UNAVAILABLE_MARKER,
        TechnicalAnalysis,
    )
    from finrobot.engine.models.financial import StepOutput
    from finrobot.engine.pipelines.equity_research import _execute_technical_analysis
    from finrobot.engine.pipelines.validators import validate_technical_analysis

    # Mirror the degrade path: financial_modeling returned structured=None and
    # never wrote a DCFResult into structured_context.
    ctx: dict[str, object] = {"data_collection": _low_wacc_financial_data()}

    mock_agent = MagicMock()
    output = await _execute_technical_analysis(mock_agent, mock_deps, "prompt", ctx, "LOWW")

    assert isinstance(output, StepOutput)
    assert isinstance(output.structured, TechnicalAnalysis)
    payload = output.structured
    # All three quant overlays skipped (they seed off DCF inputs).
    assert payload.monte_carlo is None
    assert payload.sniper is None
    assert payload.historical_bands is None
    # Explicit marker present, and the validator PASSES on it (no misleading
    # green check, no re-triggered degrade).
    assert TECHNICAL_DCF_UNAVAILABLE_MARKER in payload.warnings
    assert validate_technical_analysis(payload).passed is True


@pytest.mark.asyncio
async def test_low_wacc_run_degrades_to_relative_valuation(mock_deps):
    """BUG-014 integration: when calculate_dcf raises ValueError (the tg≥WACC
    Gordon-undefined case for low-WACC profiles), financial_modeling degrades
    (structured=None, nothing written to ctx) AND the follow-on
    technical_analysis degrades gracefully rather than crashing the run —
    producing a usable (validator-passing) chapter-09 payload off the SAME ctx.
    """
    from finrobot.engine.models.financial import HistoricalMetrics, StepOutput
    from finrobot.engine.pipelines.equity_research import (
        _execute_financial_modeling,
        _execute_technical_analysis,
    )
    from finrobot.engine.pipelines.validators import validate_technical_analysis

    fd = _low_wacc_financial_data()
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
        ticker="LOWW",
    )
    ctx: dict[str, object] = {"data_collection": fd, "historical_metrics": hm}

    mock_agent = MagicMock()

    # Force the Gordon-undefined degrade exactly as a tg≥WACC seed would: the
    # equity_research module calls calculate_dcf, which raises ValueError.
    with patch(
        "finrobot.engine.pipelines.equity_research.calculate_dcf",
        side_effect=ValueError(
            "Terminal growth 0.043 must be less than WACC 0.043 "
            "(Gordon Growth Model perpetuity is undefined when tg >= wacc)"
        ),
    ):
        fm_out = await _execute_financial_modeling(mock_agent, mock_deps, "prompt", ctx, "LOWW")

    # DCF degraded: no DCFResult emitted, nothing written into ctx.
    assert isinstance(fm_out, StepOutput)
    assert fm_out.structured is None
    assert "financial_modeling" not in ctx

    # The next step must NOT crash on the missing DCFResult — it degrades and
    # the validator passes (run continues to a relative-valuation report).
    tech_out = await _execute_technical_analysis(mock_agent, mock_deps, "prompt", ctx, "LOWW")
    assert isinstance(tech_out, StepOutput)
    assert validate_technical_analysis(tech_out.structured).passed is True
    # CONTROL (non-financial): the degrade reason is the generic Gordon-undefined
    # marker only — NOT the balance-sheet-financial category-error reason.
    assert not any("balance-sheet financial" in w for w in tech_out.structured.warnings), (
        "non-financial degrade must not claim the FCFF-DCF is a category error"
    )


def _insurer_financial_data():
    """A USD property & casualty insurer: is_balance_sheet_financial True (risk-carrying
    insurer), is_bank False. USD/USD so financial_modeling's FX normalization is a
    network-free no-op and the is_bank DDM block never runs — the whole path stays
    deterministic and offline for the test."""
    from datetime import datetime, timezone

    from finrobot.engine.models.financial import (
        BalanceSheet,
        FinancialData,
        IncomeStatement,
        MarketData,
        ValuationMetrics,
    )

    return FinancialData(
        ticker="ALL",
        company_name="Allstate",
        timestamp=datetime.now(tz=timezone.utc),
        reporting_currency="USD",
        quote_currency="USD",
        income=IncomeStatement(revenue=5e10, ebitda=8e9, net_income=4e9),
        balance=BalanceSheet(total_debt=8e9, total_cash=6e9),
        market=MarketData(
            market_cap=4.9e10,
            shares_outstanding=2.6e8,
            current_price=190.0,
            industry="Insurance - Property & Casualty",
            sector="Financial Services",
            book_value_per_share=70.0,
        ),
        valuation=ValuationMetrics(),
    )


def _insurer_peer_comps():
    from finrobot.engine.models.financial import CompanyFinancials, PeerComps

    target = CompanyFinancials(
        ticker="ALL",
        name="Allstate",
        revenue=5e10,
        ebitda=8e9,
        net_income=4e9,
        market_cap=4.9e10,
        total_debt=8e9,
        total_cash=6e9,
        book_value_per_share=70.0,
        pb_ratio=1.3,
        pe_ratio=12.0,
    )
    peers = [
        target.model_copy(update={"ticker": t, "pb_ratio": 1.2, "pe_ratio": 12.5})
        for t in ("PGR", "TRV", "CB")
    ]
    return PeerComps(
        target=target, peers=peers, median_pb=1.2, pb_sample_n=4, median_pe=12.5, pe_sample_n=4
    )


@pytest.mark.asyncio
async def test_financial_modeling_withholds_fcff_for_balance_sheet_financial(mock_deps):
    """P1-5 (2026-07-02): a bank / insurer report leaked a full FCFF-DCF — the synthesis
    suppressed the METHOD row, but the raw DCFResult still rendered the 10y EBITDA/FCF
    trajectory + terminal value + EV + implied price in the financial chapter, seeded the
    technical chapter's Monte Carlo (a DCF distribution) and drew an EV/EBITDA band. The
    source-enforce gate withholds the ENTIRE FCFF-DCF for a balance-sheet financial: no
    DCFResult is computed or written, a machine-readable reason surfaces, and the
    football field is still built from the bank/insurer methods (financial_sector flag
    set for the frontend). is_balance_sheet_financial covers insurers too (is_bank does
    not) — the P&C insurer here confirms the wider boundary and needs no DDM/network."""
    from finrobot.engine.models.financial import (
        HistoricalMetrics,
        StepOutput,
        ValuationSynthesis,
    )
    from finrobot.engine.pipelines.equity_research import _execute_financial_modeling

    fd = _insurer_financial_data()
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
        ticker="ALL",
    )
    ctx: dict[str, object] = {
        "data_collection": fd,
        "historical_metrics": hm,
        "peer_analysis": _insurer_peer_comps(),
    }

    out = await _execute_financial_modeling(MagicMock(), mock_deps, "prompt", ctx, "ALL")

    # No DCFResult — the entire cash-flow projection is withheld at the source…
    assert isinstance(out, StepOutput)
    assert out.structured is None
    assert "financial_modeling" not in ctx
    # …with a machine-readable reason (carries the surfacing marker)…
    assert out.warnings and "method withheld" in out.warnings[0]
    assert "category error" in out.warnings[0]
    # …and the football field is still built from the insurer's P/B · P/E, flagged
    # financial_sector so the frontend frames the absent DCF panels as not-applicable.
    vs = ctx.get("valuation_synthesis")
    assert isinstance(vs, ValuationSynthesis)
    assert vs.financial_sector is True
    assert "dcf" not in {m.name for m in vs.methods}
    assert {m.name for m in vs.methods} <= {"comps_pb", "comps_pe"}


@pytest.mark.asyncio
async def test_technical_analysis_reason_is_category_error_for_financial(mock_deps):
    """The bank/insurer technical degrade must read as a category error (the Monte Carlo
    is a DCF distribution, the EV/EBITDA band an enterprise-value multiple — both
    ill-defined for a balance-sheet financial), carrying a 'method withheld' reason —
    NOT the generic 'Gordon undefined / re-run' framing a low-WACC non-financial gets.
    Same all-None payload, validator still passes; only the reason differs by issuer."""
    from finrobot.engine.models.financial import StepOutput
    from finrobot.engine.pipelines.equity_research import _execute_technical_analysis
    from finrobot.engine.pipelines.validators import validate_technical_analysis

    # No DCFResult in ctx (financial_modeling withheld) + an insurer data_collection.
    ctx: dict[str, object] = {"data_collection": _insurer_financial_data()}
    out = await _execute_technical_analysis(MagicMock(), mock_deps, "prompt", ctx, "ALL")
    assert isinstance(out, StepOutput)
    assert out.structured.monte_carlo is None
    assert out.structured.sniper is None
    assert out.structured.historical_bands is None
    assert validate_technical_analysis(out.structured).passed is True
    assert any(
        "balance-sheet financial" in w and "method withheld" in w for w in out.structured.warnings
    ), f"financial degrade must state the category error: {out.structured.warnings}"


def _twd_local_financial_data():
    """A locally-listed TWD issuer: reporting_currency == quote_currency == TWD.

    Magnitudes mirror a TSMC-like local listing — NT$ revenue/debt, an NT$~1000
    quote, NT$ market cap. The FX-drift bug (BUG-073, second leg) bites exactly
    this shape: financial_modeling normalizes a LOCAL copy to USD and seeds the
    DCF from USD, but the un-normalized TWD snapshot used to leak forward into
    technical_analysis / EV-EBITDA / synthesis.
    """
    from datetime import datetime, timezone

    from finrobot.engine.models.financial import (
        BalanceSheet,
        FinancialData,
        IncomeStatement,
        MarketData,
        ValuationMetrics,
    )

    return FinancialData(
        ticker="2330.TW",
        company_name="TSMC (local listing)",
        timestamp=datetime.now(tz=timezone.utc),
        reporting_currency="TWD",
        quote_currency="TWD",
        income=IncomeStatement(
            revenue=2_160e9,
            ebitda=1_400e9,
            net_income=850e9,
            gross_margin=0.53,
            operating_margin=0.42,
            interest_expense=4e9,
        ),
        balance=BalanceSheet(total_debt=900e9, total_cash=1_500e9),
        market=MarketData(
            market_cap=26_000e9,
            shares_outstanding=25.9e9,
            current_price=1000.0,
            price_52w_high=1100.0,
            price_52w_low=600.0,
            industry="Semiconductors",
            beta=1.05,
        ),
        valuation=ValuationMetrics(),
    )


@pytest.mark.asyncio
async def test_foreign_issuer_technical_analysis_consumes_usd_not_native_currency(mock_deps):
    """BUG-073 (caliber drift, second leg): for a locally-listed NON-USD issuer
    (reporting_currency == quote_currency == TWD), technical_analysis must consume
    a current_price in the SAME currency as the USD-seeded dcf_target — never the
    native TWD quote.

    Production-live shape: drive the REAL pipeline functions
    (_execute_financial_modeling → _execute_technical_analysis) end-to-end, with
    only the FX spot read patched deterministically (32 TWD/USD). Asserts:

    1. data_collection is rewritten to USD after financial_modeling (single
       currency for every downstream consumer);
    2. the dcf_target the sniper anchors to is USD;
    3. the sniper's price levels land in USD magnitude (~US$30), NOT the native
       NT$~1000 — proving load_price_history's native bars were FX-scaled.

    A live-shaped assertion (not a fixture echo): a fixture that hard-coded both
    legs already USD would pass even with the bug present. Forcing reporting ==
    quote == TWD through the real normalize→seed→technical chain is what makes
    this catch a regression of either leg (snapshot write-back OR price-history
    scaling).
    """
    from datetime import date, timedelta

    from finrobot.engine.compute.coordinators.technical_payload import TechnicalAnalysis
    from finrobot.engine.models.financial import DCFResult, FinancialData, HistoricalMetrics
    from finrobot.engine.pipelines.equity_research import (
        _execute_financial_modeling,
        _execute_technical_analysis,
    )
    from finrobot.engine.primitives.historical_valuation import PricePoint

    twd_per_usd = 32.0

    async def _fixed_fx(currency, *, fmp_api_key=None):
        return 1.0 / twd_per_usd if currency.upper() == "TWD" else 1.0

    # Native-currency 1y price path (real PricePoint dataclasses, as
    # load_price_history returns) around the NT$1000 quote.
    base = date(2026, 1, 1)
    twd_bars = [
        PricePoint(sample_date=base + timedelta(days=i), close=float(c))
        for i, c in enumerate((900, 950, 1000, 1050, 980, 1010, 1000, 990, 1020, 1000))
    ]

    mock_deps.settings.fmp_api_key = None
    # Bands leg hits the data layer; stub to empty so it degrades (band is a
    # dimensionless ratio anyway — currency-invariant, not the leg under test).
    mock_deps.data_layer.fetch_historical = AsyncMock(return_value=[])
    mock_deps.data_layer.fetch_price_range = AsyncMock(return_value=[])

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
        ticker="2330.TW",
    )
    ctx: dict[str, object] = {
        "data_collection": _twd_local_financial_data(),
        "historical_metrics": hm,
    }
    mock_agent = MagicMock()

    with (
        patch(
            "finrobot.engine.data.providers.fx.fetch_fx_rate_to_usd",
            side_effect=_fixed_fx,
        ),
        patch(
            "finrobot.engine.pipelines.equity_research.fetch_fx_rate_to_usd",
            side_effect=_fixed_fx,
        ),
        patch(
            "finrobot.engine.compute.coordinators.technical_payload.load_price_history",
            new=AsyncMock(return_value=twd_bars),
        ),
    ):
        fm_out = await _execute_financial_modeling(mock_agent, mock_deps, "p", ctx, "2330.TW")
        dcf = ctx.get("financial_modeling")
        assert isinstance(dcf, DCFResult), f"DCF degraded unexpectedly: {fm_out.warnings}"

        # (1) data_collection rewritten to USD — single currency downstream.
        stored = ctx["data_collection"]
        assert isinstance(stored, FinancialData)
        assert stored.reporting_currency == "USD"
        assert stored.quote_currency == "USD"
        # current_price collapsed from NT$1000 to ~US$31 (1000 / 32).
        assert stored.market.current_price == pytest.approx(1000.0 / twd_per_usd, rel=1e-6)

        # (2) the dcf_target the sniper anchors to is USD.
        assert dcf.inputs.currency == "USD"

        # FX factor stamped for the price-history leg.
        assert ctx.get("price_fx_to_usd") == pytest.approx(1.0 / twd_per_usd, rel=1e-6)

        tech_out = await _execute_technical_analysis(mock_agent, mock_deps, "p", ctx, "2330.TW")

    payload = tech_out.structured
    assert isinstance(payload, TechnicalAnalysis)

    # (3) sniper levels are USD magnitude (~US$30), NOT native NT$~1000. If the
    # price history had leaked native TWD, support/resistance would be ~1000.
    assert payload.sniper is not None
    assert payload.sniper.support_level < 100.0
    assert payload.sniper.resistance_level < 100.0
    # Resistance = rolling max of the FX-scaled price series (max close NT$1050 →
    # ~US$32.8). The native NT$ levels (≥900) never leak through.
    assert payload.sniper.resistance_level == pytest.approx(1050.0 / twd_per_usd, abs=0.5)
    assert payload.sniper.support_level == pytest.approx(900.0 / twd_per_usd, abs=0.5)

    # Monte Carlo is seeded from USD dcf_inputs + USD current_price; its mean is
    # USD magnitude, not NT$ — a single-currency MC distribution.
    assert payload.monte_carlo is not None
    assert payload.monte_carlo.mean < 100.0


# ---------------------------------------------------------------------------
# Critical-1: the STANDALONE dcf / ddm pipelines must write the USD-normalized
# snapshot back to historical_data (the key the artifact builder reads for
# entry_price), exactly as equity_research does via data_collection. Without it
# a foreign issuer's entry_price stays native (NT$1000) while the DCF/DDM target
# is USD (~$31) → coverage signal / hit-rate compares cross-currency.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_standalone_dcf_writes_usd_snapshot_back_to_historical_data(mock_deps):
    """A TWD local listing (reporting == quote == TWD) through the REAL
    _execute_dcf_calc, FX patched to 32 TWD/USD. After the step, historical_data
    must hold the USD snapshot (current_price ~US$31), not the native NT$1000 —
    so build_dcf_artifact's entry_price agrees with the USD implied_price."""
    from finrobot.engine.models.financial import DCFResult, FinancialData, HistoricalMetrics
    from finrobot.engine.pipelines.dcf import _execute_dcf_calc

    twd_per_usd = 32.0

    async def _fixed_fx(currency, *, fmp_api_key=None):
        return 1.0 / twd_per_usd if currency.upper() == "TWD" else 1.0

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
        ticker="2330.TW",
    )
    mock_deps.settings.fmp_api_key = None
    ctx: dict[str, object] = {"historical_data": _twd_local_financial_data()}

    with (
        patch(
            "finrobot.engine.data.providers.fx.fetch_fx_rate_to_usd",
            side_effect=_fixed_fx,
        ),
        patch(
            "finrobot.engine.pipelines.dcf.fetch_historical_metrics",
            new=AsyncMock(return_value=hm),
        ),
    ):
        out = await _execute_dcf_calc(MagicMock(), mock_deps, "p", ctx, "2330.TW")

    stored = ctx["historical_data"]
    assert isinstance(stored, FinancialData)
    assert stored.reporting_currency == "USD"
    assert stored.quote_currency == "USD"
    assert stored.market.current_price == pytest.approx(1000.0 / twd_per_usd, rel=1e-6)
    if isinstance(out.structured, DCFResult):
        assert out.structured.inputs.currency == "USD"


@pytest.mark.asyncio
async def test_standalone_dcf_us_issuer_historical_data_unchanged(mock_deps):
    """US issuer (USD == USD): normalize_financials_to_usd is a no-op, so the
    write-back must not perturb the snapshot."""
    from finrobot.engine.models.financial import (
        BalanceSheet,
        FinancialData,
        HistoricalMetrics,
        IncomeStatement,
        MarketData,
        ValuationMetrics,
    )
    from finrobot.engine.pipelines.dcf import _execute_dcf_calc

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
    mock_deps.settings.fmp_api_key = None
    original = FinancialData(
        ticker="AAPL",
        company_name="Apple Inc.",
        timestamp=datetime.now(tz=timezone.utc),
        reporting_currency="USD",
        quote_currency="USD",
        income=IncomeStatement(
            revenue=4e11,
            ebitda=1.3e11,
            net_income=1e11,
            gross_margin=0.46,
            operating_margin=0.3,
            interest_expense=3e9,
        ),
        balance=BalanceSheet(total_debt=1e11, total_cash=6e10),
        market=MarketData(
            market_cap=3e12,
            shares_outstanding=1.5e10,
            current_price=200.0,
            industry="Consumer Electronics",
            beta=1.2,
        ),
        valuation=ValuationMetrics(),
    )
    ctx: dict[str, object] = {"historical_data": original}

    with patch(
        "finrobot.engine.pipelines.dcf.fetch_historical_metrics",
        new=AsyncMock(return_value=hm),
    ):
        await _execute_dcf_calc(MagicMock(), mock_deps, "p", ctx, "AAPL")

    stored = ctx["historical_data"]
    assert isinstance(stored, FinancialData)
    assert stored.quote_currency == "USD"
    assert stored.market.current_price == pytest.approx(original.market.current_price, rel=1e-9)


@pytest.mark.asyncio
async def test_standalone_ddm_writes_usd_snapshot_back_to_historical_data(mock_deps):
    """DDM leg of Critical-1: _execute_ddm_params (the seed step) normalizes a
    foreign dividend payer to USD but must write the USD snapshot back to
    historical_data, else build_ddm_artifact's entry_price stays native while
    equity_value_per_share is USD."""
    from finrobot.engine.data.normalize.contracts import NormalizedFinancials, Provenance
    from finrobot.engine.models.financial import FinancialData
    from finrobot.engine.pipelines.ddm import _execute_ddm_seed

    twd_per_usd = 32.0

    async def _fixed_fx(currency, *, fmp_api_key=None):
        return 1.0 / twd_per_usd if currency.upper() == "TWD" else 1.0

    now = datetime.now(tz=timezone.utc)
    norm_twd = NormalizedFinancials(
        ticker="2330.TW",
        revenue=2_160e9,
        market_cap=26_000e9,
        as_of=now,
        net_income=850e9,
        shares_outstanding=25.9e9,
        current_price=1000.0,
        dividend_per_share=30.0,
        payout_ratio=0.5,
        return_on_equity=0.25,
        book_value_per_share=120.0,
        beta=1.05,
        industry="Semiconductors",
        sector="Technology",
        provenance=Provenance(provider="yfinance", as_of=now, fetched_at=now),
    )
    mock_deps.settings.fmp_api_key = None
    mock_deps.data_layer.fetch_canonical = AsyncMock(return_value=norm_twd)
    ctx: dict[str, object] = {"historical_data": _twd_local_financial_data()}

    with patch(
        "finrobot.engine.pipelines.ddm.fetch_fx_rate_to_usd",
        side_effect=_fixed_fx,
    ):
        await _execute_ddm_seed(MagicMock(), mock_deps, "p", ctx, "2330.TW")

    stored = ctx["historical_data"]
    assert isinstance(stored, FinancialData)
    assert stored.reporting_currency == "USD"
    assert stored.quote_currency == "USD"
    assert stored.market.current_price == pytest.approx(1000.0 / twd_per_usd, rel=1e-6)


@pytest.mark.asyncio
async def test_standalone_lbo_normalizes_to_usd_and_writes_back(mock_deps):
    """#3: the standalone LBO pipeline fed the native-currency snapshot straight
    to seed_lbo_inputs (no normalize), so a foreign issuer's revenue_base /
    ltm_ebitda — documented "(USD)" — and the LBOResult exit_equity / ending_debt
    were reporting-currency (TWD). The football field then divides exit_equity by
    share count and plots it against a USD current_price (mixed currency, same
    BUG-073 family). ic_memo / equity_research normalize before seeding; the
    standalone LBO must too, and write the USD snapshot back to data_collection
    (build_lbo_artifact's raw_data → entry_price)."""
    from finrobot.engine.models.financial import FinancialData, HistoricalMetrics, LBOInputs
    from finrobot.engine.pipelines.lbo import _execute_lbo_params

    twd_per_usd = 32.0

    async def _fixed_fx(currency, *, fmp_api_key=None):
        return 1.0 / twd_per_usd if currency.upper() == "TWD" else 1.0

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
        ticker="2330.TW",
    )
    mock_deps.settings.fmp_api_key = None
    ctx: dict[str, object] = {
        "data_collection": _twd_local_financial_data(),
        "historical_metrics": hm,
    }

    with patch(
        "finrobot.engine.data.providers.fx.fetch_fx_rate_to_usd",
        side_effect=_fixed_fx,
    ):
        out = await _execute_lbo_params(MagicMock(), mock_deps, "p", ctx, "2330.TW")

    # (1) data_collection rewritten to USD (entry_price basis matches the model).
    stored = ctx["data_collection"]
    assert isinstance(stored, FinancialData)
    assert stored.reporting_currency == "USD"
    assert stored.quote_currency == "USD"
    assert stored.market.current_price == pytest.approx(1000.0 / twd_per_usd, rel=1e-6)

    # (2) the seed consumed USD: revenue_base collapsed from NT$2,160B to ~US$67.5B.
    inputs = out.structured
    assert isinstance(inputs, LBOInputs)
    assert inputs.revenue_base == pytest.approx(2_160e9 / twd_per_usd, rel=1e-6)
    assert inputs.ltm_ebitda == pytest.approx(1_400e9 / twd_per_usd, rel=1e-6)


# ---------------------------------------------------------------------------
# BUG-015: recoverable AgentRunError must propagate (not be wrapped into
# non-recoverable ValueError that defeats base.py's retry-by-type)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_thesis_propagates_agent_run_error(mock_deps):
    """BUG-015: an AgentRunError inside _execute_thesis propagates as
    AgentRunError (recoverable), NOT re-wrapped into ValueError."""
    from pydantic_ai.exceptions import AgentRunError

    from finrobot.engine.pipelines.equity_research import _execute_thesis

    mock_agent_instance = MagicMock()
    mock_agent_instance.run = AsyncMock(side_effect=AgentRunError("rate limit (429)"))
    mock_agent = MagicMock()

    with patch(
        "finrobot.engine.pipelines.equity_research.Agent",
        return_value=mock_agent_instance,
    ):
        with pytest.raises(AgentRunError):
            await _execute_thesis(mock_agent, mock_deps, "base prompt", {}, "AAPL")


@pytest.mark.asyncio
async def test_thesis_wraps_validation_error_as_value_error(mock_deps):
    """BUG-015: a ValidationError (deterministic schema failure) stays wrapped as
    a non-recoverable ValueError — retrying it would only burn budget."""
    from pydantic import ValidationError

    from finrobot.engine.models.financial import ThesisResult
    from finrobot.engine.pipelines.equity_research import _execute_thesis

    try:
        ThesisResult(recommendation="Buy")  # missing required fields → ValidationError
    except ValidationError as ve:
        validation_error = ve

    mock_agent_instance = MagicMock()
    mock_agent_instance.run = AsyncMock(side_effect=validation_error)
    mock_agent = MagicMock()

    with patch(
        "finrobot.engine.pipelines.equity_research.Agent",
        return_value=mock_agent_instance,
    ):
        with pytest.raises(ValueError, match="failed to produce valid thesis"):
            await _execute_thesis(mock_agent, mock_deps, "base prompt", {}, "AAPL")


@pytest.mark.asyncio
async def test_deterministic_peer_selection_uses_candidate_screen(mock_deps):
    """Default peer selection consumes the provider candidate pool and pure screen.

    NVDA regression: a same-industry but wrong-value-chain supplier (TSM foundry)
    must be rejected before it can move comps_pe.
    """
    from finrobot.engine.data.interface import DataResult
    from finrobot.engine.data.types import DataType
    from finrobot.engine.pipelines._helpers import _deterministic_select_peers

    payload = {
        "profile": {
            "company_name": "NVIDIA Corporation",
            "sector": "Technology",
            "industry": "Semiconductors",
            "market_cap": 3_000_000_000_000,
            "description": "Provides GPUs and data center platforms for AI accelerated computing.",
        },
        "industry_screen": ["TSM", "ASML", "AVGO", "AMD", "QCOM"],
        "stock_peers": [],
        "sector_screen": [],
        "quotes": {
            "TSM": {"market_cap": 1_300_000_000_000, "pe": 25.0},
            "ASML": {"market_cap": 350_000_000_000, "pe": 35.0},
            "AVGO": {"market_cap": 1_100_000_000_000, "pe": 38.0},
            "AMD": {"market_cap": 260_000_000_000, "pe": 42.0},
            "QCOM": {"market_cap": 180_000_000_000, "pe": 16.0},
        },
        "profiles": {
            "TSM": {
                "industry": "Semiconductors",
                "description": "Manufactures, packages, tests, and sells integrated circuits; wafer fabrication.",
            },
            "ASML": {
                "industry": "Semiconductors",
                "description": "Develops semiconductor equipment systems, including lithography.",
            },
            "AVGO": {
                "industry": "Semiconductors",
                "description": "Designs, develops and supplies semiconductor solutions.",
            },
            "AMD": {
                "industry": "Semiconductors",
                "description": "Develops microprocessors, chipsets and discrete GPUs.",
            },
            "QCOM": {
                "industry": "Semiconductors",
                "description": "Develops and supplies integrated circuits and system software.",
            },
        },
    }
    mock_deps.data_layer.fetch = AsyncMock(
        return_value=DataResult(
            data=payload,
            provider="fmp",
            ticker="NVDA",
            data_type=DataType.PEER_CANDIDATES,
            timestamp=datetime.now(tz=timezone.utc),
        )
    )

    selection = await _deterministic_select_peers(mock_deps, "NVDA")

    assert selection.tickers == ["AVGO", "AMD", "QCOM"]
    assert "TSM" not in selection.tickers
    assert "role-dropped 2" in selection.rationale


@pytest.mark.asyncio
async def test_peer_analysis_excludes_target_and_names_dropped_peers(mock_deps):
    """execute_peer_analysis (1) never lists the target as its own comp even when
    the caller includes it, and (2) NAMES every dropped peer in the warnings so a
    comp lost to a transient fetch/FX failure is visibly accounted for rather than
    silently swapped."""
    from datetime import datetime, timezone

    from finrobot.engine.data.normalize.financials import normalize_financials
    from finrobot.engine.models.financial import (
        BalanceSheet,
        FinancialData,
        IncomeStatement,
        MarketData,
        ValuationMetrics,
    )
    from finrobot.engine.pipelines._helpers import execute_peer_analysis

    def _mk_norm(t: str):
        return normalize_financials(
            DataResult(
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
                ticker=t,
                data_type="financials",
                timestamp=datetime.now(tz=timezone.utc),
            )
        )

    async def _canon(_dt, t, **kw):
        from finrobot.engine.data.interface import ProviderError
        from finrobot.engine.data.types import DataType as _DT

        if _DT(_dt) != _DT.FINANCIALS:
            # FORWARD_ESTIMATES (638a8164): refuse honestly — the enricher's
            # tolerated branch handles it; a NormalizedFinancials has no .payload().
            raise ProviderError(f"no canonical fake for {_dt}")
        if t == "FAILME":
            raise ValueError("simulated FX rate-limit for FAILME")
        # If target-dedup regressed, AAPL would be fetched here and leak into peers.
        return _mk_norm(t)

    mock_deps.data_layer.fetch_canonical = AsyncMock(side_effect=_canon)
    mock_deps.data_layer.fetch = AsyncMock(
        return_value=DataResult(
            data={},
            provider="fake",
            ticker="x",
            data_type="xbrl_facts",
            timestamp=datetime.now(tz=timezone.utc),
        )
    )
    mock_deps.settings.fmp_api_key = None  # keep FX a no-op (all USD)

    target_fd = FinancialData(
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
    ctx = {"data_collection": target_fd}

    mock_agent = MagicMock()
    out = await execute_peer_analysis(
        mock_agent,
        mock_deps,
        "prompt",
        ctx,
        "AAPL",
        peers=["AAPL", "MSFT", "GOOGL", "META", "FAILME"],
    )

    peer_comps = out.structured
    peer_tickers = {p.ticker.upper() for p in peer_comps.peers}
    # (1) target excluded from its own comp set
    assert "AAPL" not in peer_tickers
    assert peer_tickers == {"MSFT", "GOOGL", "META"}
    # (2) the dropped peer is named, not silent
    assert any("FAILME" in w for w in peer_comps.warnings)


@pytest.mark.asyncio
async def test_peer_analysis_drops_non_positive_revenue_peer_keeps_rest(mock_deps):
    """A structurally-invalid peer (non-positive revenue — a preferred/non-operating
    listing whose bank net-revenue caliber went negative, or a provider glitch) is
    dropped INDIVIDUALLY and named, and the remaining peers still compute a median —
    it no longer fails the WHOLE set (C/MER-PK comps crash, 2026-07-02)."""
    from datetime import datetime, timezone

    from finrobot.engine.data.normalize.financials import normalize_financials
    from finrobot.engine.models.financial import (
        BalanceSheet,
        FinancialData,
        IncomeStatement,
        MarketData,
        ValuationMetrics,
    )
    from finrobot.engine.pipelines._helpers import execute_peer_analysis

    def _mk_norm(t: str, revenue: float):
        return normalize_financials(
            DataResult(
                data=dict(
                    revenue=revenue,
                    ebitda=15e9,
                    net_income=10e9,
                    gross_margin=0.40,
                    operating_margin=0.25,
                    pe_ratio=20.0,
                    market_cap=2e11,  # P/E = 2e11 / 10e9 net income = 20x (under the NM cap)
                    shares_outstanding=5e9,
                    current_price=100.0,
                    total_debt=10e9,
                    total_cash=5e9,
                ),
                provider="yfinance",
                ticker=t,
                data_type="financials",
                timestamp=datetime.now(tz=timezone.utc),
            )
        )

    async def _canon(_dt, t, **kw):
        from finrobot.engine.data.interface import ProviderError
        from finrobot.engine.data.types import DataType as _DT

        if _DT(_dt) != _DT.FINANCIALS:
            raise ProviderError(f"no canonical fake for {_dt}")
        # PREFPK simulates a preferred listing whose bank net-revenue caliber is
        # negative — present (so extract does NOT raise), just non-positive.
        return _mk_norm(t, -5e9 if t == "PREFPK" else 50e9)

    mock_deps.data_layer.fetch_canonical = AsyncMock(side_effect=_canon)
    mock_deps.data_layer.fetch = AsyncMock(
        return_value=DataResult(
            data={},
            provider="fake",
            ticker="x",
            data_type="xbrl_facts",
            timestamp=datetime.now(tz=timezone.utc),
        )
    )
    mock_deps.settings.fmp_api_key = None

    target_fd = FinancialData(
        ticker="C",
        company_name="Citigroup Inc.",
        timestamp=datetime.now(tz=timezone.utc),
        income=IncomeStatement(revenue=88e9, ebitda=26e9, net_income=16e9, interest_expense=83e9),
        balance=BalanceSheet(total_debt=749e9, total_cash=23e9),
        market=MarketData(
            market_cap=239e9,
            shares_outstanding=1.7e9,
            current_price=139.0,
            industry="Banks - Diversified",
        ),
        valuation=ValuationMetrics(),
    )
    ctx = {"data_collection": target_fd}

    out = await execute_peer_analysis(
        MagicMock(),
        mock_deps,
        "prompt",
        ctx,
        "C",
        peers=["WFC", "MUFG", "TD", "RY", "PREFPK"],
    )
    peer_comps = out.structured
    peer_tickers = {p.ticker.upper() for p in peer_comps.peers}
    # The bad peer is gone; the healthy 4 survive and a median is computed.
    assert "PREFPK" not in peer_tickers
    assert peer_tickers == {"WFC", "MUFG", "TD", "RY"}
    assert peer_comps.median_pe is not None
    # ... and it is NAMED (not silently swapped), with the reason.
    assert any("PREFPK" in w and "non-positive revenue" in w for w in peer_comps.warnings)


def test_override_empty_canonical_withholds_llm_target():
    """When EVERY valuation method degrades (resolve_canonical_thesis's empty
    branch: no synthesis → verdict=None, target=None), the LLM's own
    price_target — a fact field with zero code backing — must NOT pass through:
    summary_extractor treats thesis.price_target as authoritative for the
    coverage signal. The override forces the target None and defaults the verdict
    to a neutral HOLD (never the deleted REVIEW)."""
    from finrobot.engine.compute.operators.valuation_synthesis import CanonicalThesis
    from finrobot.engine.models.financial import ThesisResult
    from finrobot.engine.pipelines.equity_research import apply_canonical_override

    rogue = ThesisResult(
        recommendation="Buy",
        price_target=123.45,  # pure LLM fabrication — nothing computed it
        price_target_basis="Gut feel dressed as synthesis",
        catalysts=["c"],
        risks=["r"],
        narrative="n",
    )
    empty = CanonicalThesis(
        target=None, verdict=None, basis=None, upside=None, valuation_withheld=False
    )

    out = apply_canonical_override(rogue, empty, vs=None)

    # Verdict is directional (defaults to HOLD), never REVIEW; the LLM target is
    # scrubbed to None.
    assert out.recommendation == "HOLD"
    assert out.price_target is None
    assert out.price_target_basis is not None
    assert "withheld" in out.price_target_basis


def test_override_withheld_point_scrubs_smuggled_prose_amount():
    """The withheld-point path MUST run the narrative reconciler too (it used to
    run only on the publish path). With the structured target forced None, an LLM
    that smuggles a fair-value $-amount into prose must have it erased to the
    [target withheld] marker — a per-method mid and the market price stay citable."""
    from finrobot.engine.compute.operators.valuation_synthesis import CanonicalThesis
    from finrobot.engine.models.financial import (
        ThesisResult,
        ValuationMethod,
        ValuationSynthesis,
    )
    from finrobot.engine.pipelines.equity_research import apply_canonical_override

    rogue = ThesisResult(
        recommendation="Sell",
        price_target=33.0,  # smuggled point — must be nulled
        price_target_basis="DCF says fair value is $33.00",  # smuggled prose amount
        catalysts=["c"],
        risks=["r"],
        narrative="We peg fair value at $33.00 despite the $406.00 market.",
        valuation_overview="Blending methods we reach about $33.00.",
    )
    # very_low / point withheld (TSLA option-value regime).
    vs = ValuationSynthesis(
        methods=[
            ValuationMethod(name="dcf", low=30, mid=33.0, high=36, confidence=0.7, source="DCF"),
            ValuationMethod(name="comps_pe", low=22, mid=24.0, high=27, confidence=0.7, source="C"),
        ],
        weighted_price=28.5,
        current_price=406.0,
        upside_downside=-0.93,
        confidence="very_low",
        valuation_withheld=True,
    )
    canonical = CanonicalThesis(
        target=None,
        verdict="SELL",
        basis="POINT TARGET WITHHELD (confidence=very_low).",
        upside=-0.92,
        valuation_withheld=True,
        confidence="very_low",
    )

    out = apply_canonical_override(rogue, canonical, vs=vs)

    assert out.recommendation == "SELL"  # directional, never REVIEW
    assert out.price_target is None
    # The smuggled fair-value "$33.00" in prose (a point, not a per-method mid
    # cited as such — 33 IS the dcf mid, so it survives; 28.5 weighted would not)
    # — verify the market price ($406.00) and the per-method mid ($33.00) survive,
    # while a smuggled NON-whitelisted amount is erased. Inject one to prove it.
    rogue2 = rogue.model_copy(
        update={"valuation_overview": "Our point estimate is $99.99 fair value."}
    )
    out2 = apply_canonical_override(rogue2, canonical, vs=vs)
    assert "$99.99" not in (out2.valuation_overview or "")
    assert "[target withheld]" in (out2.valuation_overview or "")


async def test_thesis_single_method_out_of_band_withholds_point_keeps_direction(mock_deps):
    """The 2026-06-05 TSLA live artifact: comps died (all-EV peer set, P/E n=0)
    → single-method synthesis (weighted_price=None) → the LLM stamped SELL $20.38
    on a 0.05x model/market ratio. The dial now withholds the POINT (the only
    number would be the market price in costume) while STILL issuing a directional
    verdict: target forced None, recommendation directional (never the deleted
    REVIEW), and the prompt carries the point-withheld instruction."""
    from finrobot.engine.pipelines.equity_research import _execute_thesis
    from finrobot.engine.models.financial import (
        ThesisResult,
        StepOutput,
        ValuationMethod,
        ValuationSynthesis,
    )

    rogue = ThesisResult(
        recommendation="Sell",
        price_target=20.38,  # the live bug: DCF mid published as headline target
        price_target_basis="Based on the DCF model",
        catalysts=["c"],
        risks=["r"],
        narrative="n",
    )
    mock_result = MagicMock()
    mock_result.output = rogue
    agent = MagicMock()
    agent.run = AsyncMock(return_value=mock_result)

    # synthesize_valuations would set confidence=very_low / valuation_withheld=True
    # for this single-method 0.049x case; build the same shape directly.
    vs = ValuationSynthesis(
        methods=[
            ValuationMethod(
                name="dcf", low=15.0, mid=20.38, high=25.0, confidence=0.85, source="DCF"
            )
        ],
        weighted_price=None,  # single method — no cross-check
        current_price=418.45,  # ratio 0.049 — far outside [0.25, 4]
        upside_downside=None,
        confidence="very_low",
        valuation_withheld=True,
    )

    with patch(
        "finrobot.engine.pipelines.equity_research.Agent",
        return_value=agent,
    ):
        output = await _execute_thesis(
            agent, mock_deps, "base prompt", {"valuation_synthesis": vs}, "TSLA"
        )

    assert isinstance(output, StepOutput)
    thesis = output.structured
    assert isinstance(thesis, ThesisResult)
    # Directional verdict (never the deleted REVIEW); the point is withheld.
    assert thesis.recommendation in ("BUY", "HOLD", "SELL")
    assert thesis.price_target is None, (
        f"single-method out-of-band mid must NOT publish a target, got {thesis.price_target}"
    )
    # The prompt must have carried the point-withheld instruction (not a gate).
    prompt = agent.run.call_args[0][0]
    assert "POINT PRICE TARGET WITHHELD" in prompt
    assert "REVIEW" not in prompt


@pytest.mark.asyncio
async def test_thesis_single_method_in_band_publishes_with_caveat(mock_deps):
    """Banks legitimately run comps-only (DCF structurally n/a): a single method
    whose mid sits INSIDE the calibration band publishes as the canonical target
    — deterministic, with an explicit single-method/no-cross-check caveat — so
    JPM-class names keep coverage instead of degrading to REVIEW."""
    from finrobot.engine.pipelines.equity_research import _execute_thesis
    from finrobot.engine.models.financial import (
        ThesisResult,
        ValuationMethod,
        ValuationSynthesis,
    )

    rogue = ThesisResult(
        recommendation="Buy",
        price_target=999.0,  # LLM drift — must be overridden to the method mid
        price_target_basis="vibes",
        catalysts=["c"],
        risks=["r"],
        narrative="n",
    )
    mock_result = MagicMock()
    mock_result.output = rogue
    agent = MagicMock()
    agent.run = AsyncMock(return_value=mock_result)

    # Mirror what synthesize_valuations produces for a single in-band method:
    # confidence=medium, point published (not withheld), a widened band + a
    # no-cross-check degradation note.
    vs = ValuationSynthesis(
        methods=[
            ValuationMethod(
                name="comps_pe", low=250.0, mid=289.57, high=330.0, confidence=0.55, source="Comps"
            )
        ],
        weighted_price=None,
        current_price=310.89,  # ratio 0.93 — comfortably in-band
        upside_downside=None,
        confidence="medium",
        target_low=217.18,
        target_high=361.96,
        valuation_withheld=False,
        degradation_note="single method comps_pe with no cross-validation — band widened, confidence medium.",
    )

    with patch(
        "finrobot.engine.pipelines.equity_research.Agent",
        return_value=agent,
    ):
        output = await _execute_thesis(
            agent, mock_deps, "base prompt", {"valuation_synthesis": vs}, "JPM"
        )

    thesis = output.structured
    assert isinstance(thesis, ThesisResult)
    assert thesis.price_target == 289.57, (
        f"in-band single-method mid must become the canonical target, got {thesis.price_target}"
    )
    # -6.9% upside → HOLD (medium-tier SELL needs -35%).
    assert thesis.recommendation == "HOLD"
    # Basis must disclose the single-method / no-cross-check caliber.
    assert "no cross-validation" in thesis.price_target_basis
    prompt = agent.run.call_args[0][0]
    assert "AUTHORITATIVE PRICE TARGET" in prompt


class TestSec8kCatalystMateriality:
    """8-K → catalyst conversion must drop filing-mechanics (earnings-release
    Item 2.02 / exhibits 9.01) and only surface MATERIAL events with a readable
    label. Regression for the 2026-06-09 TSLA report: 8 identical content-free
    'SEC 8-K filed: Item 2.02, Item 9.01' stubs flooded the catalyst list."""

    def test_material_codes_drops_routine_keeps_material(self):
        from finrobot.engine.pipelines.equity_research import _material_8k_codes

        # Bare earnings release → all routine → no material codes.
        assert _material_8k_codes(["Item 2.02", "Item 9.01"]) == []
        # Annual-meeting mechanics → routine.
        assert _material_8k_codes(["Item 5.07", "Item 9.01"]) == []
        # Exec change → material.
        assert _material_8k_codes(["Item 5.02", "Item 9.01"]) == ["5.02"]
        # Material agreement → material.
        assert _material_8k_codes(["Item 1.01", "Item 9.01"]) == ["1.01"]
        # Already-bare codes tolerated.
        assert _material_8k_codes(["5.02"]) == ["5.02"]

    def test_8k_to_catalyst_uses_descriptive_headline(self):
        from finrobot.engine.pipelines.equity_research import _sec_8k_to_catalyst

        event = {
            "items": ["Item 5.02", "Item 9.01"],
            "filing_date": "2025-11-07",
            "accession_no": "0001104659-25-108507",
        }
        cat = _sec_8k_to_catalyst(event)
        # Readable label, not a bare item number; routine 9.01 omitted.
        assert cat.headline == "SEC 8-K: Executive / director change"
        assert cat.category == "management"

    def test_material_agreement_categorized_acquisition(self):
        from finrobot.engine.pipelines.equity_research import _sec_8k_to_catalyst

        cat = _sec_8k_to_catalyst({"items": ["Item 1.01", "Item 9.01"]})
        assert cat.category == "acquisition"
        assert "Material agreement entered" in cat.headline
