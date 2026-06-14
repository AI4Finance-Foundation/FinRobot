from datetime import datetime, timezone
from finrobot.engine.models.financial import (
    FinancialData,
    IncomeStatement,
    MarketData,
    PeerComps,
    CompanyFinancials,
    DCFInputs,
    DCFResult,
    ThesisResult,
)
from finrobot.engine.pipelines.validators import (
    validate_financial_data,
    validate_peer_comps,
    validate_dcf_result,
    validate_thesis,
)


def _make_fd(**overrides):
    """Build FinancialData with sub-models. Accepts flat-style overrides for convenience."""
    flat = dict(
        revenue=100e9,
        ebitda=35e9,
        net_income=20e9,
        gross_margin=0.47,
        operating_margin=0.28,
        market_cap=3e12,
        shares_outstanding=15e9,
        current_price=200.0,
    )
    flat.update(overrides)
    return FinancialData(
        ticker="AAPL",
        timestamp=datetime.now(tz=timezone.utc),
        income=IncomeStatement(
            revenue=flat["revenue"],
            ebitda=flat["ebitda"],
            net_income=flat["net_income"],
            gross_margin=flat["gross_margin"],
            operating_margin=flat["operating_margin"],
        ),
        market=MarketData(
            market_cap=flat["market_cap"],
            shares_outstanding=flat["shares_outstanding"],
            current_price=flat["current_price"],
        ),
    )


def _make_dcf_result(**overrides):
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
    defaults = dict(
        cost_of_equity=0.10,
        wacc=0.09,
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
    defaults.update(overrides)
    return DCFResult(**defaults)


def _make_company(ticker, net_income=10e9):
    return CompanyFinancials(
        ticker=ticker,
        revenue=100e9,
        ebitda=30e9,
        net_income=net_income,
        market_cap=500e9,
        gross_margin=0.4,
        operating_margin=0.2,
        ev_ebitda=15.0,
        pe_ratio=25.0 if net_income > 0 else None,
        enterprise_value=450e9,
        ev_revenue=4.5,
    )


def _make_peer_comps(n_peers=3):
    peers = [_make_company(f"P{i}") for i in range(n_peers)]
    target = _make_company("T")
    comps = PeerComps(
        target=target,
        peers=peers,
        median_ev_ebitda=15.0,
        median_pe=25.0,
        mean_ev_ebitda=15.0,
        mean_pe=25.0,
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


def test_validate_peer_comps_cyclical_trough_passes():
    """AMD-style cyclical trough (112.8x) should validate — real signal, not garbage."""
    comps = _make_peer_comps()
    comps.peers[0].ev_ebitda = 112.8
    result = validate_peer_comps(comps)
    assert result.passed


def test_validate_peer_comps_subunit_currency_artifact_fails():
    """TSM-style 0.158x (currency/unit mismatch) must fail — caught as garbage."""
    comps = _make_peer_comps()
    comps.peers[0].ev_ebitda = 0.158
    result = validate_peer_comps(comps)
    assert not result.passed
    assert "0.16x" in result.error or "0.5" in result.error


def test_validate_peer_comps_collects_all_violations():
    """Multiple bad peers should ALL surface in the error, not short-circuit on first."""
    comps = _make_peer_comps(n_peers=4)
    comps.peers[0].ev_ebitda = 0.1
    comps.peers[2].ev_ebitda = 500.0
    result = validate_peer_comps(comps)
    assert not result.passed
    assert comps.peers[0].ticker in result.error
    assert comps.peers[2].ticker in result.error


def test_validate_peer_comps_median_none_fails():
    comps = _make_peer_comps()
    comps.median_ev_ebitda = None
    result = validate_peer_comps(comps)
    assert not result.passed


def test_validate_thesis_bad_recommendation():
    t = ThesisResult(
        recommendation="Maybe",
        price_target=200.0,
        price_target_basis="DCF",
        catalysts=["growth"],
        risks=["competition"],
        narrative="bullish",
    )
    result = validate_thesis(t)
    assert not result.passed


def test_validate_thesis_valid():
    t = ThesisResult(
        recommendation="Buy",
        price_target=200.0,
        price_target_basis="DCF",
        catalysts=["AI growth"],
        risks=["competition"],
        narrative="bullish",
    )
    assert validate_thesis(t).passed


def test_validate_thesis_uppercase_canonical_passes():
    """CLAUDE.md spec: BUY/HOLD/SELL is the canonical IB form. Agent prompts emit
    uppercase — validator must accept it (previously rejected, burning 3 retries)."""
    for rec in ("BUY", "HOLD", "SELL", "OVERWEIGHT", "OUTPERFORM"):
        t = ThesisResult(
            recommendation=rec,
            price_target=200.0,
            price_target_basis="DCF",
            catalysts=["AI growth"],
            risks=["competition"],
            narrative="bullish",
        )
        assert validate_thesis(t).passed, f"{rec} should pass"


def test_validate_thesis_recommendation_preserves_case_in_artifact():
    """Validation is case-insensitive but does not mutate the recommendation field —
    storage / UI keeps whatever case the agent emitted."""
    t = ThesisResult(
        recommendation="BUY",
        price_target=200.0,
        price_target_basis="DCF",
        catalysts=["AI growth"],
        risks=["competition"],
        narrative="bullish",
    )
    validate_thesis(t)
    assert t.recommendation == "BUY"


def test_validate_thesis_review_recommendation_rejected():
    """The REVIEW state is deleted: it is no longer a valid recommendation. A
    thesis tagged 'REVIEW' must fail validation — the verdict is always
    directional (BUY/HOLD/SELL)."""
    t = ThesisResult(
        recommendation="REVIEW",
        price_target=None,
        price_target_basis="legacy gate verdict — no longer valid",
        catalysts=["x"],
        risks=["y"],
        narrative="z",
    )
    result = validate_thesis(t)
    assert not result.passed
    assert "REVIEW" in (result.error or "")


def test_validate_thesis_withheld_directional_with_null_target_passes():
    """The decoupled contract: a directional verdict (e.g. SELL) with a withheld
    POINT (price_target=None) is VALID — the target is decoupled from the verdict
    and may be honestly None while the directional call still ships."""
    t = ThesisResult(
        recommendation="SELL",
        price_target=None,
        price_target_basis="Point withheld (option-value regime); SELL stands on direction.",
        catalysts=["valuation outside calibration band"],
        risks=["market prices option value the models do not capture"],
        narrative="Directionally rich; no defensible point.",
    )
    assert validate_thesis(t).passed


def test_validate_thesis_non_positive_target_rejected():
    """A target that is present but non-positive is the only invalid target state —
    it is neither a defensible point nor an honest withhold (which uses None)."""
    t = ThesisResult(
        recommendation="BUY",
        price_target=0.0,
        price_target_basis="bad",
        catalysts=["x"],
        risks=["y"],
        narrative="z",
    )
    result = validate_thesis(t)
    assert not result.passed
    assert "positive" in (result.error or "").lower()
