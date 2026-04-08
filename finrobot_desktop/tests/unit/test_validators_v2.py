import math
import pytest
from datetime import datetime, timezone
from finagent.engine.models.financial import (
    FinancialData, PeerComps, CompanyFinancials, DCFInputs, DCFResult, ThesisResult,
)
from finagent.engine.pipelines.validators import (
    validate_financial_data, validate_peer_comps,
    validate_dcf_result, validate_thesis,
)

def _make_fd(**overrides):
    defaults = dict(
        ticker="AAPL", timestamp=datetime.now(tz=timezone.utc),
        revenue=100e9, ebitda=35e9, net_income=20e9,
        gross_margin=0.47, operating_margin=0.28,
        market_cap=3e12, shares_outstanding=15e9, current_price=200.0,
    )
    defaults.update(overrides)
    return FinancialData(**defaults)

def _make_dcf_result(**overrides):
    inputs = DCFInputs(
        revenue_base=100e9, revenue_growth_rates=[0.05], ebitda_margin=0.35,
        capex_pct_revenue=0.05, nwc_pct_revenue=0.02, tax_rate=0.21,
        risk_free_rate=0.04, beta=1.2, equity_risk_premium=0.05,
        cost_of_debt=0.04, debt_ratio=0.1, terminal_growth_rate=0.025,
        shares_outstanding=1e9, net_debt=10e9,
    )
    defaults = dict(
        cost_of_equity=0.10, wacc=0.09, projection_years=1,
        projected_revenue=[105e9], projected_ebitda=[36.75e9],
        projected_fcf=[21e9], terminal_value=300e9, pv_terminal=200e9,
        pv_fcf_total=19e9, enterprise_value=219e9,
        equity_value=209e9, implied_price=209.0, inputs=inputs,
    )
    defaults.update(overrides)
    return DCFResult(**defaults)

def _make_company(ticker, net_income=10e9):
    return CompanyFinancials(
        ticker=ticker, revenue=100e9, ebitda=30e9, net_income=net_income,
        market_cap=500e9, gross_margin=0.4, operating_margin=0.2,
        ev_ebitda=15.0, pe_ratio=25.0 if net_income > 0 else None,
        enterprise_value=450e9, ev_revenue=4.5,
    )

def _make_peer_comps(n_peers=3):
    peers = [_make_company(f"P{i}") for i in range(n_peers)]
    target = _make_company("T")
    comps = PeerComps(
        target=target, peers=peers,
        median_ev_ebitda=15.0, median_pe=25.0, mean_ev_ebitda=15.0, mean_pe=25.0,
    )
    return comps

def test_validate_financial_data_valid():
    assert validate_financial_data(_make_fd()).passed

def test_validate_financial_data_zero_revenue():
    result = validate_financial_data(_make_fd(revenue=0))
    assert not result.passed
    assert "Revenue" in result.error

def test_validate_financial_data_ebitda_margin_too_high():
    # ebitda=95e9 / revenue=100e9 = 95% > 90% default limit
    result = validate_financial_data(_make_fd(ebitda=95e9))
    assert not result.passed

def test_validate_dcf_result_valid():
    assert validate_dcf_result(_make_dcf_result()).passed

def test_validate_dcf_result_wacc_too_high():
    result = validate_dcf_result(_make_dcf_result(wacc=0.35))
    assert not result.passed
    assert "0.35" in result.error or "WACC" in result.error

def test_validate_dcf_result_negative_wacc():
    """Acceptance criterion 5: wacc=-0.05 → fails with 'WACC must be positive'"""
    result = validate_dcf_result(_make_dcf_result(wacc=-0.05))
    assert not result.passed
    assert "positive" in result.error.lower() or "WACC" in result.error

def test_validate_dcf_result_negative_implied_price():
    result = validate_dcf_result(_make_dcf_result(implied_price=-5.0))
    assert not result.passed

def test_validate_dcf_result_nan_fcf():
    result = validate_dcf_result(_make_dcf_result(projected_fcf=[float("nan")]))
    assert not result.passed

def test_validate_dcf_result_none_cost_of_equity_still_passes():
    """wacc_override case: cost_of_equity=None should still pass"""
    result = validate_dcf_result(_make_dcf_result(cost_of_equity=None))
    assert result.passed

def test_validate_peer_comps_two_peers_fails():
    comps = _make_peer_comps(n_peers=2)
    result = validate_peer_comps(comps)
    assert not result.passed
    assert "3" in result.error or "peers" in result.error.lower()

def test_validate_peer_comps_ev_ebitda_out_of_range():
    comps = _make_peer_comps()
    comps.peers[0].ev_ebitda = 500.0
    result = validate_peer_comps(comps)
    assert not result.passed

def test_validate_peer_comps_median_none_fails():
    comps = _make_peer_comps()
    comps.median_ev_ebitda = None
    result = validate_peer_comps(comps)
    assert not result.passed

def test_validate_thesis_bad_recommendation():
    t = ThesisResult(
        recommendation="Maybe", price_target=200.0,
        price_target_basis="DCF", catalysts=["growth"],
        risks=["competition"], narrative="bullish",
    )
    result = validate_thesis(t)
    assert not result.passed

def test_validate_thesis_valid():
    t = ThesisResult(
        recommendation="Buy", price_target=200.0, price_target_basis="DCF",
        catalysts=["AI growth"], risks=["competition"], narrative="bullish",
    )
    assert validate_thesis(t).passed
