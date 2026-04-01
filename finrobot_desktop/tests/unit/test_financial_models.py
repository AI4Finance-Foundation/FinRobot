import pytest
from datetime import datetime, timezone
from pydantic import ValidationError
from finagent.engine.models.financial import (
    FinancialData,
    CompanyFinancials,
    PeerComps,
    PeerSelection,
    DCFInputs,
    DCFResult,
    ThesisResult,
    StepOutput,
)


def _base_financial_data(**overrides):
    defaults = dict(
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
    )
    defaults.update(overrides)
    return defaults


def test_financial_data_valid():
    fd = FinancialData(**_base_financial_data())
    assert fd.ticker == "AAPL"
    assert fd.revenue == 100e9


def test_financial_data_rejects_negative_gross_margin():
    with pytest.raises(ValidationError):
        FinancialData(**_base_financial_data(gross_margin=-0.1))


def test_financial_data_rejects_zero_shares():
    with pytest.raises(ValidationError):
        FinancialData(**_base_financial_data(shares_outstanding=0))


def test_financial_data_allows_mutation():
    fd = FinancialData(**_base_financial_data())
    fd.ev_ebitda = 25.0
    assert fd.ev_ebitda == 25.0


def test_financial_data_allows_negative_operating_margin():
    fd = FinancialData(**_base_financial_data(operating_margin=-2.5))
    assert fd.operating_margin == -2.5


def test_financial_data_has_total_debt_total_cash():
    fd = FinancialData(**_base_financial_data())
    assert fd.total_debt == 0
    assert fd.total_cash == 0
    fd2 = FinancialData(**_base_financial_data(total_debt=100e9, total_cash=50e9))
    assert fd2.total_debt == 100e9


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


def test_company_financials_total_debt_cash():
    cf = CompanyFinancials(
        ticker="X",
        revenue=100e9,
        ebitda=30e9,
        net_income=10e9,
        market_cap=500e9,
        gross_margin=0.4,
        operating_margin=0.2,
    )
    assert cf.total_debt == 0
    assert cf.total_cash == 0


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
        revenue=100e9,
        ebitda=35e9,
        net_income=20e9,
        gross_margin=0.43,
        operating_margin=0.30,
        market_cap=2.5e12,
        shares_outstanding=15e9,
        current_price=170.0,
    )
    assert fd.depreciation_amortization is None
    assert fd.rd_expense is None
    assert fd.sga_expense is None
    assert fd.interest_expense is None


def test_financial_data_da_fields_set():
    fd = FinancialData(
        ticker="AAPL",
        timestamp=datetime.now(tz=timezone.utc),
        revenue=100e9,
        ebitda=35e9,
        net_income=20e9,
        gross_margin=0.43,
        operating_margin=0.30,
        market_cap=2.5e12,
        shares_outstanding=15e9,
        current_price=170.0,
        depreciation_amortization=11e9,
        rd_expense=22e9,
        sga_expense=18e9,
        interest_expense=3e9,
    )
    assert fd.depreciation_amortization == 11e9
    assert fd.rd_expense == 22e9


def test_dcf_inputs_da_pct_revenue_default_none():
    """da_pct_revenue defaults to None (P1.5 simplified formula)."""
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
    assert inputs.da_pct_revenue is None


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
    """da_pct_revenue must be 0-0.5 when set."""
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


def test_dcf_result_fcf_formula_default():
    """fcf_formula defaults to 'simplified'."""
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
    result = DCFResult(
        cost_of_equity=0.10,
        wacc=0.10,
        projection_years=1,
        projected_revenue=[105e9],
        projected_ebitda=[36.75e9],
        projected_fcf=[21.68e9],
        terminal_value=300e9,
        pv_terminal=272e9,
        pv_fcf_total=19.7e9,
        enterprise_value=291.7e9,
        equity_value=281.7e9,
        implied_price=281.7,
        inputs=inputs,
    )
    assert result.fcf_formula == "simplified"
