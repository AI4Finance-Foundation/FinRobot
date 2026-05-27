from finrobot.engine.compute.wacc import calculate_wacc


def test_wacc_hand_calculated():
    """rf=4%, beta=1.2, erp=5%, cod=4%, tax=21%, D/(D+E)=30%
    CoE = 4% + 1.2 × 5% = 10%
    WACC = 70% × 10% + 30% × 4% × (1-21%) = 7% + 0.948% = 7.948%"""
    coe, wacc = calculate_wacc(
        risk_free_rate=0.04,
        beta=1.2,
        equity_risk_premium=0.05,
        cost_of_debt=0.04,
        tax_rate=0.21,
        debt_ratio=0.3,
    )
    assert abs(coe - 0.10) < 1e-10
    assert abs(wacc - 0.07948) < 1e-6


def test_wacc_all_equity():
    """debt_ratio=0: WACC == cost_of_equity"""
    coe, wacc = calculate_wacc(0.04, 1.2, 0.05, 0.04, 0.21, debt_ratio=0)
    assert abs(wacc - coe) < 1e-12


def test_wacc_high_leverage():
    """debt_ratio=0.8: WACC drops due to tax shield"""
    _, wacc_high = calculate_wacc(0.04, 1.2, 0.05, 0.04, 0.21, debt_ratio=0.8)
    _, wacc_low = calculate_wacc(0.04, 1.2, 0.05, 0.04, 0.21, debt_ratio=0.2)
    assert wacc_high < wacc_low


def test_wacc_zero_beta():
    """beta=0: cost_of_equity = risk_free_rate"""
    coe, _ = calculate_wacc(0.04, 0, 0.05, 0.04, 0.21, debt_ratio=0.3)
    assert abs(coe - 0.04) < 1e-12


def test_wacc_deterministic():
    r1 = calculate_wacc(0.04, 1.2, 0.05, 0.04, 0.21, 0.3)
    r2 = calculate_wacc(0.04, 1.2, 0.05, 0.04, 0.21, 0.3)
    assert r1 == r2
