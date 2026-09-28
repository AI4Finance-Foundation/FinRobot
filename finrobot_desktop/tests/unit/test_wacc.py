from finrobot.engine.compute.operators.wacc import adjust_beta_blume, calculate_wacc


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


# --- adjust_beta_blume: ASYMMETRIC Blume (only converge β > 1.0) ---------------
# High-β regression estimates are noise-dominated and mean-revert toward 1.0, so
# the 2/3·β+1/3 convergence applies. Structurally low defensive betas (staples,
# utilities) are NOT noise — their low cyclicality is real — so they are returned
# raw, never lifted toward 1.0. β = 1.0 is the seam: both rules give 1.0 there.


def test_blume_converges_high_beta():
    """NVDA raw 2.24 → 1.827 (Blume convergence on the high-β side is preserved)."""
    assert abs(adjust_beta_blume(2.24) - (2.0 / 3.0 * 2.24 + 1.0 / 3.0)) < 1e-12
    assert abs(adjust_beta_blume(2.24) - 1.82666667) < 1e-6


def test_blume_low_beta_returned_raw_not_lifted():
    """KO-style defensive raw β 0.35 must NOT be revised up toward 1.0.

    The symmetric Blume formula would have returned 2/3·0.35+1/3 = 0.567,
    inflating WACC ~80bp and pushing the KO DCF to a spurious 34% discount. The
    asymmetric rule returns the raw 0.35 unchanged. This is the regression guard.
    """
    assert adjust_beta_blume(0.35) == 0.35
    # Explicitly assert it is NOT the old symmetric output.
    assert adjust_beta_blume(0.35) != 2.0 / 3.0 * 0.35 + 1.0 / 3.0


def test_blume_continuous_and_monotone_at_one():
    """No jump at β = 1.0; both branches yield exactly 1.0 and the map is non-decreasing."""
    assert adjust_beta_blume(1.0) == 1.0
    # Just below 1.0 (raw branch) and just above 1.0 (convergence branch) straddle 1.0.
    below = adjust_beta_blume(0.999)
    above = adjust_beta_blume(1.001)
    assert below < 1.0 < above
    # Monotone non-decreasing across the seam.
    assert below <= adjust_beta_blume(1.0) <= above


def test_blume_above_one_still_converges():
    """AAPL raw β 1.09 (> 1.0) still gets pulled DOWN toward 1.0 → ~1.06."""
    out = adjust_beta_blume(1.09)
    assert abs(out - (2.0 / 3.0 * 1.09 + 1.0 / 3.0)) < 1e-12
    assert abs(out - 1.06) < 5e-3
    assert out < 1.09  # converged downward, not raw


def test_blume_monotone_across_domain():
    """β_adj is non-decreasing in raw β over the whole [0.2, 2.5] domain."""
    prev = adjust_beta_blume(0.2)
    for raw in [0.35, 0.5, 0.8, 0.999, 1.0, 1.001, 1.2, 1.8, 2.24, 2.5]:
        cur = adjust_beta_blume(raw)
        assert cur >= prev, f"non-monotone at raw={raw}: {cur} < {prev}"
        prev = cur
