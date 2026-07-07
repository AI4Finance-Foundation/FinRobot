import pytest
from datetime import datetime, timezone
from pydantic import ValidationError
from finrobot.engine.models.financial import (
    BalanceSheet,
    FinancialData,
    IncomeStatement,
    MarketData,
    ValuationMetrics,
    CompanyFinancials,
    PeerComps,
    PeerSelection,
    DCFInputs,
    DCFResult,
    ThesisResult,
    StepOutput,
    HistoricalMetrics,
    CatalystEvent,
    ValuationMethod,
    ValuationSynthesis,
)


def _base_financial_data(**overrides):
    """Build kwargs dict for FinancialData with sub-model construction.

    Accepts flat-style overrides for convenience, then routes them into
    the correct sub-model kwargs.
    """
    # Flat defaults
    flat = dict(
        ticker="AAPL",
        timestamp=datetime.now(tz=timezone.utc),
        revenue=100e9,
        ebitda=35e9,
        net_income=20e9,
        gross_margin=0.47,
        operating_margin=0.28,
        market_cap=3e12,
        shares_outstanding=15e9,
        current_price=200.0,
        total_debt=0,
        total_cash=0,
        depreciation_amortization=None,
        rd_expense=None,
        sga_expense=None,
        interest_expense=None,
        enterprise_value=None,
        ev_ebitda=None,
        ev_revenue=None,
    )
    flat.update(overrides)

    return dict(
        ticker=flat["ticker"],
        timestamp=flat["timestamp"],
        income=IncomeStatement(
            revenue=flat["revenue"],
            ebitda=flat["ebitda"],
            net_income=flat["net_income"],
            gross_margin=flat["gross_margin"],
            operating_margin=flat["operating_margin"],
            depreciation_amortization=flat["depreciation_amortization"],
            rd_expense=flat["rd_expense"],
            sga_expense=flat["sga_expense"],
            interest_expense=flat["interest_expense"],
        ),
        balance=BalanceSheet(
            total_debt=flat["total_debt"],
            total_cash=flat["total_cash"],
        ),
        market=MarketData(
            market_cap=flat["market_cap"],
            shares_outstanding=flat["shares_outstanding"],
            current_price=flat["current_price"],
        ),
        valuation=ValuationMetrics(
            enterprise_value=flat["enterprise_value"],
            ev_ebitda=flat["ev_ebitda"],
            ev_revenue=flat["ev_revenue"],
        ),
    )


def test_financial_data_valid():
    fd = FinancialData(**_base_financial_data())
    assert fd.ticker == "AAPL"
    assert fd.income.revenue == 100e9


def test_financial_data_allows_negative_gross_margin():
    # RIVN-class loss-maker sells vehicles below cost → gross margin < 0. The live
    # FMP payload for RIVN returned gross_margin≈-0.0172, which used to 500 the
    # /financials route because the field carried an asymmetric `ge=0` guard while
    # its sibling operating_margin already allowed negatives. gross_margin ≥
    # operating_margin always (opex ≥ 0), so admitting it down to the same -5 floor
    # is provably crash-free.
    fd = FinancialData(**_base_financial_data(gross_margin=-0.0172))
    assert fd.income.gross_margin == -0.0172


def test_financial_data_rejects_garbage_gross_margin():
    # Below the -5 floor (a percentage/decimal mixup, e.g. -50 meaning -50%) is
    # still rejected so unit-scale garbage can't masquerade as a real margin.
    with pytest.raises(ValidationError):
        FinancialData(**_base_financial_data(gross_margin=-50))


def test_financial_data_rejects_zero_shares():
    with pytest.raises(ValidationError):
        FinancialData(**_base_financial_data(shares_outstanding=0))


def test_financial_data_allows_mutation():
    fd = FinancialData(**_base_financial_data())
    fd.valuation.ev_ebitda = 25.0
    assert fd.valuation.ev_ebitda == 25.0


def test_financial_data_allows_negative_operating_margin():
    fd = FinancialData(**_base_financial_data(operating_margin=-2.5))
    assert fd.income.operating_margin == -2.5


def test_financial_data_has_total_debt_total_cash():
    fd = FinancialData(**_base_financial_data())
    assert fd.balance.total_debt == 0
    assert fd.balance.total_cash == 0
    fd2 = FinancialData(**_base_financial_data(total_debt=100e9, total_cash=50e9))
    assert fd2.balance.total_debt == 100e9


def test_dcf_inputs_rejects_high_beta():
    with pytest.raises(ValidationError):
        DCFInputs(
            revenue_base=100e9,
            revenue_growth_rates=[0.05],
            ebitda_margin=0.35,
            capex_pct_revenue=0.05,
            nwc_pct_revenue=0.02,
            tax_rate=0.21,
            risk_free_rate=0.04,
            beta=10,
            equity_risk_premium=0.05,
            cost_of_debt=0.04,
            debt_ratio=0.1,
            terminal_growth_rate=0.025,
            shares_outstanding=1e9,
            net_debt=10e9,
        )


@pytest.mark.parametrize("beta", [-0.248, -1.0, 0.0, 6.0, 0.354, None])
def test_market_data_accepts_out_of_band_beta(beta):
    """Raw MarketData.beta is UNCONSTRAINED — it is the raw-value layer.

    Vendors emit short-window glitches outside any economically possible band
    (SHEL −0.248, BP −0.239, EQNR −0.752 — a whole sector compressed by a shared
    upstream feed; impossible for a cyclical oil major). The OLD schema clamped
    beta to [0, 5] and raised ValidationError, which crashed the entire extraction
    for that ticker (refuse-to-conclude). Sanity now lives in the WACC layer
    (_pick_with_provenance), which routes out-of-band betas to the industry proxy.
    The schema must store the raw value verbatim (traceability) and never raise.
    """
    md = MarketData(
        market_cap=1e11,
        shares_outstanding=1e9,
        current_price=100.0,
        beta=beta,
    )
    assert md.beta == beta


def test_dcf_inputs_allows_negative_nwc():
    inputs = DCFInputs(
        revenue_base=100e9,
        revenue_growth_rates=[0.05],
        ebitda_margin=0.35,
        capex_pct_revenue=0.05,
        nwc_pct_revenue=-0.1,
        tax_rate=0.21,
        risk_free_rate=0.04,
        beta=1.2,
        equity_risk_premium=0.05,
        cost_of_debt=0.04,
        debt_ratio=0.1,
        terminal_growth_rate=0.025,
        shares_outstanding=1e9,
        net_debt=10e9,
    )
    assert inputs.nwc_pct_revenue == -0.1


def test_dcf_inputs_rejects_too_negative_nwc():
    with pytest.raises(ValidationError):
        DCFInputs(
            revenue_base=100e9,
            revenue_growth_rates=[0.05],
            ebitda_margin=0.35,
            capex_pct_revenue=0.05,
            nwc_pct_revenue=-0.3,
            tax_rate=0.21,
            risk_free_rate=0.04,
            beta=1.2,
            equity_risk_premium=0.05,
            cost_of_debt=0.04,
            debt_ratio=0.1,
            terminal_growth_rate=0.025,
            shares_outstanding=1e9,
            net_debt=10e9,
        )


def test_dcf_result_allows_none_cost_of_equity():
    inputs = DCFInputs(
        revenue_base=100e9,
        revenue_growth_rates=[0.05],
        ebitda_margin=0.35,
        capex_pct_revenue=0.05,
        nwc_pct_revenue=0.02,
        tax_rate=0.21,
        risk_free_rate=0.04,
        beta=1.2,
        equity_risk_premium=0.05,
        cost_of_debt=0.04,
        debt_ratio=0.1,
        terminal_growth_rate=0.025,
        shares_outstanding=1e9,
        net_debt=10e9,
    )
    result = DCFResult(
        cost_of_equity=None,
        wacc=0.10,
        projection_years=1,
        projected_revenue=[105e9],
        projected_ebitda=[36.75e9],
        projected_fcf=[21e9],
        terminal_value=300e9,
        pv_terminal=200e9,
        pv_fcf_total=19e9,
        enterprise_value=219e9,
        equity_value=209e9,
        implied_price=209.0,
        inputs=inputs,
    )
    assert result.cost_of_equity is None


def test_peer_comps_allows_one_peer():
    cf = CompanyFinancials(
        ticker="X",
        revenue=100e9,
        ebitda=30e9,
        net_income=10e9,
        market_cap=500e9,
        gross_margin=0.4,
        operating_margin=0.2,
    )
    target = CompanyFinancials(
        ticker="AAPL",
        revenue=100e9,
        ebitda=35e9,
        net_income=20e9,
        market_cap=3e12,
        gross_margin=0.47,
        operating_margin=0.28,
    )
    comps = PeerComps(target=target, peers=[cf])
    assert len(comps.peers) == 1


def test_thesis_requires_catalyst_and_risk():
    with pytest.raises(ValidationError):
        ThesisResult(
            recommendation="Buy",
            price_target=200.0,
            price_target_basis="DCF",
            catalysts=[],
            risks=["competition"],
            narrative="bullish",
        )
    with pytest.raises(ValidationError):
        ThesisResult(
            recommendation="Buy",
            price_target=200.0,
            price_target_basis="DCF",
            catalysts=["growth"],
            risks=[],
            narrative="bullish",
        )


def test_thesis_narrative_slots_optional_for_backward_compat():
    """narrative fields (incl. company_overview) must be
    optional so legacy artifacts persisted before the schema bump still
    deserialize cleanly. New runs populate them; old runs read None.
    """
    minimal = ThesisResult(
        recommendation="Hold",
        price_target=150.0,
        price_target_basis="DCF",
        catalysts=["new product"],
        risks=["competition"],
        narrative="neutral",
    )
    assert minimal.company_overview is None
    assert minimal.tagline is None
    assert minimal.key_takeaways is None
    assert minimal.valuation_overview is None
    assert minimal.competitor_analysis is None
    assert minimal.news_summary is None


def test_thesis_accepts_full_narrative_payload():
    """All 6 narrative slots can be populated together — represents the
    target shape once company_overview agent ships (P3.1 narrative).
    """
    full = ThesisResult(
        recommendation="Buy",
        price_target=295.0,
        price_target_basis="DCF + Comps blended",
        catalysts=["iPhone 17 ASP", "India capacity ramp"],
        risks=["Greater China", "EU DMA"],
        narrative="Apple BUY with $295 target.",
        tagline="Services 高毛利 + 印度供应链分散，估值仍有 14% 空间",
        key_takeaways=[
            "Services franchise reaches inflection point",
            "iPhone 17 cycle ASP +6% YoY",
            "India capacity 12% → 25% by FY27",
        ],
        company_overview=(
            "Apple Inc. designs, manufactures, and markets smartphones, "
            "personal computers, tablets, wearables and accessories worldwide. "
            "Operates through five reportable segments: iPhone (52%), "
            "Services (25%), Wearables (10%), Mac (8%), iPad (5%). "
            "Vertically integrated ecosystem with 2.2B active devices."
        ),
        valuation_overview="DCF 范围 $272-310，Comps $258-297，加权目标 $295。",
        competitor_analysis="Services unit economics 优于 Mag-7 peers。",
        news_summary="近 30 天 net bullish · India ramp + Services 创历史新高。",
    )
    assert full.company_overview is not None
    assert "Services" in full.company_overview
    assert full.tagline is not None and "印度" in full.tagline
    assert full.key_takeaways is not None and len(full.key_takeaways) == 3
    # Re-serialise + reload must preserve all narrative slots
    rt = ThesisResult.model_validate(full.model_dump())
    assert rt.company_overview == full.company_overview


def test_dcf_result_stores_required_fields():
    inputs = DCFInputs(
        revenue_base=100e9,
        revenue_growth_rates=[0.05],
        ebitda_margin=0.35,
        capex_pct_revenue=0.05,
        nwc_pct_revenue=0.02,
        tax_rate=0.21,
        risk_free_rate=0.04,
        beta=1.2,
        equity_risk_premium=0.05,
        cost_of_debt=0.04,
        debt_ratio=0.1,
        terminal_growth_rate=0.025,
        shares_outstanding=1e9,
        net_debt=10e9,
    )
    result = DCFResult(
        cost_of_equity=0.10,
        wacc=0.09,
        projection_years=2,
        projected_revenue=[105e9, 110.25e9],
        projected_ebitda=[36.75e9, 38.6e9],
        projected_fcf=[21e9, 22e9],
        terminal_value=300e9,
        pv_terminal=200e9,
        pv_fcf_total=38e9,
        enterprise_value=238e9,
        equity_value=228e9,
        implied_price=228.0,
        inputs=inputs,
    )
    assert result.wacc == 0.09
    assert result.enterprise_value == 238e9
    assert result.implied_price == 228.0
    assert result.inputs.revenue_base == 100e9
    assert len(result.projected_revenue) == 2


def test_company_financials_accepts_none_optional_fields():
    cf = CompanyFinancials(
        ticker="X",
        revenue=100e9,
        ebitda=30e9,
        net_income=10e9,
        market_cap=500e9,
        gross_margin=0.4,
        operating_margin=0.2,
        name=None,
        pe_ratio=None,
        ev_ebitda=None,
        ev_revenue=None,
        enterprise_value=None,
    )
    assert cf.name is None
    assert cf.pe_ratio is None
    assert cf.ev_ebitda is None


def test_peer_selection_validates_ticker_count():
    with pytest.raises(ValidationError):
        PeerSelection(tickers=["AAPL", "MSFT"], rationale="same sector")
    ps = PeerSelection(tickers=["AAPL", "MSFT", "GOOGL"], rationale="same sector")
    assert len(ps.tickers) == 3


def test_company_financials_total_debt_cash_default_none_means_unreported():
    """Default is None ("provider didn't report"), NOT 0. A zero default
    fabricated EV=market_cap for balance-sheet-less peers and poisoned the
    median; None makes calculate_multiples withhold EV instead."""
    cf = CompanyFinancials(
        ticker="X",
        revenue=100e9,
        ebitda=30e9,
        net_income=10e9,
        market_cap=500e9,
        gross_margin=0.4,
        operating_margin=0.2,
    )
    assert cf.total_debt is None
    assert cf.total_cash is None


def test_step_output_stores_structured():
    so = StepOutput(text="hello", structured={"key": "val"})
    assert so.text == "hello"
    assert so.structured == {"key": "val"}


# --- P2a: D&A fields ---


def test_financial_data_da_fields_default_none():
    """New D&A fields are Optional and default to None."""
    fd = FinancialData(
        ticker="AAPL",
        timestamp=datetime.now(tz=timezone.utc),
        income=IncomeStatement(
            revenue=100e9,
            ebitda=35e9,
            net_income=20e9,
            gross_margin=0.43,
            operating_margin=0.30,
        ),
        market=MarketData(
            market_cap=2.5e12,
            shares_outstanding=15e9,
            current_price=170.0,
        ),
    )
    assert fd.income.depreciation_amortization is None
    assert fd.income.rd_expense is None
    assert fd.income.sga_expense is None
    assert fd.income.interest_expense is None


def test_financial_data_da_fields_set():
    fd = FinancialData(
        ticker="AAPL",
        timestamp=datetime.now(tz=timezone.utc),
        income=IncomeStatement(
            revenue=100e9,
            ebitda=35e9,
            net_income=20e9,
            gross_margin=0.43,
            operating_margin=0.30,
            depreciation_amortization=11e9,
            rd_expense=22e9,
            sga_expense=18e9,
            interest_expense=3e9,
        ),
        market=MarketData(
            market_cap=2.5e12,
            shares_outstanding=15e9,
            current_price=170.0,
        ),
    )
    assert fd.income.depreciation_amortization == 11e9
    assert fd.income.rd_expense == 22e9


def test_dcf_inputs_da_pct_revenue_defaults_to_zero():
    """da_pct_revenue defaults to 0.0 (legacy-compat).

    Previously this defaulted to None, which triggered a separate "simplified"
    FCF branch in calculate_dcf. Phase B removed that branch entirely — the
    standard formula now always runs, and D&A=0 produces arithmetically
    equivalent FCF to the old simplified path. seed_dcf_inputs always overrides
    this default with a real value from filings or Damodaran fallback.
    """
    inputs = DCFInputs(
        revenue_base=100e9,
        revenue_growth_rates=[0.05],
        ebitda_margin=0.35,
        capex_pct_revenue=0.05,
        nwc_pct_revenue=0.02,
        risk_free_rate=0.04,
        beta=1.2,
        equity_risk_premium=0.05,
        cost_of_debt=0.04,
        debt_ratio=0.1,
        terminal_growth_rate=0.025,
        shares_outstanding=1e9,
        net_debt=10e9,
    )
    assert inputs.da_pct_revenue == 0.0


def test_dcf_inputs_da_pct_revenue_set():
    inputs = DCFInputs(
        revenue_base=100e9,
        revenue_growth_rates=[0.05],
        ebitda_margin=0.35,
        capex_pct_revenue=0.05,
        nwc_pct_revenue=0.02,
        risk_free_rate=0.04,
        beta=1.2,
        equity_risk_premium=0.05,
        cost_of_debt=0.04,
        debt_ratio=0.1,
        terminal_growth_rate=0.025,
        shares_outstanding=1e9,
        net_debt=10e9,
        da_pct_revenue=0.10,
    )
    assert inputs.da_pct_revenue == 0.10


def test_dcf_inputs_da_pct_revenue_validation():
    """da_pct_revenue must be 0-0.5."""
    with pytest.raises(ValidationError):
        DCFInputs(
            revenue_base=100e9,
            revenue_growth_rates=[0.05],
            ebitda_margin=0.35,
            capex_pct_revenue=0.05,
            nwc_pct_revenue=0.02,
            risk_free_rate=0.04,
            beta=1.2,
            equity_risk_premium=0.05,
            cost_of_debt=0.04,
            debt_ratio=0.1,
            terminal_growth_rate=0.025,
            shares_outstanding=1e9,
            net_debt=10e9,
            da_pct_revenue=0.8,  # > 0.5 → invalid
        )


# --- P2c: New models ---


class TestHistoricalMetrics:
    def test_valid_construction(self):
        hm = HistoricalMetrics(
            years=[2022, 2023, 2024],
            revenue=[300e9, 350e9, 394e9],
            revenue_growth_yoy=[None, 0.167, 0.126],
            cogs=[165e9, 185e9, 213e9],
            gross_profit=[135e9, 165e9, 181e9],
            gross_margin=[0.45, 0.471, 0.459],
            sga=[20e9, 22e9, 25e9],
            sga_ratio=[0.067, 0.063, 0.063],
            ebitda=[100e9, 120e9, 130e9],
            ebitda_margin=[0.333, 0.343, 0.330],
            operating_income=[90e9, 108e9, 117e9],
            operating_margin=[0.30, 0.309, 0.297],
            net_income=[70e9, 85e9, 97e9],
            eps=[4.67, 5.67, 6.47],
            pe_ratio=[None, 25.0, 28.3],
            cagr_revenue=0.146,
            ticker="AAPL",
        )
        assert hm.ticker == "AAPL"
        assert len(hm.years) == 3


class TestCatalystEvent:
    def test_valid_event(self):
        event = CatalystEvent(
            category="product_launch",
            headline="Vision Pro Gen 2 announced",
            sentiment="positive",
            impact_score=4,
            probability=0.8,
            reasoning="Strong pre-orders",
        )
        assert event.impact_score == 4

    def test_impact_score_bounds(self):
        with pytest.raises(ValidationError):
            CatalystEvent(
                category="earnings",
                headline="x",
                sentiment="positive",
                impact_score=6,
                probability=0.5,
                reasoning="x",
            )

    def test_probability_bounds(self):
        with pytest.raises(ValidationError):
            CatalystEvent(
                category="earnings",
                headline="x",
                sentiment="positive",
                impact_score=3,
                probability=1.5,
                reasoning="x",
            )

    def test_probability_is_excluded_from_serialization(self):
        # exclude=True keeps the internal net-sentiment weight off EVERY model_dump
        # surface (artifact export bundle, /catalysts response) — a past event's
        # "probability" is fake precision (the frontend already dropped its column).
        # The live ATTRIBUTE is untouched, so ranking (_expected_impact reads it
        # directly) stays byte-identical.
        eightk = CatalystEvent(
            category="regulatory",
            headline="SEC 8-K",
            sentiment="neutral",
            impact_score=3,
            probability=1.0,  # primary-source 8-K weight
            reasoning="x",
        )
        assert eightk.probability == 1.0  # attribute intact for the ranking math
        assert "probability" not in eightk.model_dump(mode="json")  # ...never serialized

    def test_probability_roundtrips_on_the_news_only_route(self):
        # The /catalysts route dumps then model_validates (routes/data.py). That route
        # is news-only (weight 0.7), and default=0.7 reconstructs it losslessly from the
        # probability-less dump — otherwise the required field would 500 on revalidate.
        news = CatalystEvent(
            category="market",
            headline="News item",
            sentiment="positive",
            impact_score=4,
            probability=0.7,
            reasoning="x",
        )
        restored = CatalystEvent.model_validate(news.model_dump(mode="json"))
        assert restored.probability == 0.7


class TestValuationSynthesis:
    def test_valid_synthesis(self):
        vs = ValuationSynthesis(
            methods=[
                ValuationMethod(
                    name="DCF", low=200, mid=245, high=290, confidence=0.5, source="DCF"
                ),
                ValuationMethod(
                    name="Comps", low=220, mid=250, high=280, confidence=0.3, source="EV/EBITDA"
                ),
            ],
            weighted_price=247.0,
            current_price=230.0,
            upside_downside=0.074,
        )
        assert len(vs.methods) == 2
        assert vs.upside_downside == pytest.approx(0.074)
