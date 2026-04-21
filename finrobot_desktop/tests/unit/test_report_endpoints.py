"""Tests for report endpoint cache wiring (N9 fix).

Verifies:
- Cache hit → real HTML with data from structured pipeline results
- Cache miss → 404 with guidance message
- build_report_context correctly extracts typed models from PipelineResult
"""

from datetime import datetime, timezone

import httpx
import pytest
from httpx import ASGITransport

from finagent.engine.models.financial import (
    BalanceSheet,
    CompanyFinancials,
    DCFInputs,
    DCFResult,
    FinancialData,
    IncomeStatement,
    MarketData,
    PeerComps,
    ThesisResult,
    ValuationMetrics,
)
from finagent.engine.orchestrator import build_report_context
from finagent.engine.pipelines.base import PipelineResult
from finagent.server import app


def _make_financial_data(ticker: str = "AAPL") -> FinancialData:
    return FinancialData(
        ticker=ticker,
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
        income=IncomeStatement(
            revenue=400e9,
            ebitda=130e9,
            net_income=100e9,
            gross_margin=0.45,
            operating_margin=0.30,
        ),
        balance=BalanceSheet(
            total_debt=120e9,
            total_cash=60e9,
        ),
        market=MarketData(
            market_cap=3e12,
            shares_outstanding=15e9,
            current_price=200.0,
        ),
    )


def _make_dcf_result() -> DCFResult:
    inputs = DCFInputs(
        revenue_base=400e9,
        revenue_growth_rates=[0.08, 0.06, 0.05],
        ebitda_margin=0.32,
        capex_pct_revenue=0.05,
        nwc_pct_revenue=0.02,
        tax_rate=0.21,
        risk_free_rate=0.04,
        beta=1.1,
        equity_risk_premium=0.06,
        cost_of_debt=0.05,
        debt_ratio=0.3,
        terminal_growth_rate=0.025,
        shares_outstanding=15e9,
        net_debt=60e9,
    )
    return DCFResult(
        cost_of_equity=0.106,
        wacc=0.088,
        projection_years=3,
        projected_revenue=[432e9, 457.9e9, 480.8e9],
        projected_ebitda=[138.2e9, 146.5e9, 153.9e9],
        projected_fcf=[80e9, 85e9, 89e9],
        terminal_value=2.5e12,
        pv_terminal=1.9e12,
        pv_fcf_total=220e9,
        enterprise_value=2.12e12,
        equity_value=2.06e12,
        implied_price=137.33,
        inputs=inputs,
    )


def _make_peer_comps() -> PeerComps:
    target = CompanyFinancials(
        ticker="AAPL", revenue=400e9, ebitda=130e9, net_income=100e9,
        market_cap=3e12, gross_margin=0.45, operating_margin=0.30,
    )
    peers = [
        CompanyFinancials(
            ticker="MSFT", revenue=220e9, ebitda=100e9, net_income=80e9,
            market_cap=2.8e12, gross_margin=0.70, operating_margin=0.42,
        ),
        CompanyFinancials(
            ticker="GOOGL", revenue=300e9, ebitda=90e9, net_income=70e9,
            market_cap=1.8e12, gross_margin=0.57, operating_margin=0.28,
        ),
        CompanyFinancials(
            ticker="META", revenue=130e9, ebitda=55e9, net_income=40e9,
            market_cap=1.2e12, gross_margin=0.80, operating_margin=0.35,
        ),
    ]
    return PeerComps(
        target=target, peers=peers,
        peer_justification="Large-cap tech peers with similar scale.",
        median_ev_ebitda=22.5, median_pe=28.0,
    )


def _make_thesis() -> ThesisResult:
    return ThesisResult(
        recommendation="Buy",
        price_target=230.0,
        price_target_basis="DCF base case + 10% premium for ecosystem moat",
        catalysts=["iPhone 16 cycle", "Services revenue growth"],
        risks=["China regulatory risk", "Hardware margin pressure"],
        narrative="Strong buy on expanding services margin.",
    )


def _make_equity_research_result() -> PipelineResult:
    """Simulate a full equity research pipeline result."""
    return PipelineResult(
        steps={
            "data_collection": "Revenue: $400B...",
            "peer_analysis": "Peer set: MSFT, GOOGL, META...",
            "financial_modeling": "DCF implies $137.33...",
            "thesis": "Buy with $230 target...",
            "report": "Full report narrative...",
        },
        structured_data={
            "data_collection": _make_financial_data(),
            "peer_analysis": _make_peer_comps(),
            "financial_modeling": _make_dcf_result(),
            "thesis": _make_thesis(),
        },
    )


# --- build_report_context tests ---


class TestBuildReportContext:
    def test_equity_research_extracts_all_fields(self):
        result = _make_equity_research_result()
        ctx = build_report_context("aapl", result)

        assert ctx["ticker"] == "AAPL"
        assert ctx["current_price"] == 200.0
        assert ctx["market_cap"] == 3e12
        assert ctx["recommendation"] == "Buy"
        assert ctx["price_target"] == 230.0
        assert isinstance(ctx["dcf_result"], DCFResult)
        assert isinstance(ctx["peer_comps"], PeerComps)
        assert ctx["dcf_result"].implied_price == 137.33
        assert len(ctx["peer_comps"].peers) == 3

    def test_charts_generated_from_structured_data(self):
        """Charts dict must contain base64 PNGs when structured data is present."""
        from finagent.engine.models.financial import HistoricalMetrics

        hm = HistoricalMetrics(
            years=[2020, 2021, 2022, 2023],
            revenue=[260e9, 274e9, 366e9, 394e9],
            revenue_growth_yoy=[None, 0.054, 0.336, 0.077],
            cogs=[170e9, 180e9, 220e9, 240e9],
            gross_profit=[90e9, 94e9, 146e9, 154e9],
            gross_margin=[0.346, 0.343, 0.399, 0.391],
            sga=[20e9, 21e9, 25e9, 26e9],
            sga_ratio=[0.077, 0.077, 0.068, 0.066],
            ebitda=[80e9, 85e9, 130e9, 135e9],
            ebitda_margin=[0.308, 0.310, 0.355, 0.343],
            operating_income=[60e9, 64e9, 105e9, 110e9],
            operating_margin=[0.231, 0.234, 0.287, 0.279],
            net_income=[50e9, 55e9, 95e9, 100e9],
            eps=[3.28, 3.69, 6.15, 6.42],
            pe_ratio=[32.0, 38.0, 25.0, 30.0],
            cagr_revenue=0.149,
            ticker="AAPL",
        )
        result = PipelineResult(
            steps={
                "data_collection": "...",
                "peer_analysis": "...",
                "financial_modeling": "...",
                "thesis": "...",
            },
            structured_data={
                "data_collection": _make_financial_data(),
                "historical_metrics": hm,
                "peer_analysis": _make_peer_comps(),
                "financial_modeling": _make_dcf_result(),
                "thesis": _make_thesis(),
            },
        )
        ctx = build_report_context("aapl", result)
        charts = ctx["charts"]
        assert isinstance(charts, dict)
        # Should have generated charts from HistoricalMetrics
        assert "revenue_ebitda" in charts, f"Missing revenue_ebitda, got: {list(charts.keys())}"
        assert "margin_trend" in charts
        assert "revenue_yoy" in charts
        # From PeerComps
        assert "peer_comparison" in charts
        # All values should be base64 data URIs
        for name, uri in charts.items():
            assert uri.startswith("data:image/png;base64,"), f"Chart {name} not a data URI"

    def test_charts_empty_when_no_structured_data(self):
        """No charts generated when structured_data is empty."""
        result = PipelineResult(steps={"report": "text"}, structured_data={})
        ctx = build_report_context("AAPL", result)
        assert ctx["charts"] == {}

    def test_dcf_only_pipeline(self):
        result = PipelineResult(
            steps={"historical_data": "...", "dcf_calc": "...", "output_gen": "..."},
            structured_data={
                "historical_data": _make_financial_data(),
                "dcf_calc": _make_dcf_result(),
            },
        )
        ctx = build_report_context("AAPL", result)

        assert isinstance(ctx["dcf_result"], DCFResult)
        assert ctx["peer_comps"] is None
        assert ctx["recommendation"] == "N/A"
        assert ctx["current_price"] == 200.0

    def test_comps_only_pipeline(self):
        result = PipelineResult(
            steps={"target_data": "...", "statistical_bench": "...", "output_gen": "..."},
            structured_data={
                "target_data": _make_financial_data(),
                "statistical_bench": _make_peer_comps(),
            },
        )
        ctx = build_report_context("aapl", result)

        assert isinstance(ctx["peer_comps"], PeerComps)
        assert ctx["dcf_result"] is None
        assert ctx["current_price"] == 200.0

    def test_empty_structured_data(self):
        result = PipelineResult(
            steps={"report": "some text"},
            structured_data={},
        )
        ctx = build_report_context("AAPL", result)

        assert ctx["ticker"] == "AAPL"
        assert ctx["current_price"] == 0
        assert ctx["recommendation"] == "N/A"
        assert ctx["dcf_result"] is None
        assert ctx["peer_comps"] is None

    def test_ticker_uppercased(self):
        result = PipelineResult(steps={}, structured_data={})
        ctx = build_report_context("aapl", result)
        assert ctx["ticker"] == "AAPL"

    def test_lbo_pipeline_extracts_inputs_and_result(self):
        """D3-root: LBOInputs and LBOResult must appear in report context."""
        from finagent.engine.models.financial import LBOInputs, LBOResult, LBOYear

        fake_year = LBOYear(
            year=1, revenue=500_000_000, ebitda=100_000_000, da=10_000_000,
            ebit=90_000_000, interest_expense=49_000_000, ebt=41_000_000,
            taxes=10_250_000, net_income=30_750_000, capex=20_000_000,
            delta_nwc=5_000_000, fcf=15_750_000, mandatory_amort=7_000_000,
            cash_sweep_amount=8_750_000, total_debt_paydown=15_750_000,
            ending_debt=684_250_000,
        )
        inputs = LBOInputs(
            ticker="TEST", ltm_ebitda=100_000_000, entry_ev_ebitda=10.0,
            exit_ev_ebitda=10.0, revenue_base=500_000_000,
            revenue_growth_rate=0.05, ebitda_margin=0.2,
        )
        lbo_result = LBOResult(
            entry_ev=1_000_000_000, entry_equity=300_000_000,
            entry_debt=700_000_000, schedule=[fake_year],
            exit_ev=1_800_000_000, exit_ebitda=250_000_000,
            exit_equity=1_400_000_000, irr=0.22, moic=4.5,
        )
        pipeline_result = PipelineResult(
            steps={"lbo_parameters": "...", "lbo_calculation": "..."},
            structured_data={"lbo_parameters": inputs, "lbo_calculation": lbo_result},
        )
        ctx = build_report_context("TEST", pipeline_result)
        assert ctx.get("lbo_inputs") is inputs
        assert ctx.get("lbo_result") is lbo_result


# --- HTTP endpoint tests ---


def _setup_app_state_with_cache(cache: dict[str, dict]) -> None:
    """Set app.state.deps with a pre-populated report cache."""
    from finagent.config import get_settings
    from finagent.engine.deps import FinAgentDeps

    settings = get_settings(model_name="test")
    app.state.deps = FinAgentDeps(
        data_layer=None,  # type: ignore[arg-type]
        settings=settings,
        report_cache=cache,
    )


class TestReportHTMLEndpoint:
    @pytest.mark.asyncio
    async def test_cache_hit_returns_html_with_data(self):
        result = _make_equity_research_result()
        ctx = build_report_context("AAPL", result)
        _setup_app_state_with_cache({"AAPL": ctx})

        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/report/html?ticker=AAPL")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        html = response.text
        assert "AAPL" in html
        assert "Buy" in html
        assert "$200" in html or "200.0" in html

    @pytest.mark.asyncio
    async def test_cache_miss_returns_404(self):
        _setup_app_state_with_cache({})

        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/report/html?ticker=XYZ")

        assert response.status_code == 404
        assert "No report available" in response.text

    @pytest.mark.asyncio
    async def test_ticker_case_insensitive(self):
        result = _make_equity_research_result()
        ctx = build_report_context("AAPL", result)
        _setup_app_state_with_cache({"AAPL": ctx})

        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/report/html?ticker=aapl")

        assert response.status_code == 200


class TestReportPDFEndpoint:
    @pytest.mark.asyncio
    async def test_cache_miss_returns_404(self):
        _setup_app_state_with_cache({})

        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/report/pdf?ticker=XYZ")

        assert response.status_code == 404
        assert "No report available" in response.text
