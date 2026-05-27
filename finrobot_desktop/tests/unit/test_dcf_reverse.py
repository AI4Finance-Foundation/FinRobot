"""Reverse-DCF solver tests.

These tests do NOT re-derive the DCF formula — they only verify the bisection
inverter converges to the same growth (or WACC) that calculate_dcf would
produce, plus edge cases. The forward formula itself is already covered by
test_dcf.py and tests/audit/test_financial_sanity.py.
"""


from finrobot.engine.compute.dcf import (
    calculate_dcf,
    solve_for_implied_growth,
    solve_for_implied_wacc,
)
from finrobot.engine.models.financial import DCFInputs


def _make_inputs(**overrides):
    defaults = dict(
        revenue_base=100_000_000_000,
        revenue_growth_rates=[0.05] * 5,
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
        shares_outstanding=1_000_000_000,
        net_debt=10_000_000_000,
    )
    defaults.update(overrides)
    return DCFInputs(**defaults)


# ───────────────────────────────────────────────────────────────────
# solve_for_implied_growth — round-trip and edge cases
# ───────────────────────────────────────────────────────────────────


def test_reverse_growth_round_trip():
    """Forward calculate_dcf at g=8% gives price P → reverse solve(P) should
    return ~8%. Validates that bisection inverts the forward map correctly."""
    inputs = _make_inputs(revenue_growth_rates=[0.08] * 5)
    forward = calculate_dcf(inputs, wacc_override=0.10)

    reverse = solve_for_implied_growth(
        inputs,
        target_price=forward.implied_price,
        horizon_years=5,
        wacc_override=0.10,
    )
    assert reverse["implied_growth"] is not None
    assert abs(reverse["implied_growth"] - 0.08) < 0.0005  # within 0.05%
    assert abs(reverse["computed_price"] - forward.implied_price) < 0.10


def test_reverse_growth_monotonic_in_target_price():
    """Higher target price → higher implied growth. A basic monotonicity sanity
    check independent of the round-trip formula."""
    inputs = _make_inputs()
    low = solve_for_implied_growth(inputs, target_price=200.0, wacc_override=0.10)
    high = solve_for_implied_growth(inputs, target_price=400.0, wacc_override=0.10)
    assert low["implied_growth"] < high["implied_growth"]


def test_reverse_growth_target_too_high_returns_none():
    """Target price above what max-bracket growth produces → no solution.
    Caller must not assume implied_growth is always populated."""
    inputs = _make_inputs()
    # Cap bracket at 10% growth; target $5000 is unreachable
    out = solve_for_implied_growth(
        inputs,
        target_price=5000.0,
        bracket=(-0.05, 0.10),
        wacc_override=0.10,
    )
    assert out["implied_growth"] is None
    assert "无解" in out["message"]
    assert out["price_at_hi"] < 5000.0


def test_reverse_growth_returns_wacc_and_tg_for_display():
    """Solver echoes back the WACC and terminal growth it used so the UI can
    show the user the full assumption set (not just the bare growth number)."""
    inputs = _make_inputs()
    out = solve_for_implied_growth(
        inputs,
        target_price=300.0,
        wacc_override=0.09,
        tg_override=0.02,
    )
    assert out["wacc"] == 0.09
    assert out["terminal_growth"] == 0.02
    assert out["horizon_years"] == 5


def test_reverse_growth_converges_in_few_iterations():
    """Bisection over a 60-percentage-point bracket should converge in ~30
    iterations at 1e-4 tolerance (log2(0.60 / 1e-4) ≈ 13)."""
    inputs = _make_inputs()
    out = solve_for_implied_growth(inputs, target_price=300.0, wacc_override=0.10)
    assert out["implied_growth"] is not None
    assert out["iterations"] < 30


# ───────────────────────────────────────────────────────────────────
# solve_for_implied_wacc — round-trip and edge cases
# ───────────────────────────────────────────────────────────────────


def test_reverse_wacc_round_trip():
    """Forward DCF at WACC=10% gives price P → reverse solve(P) should
    return ~10%. Price tolerance is looser than WACC tolerance because price
    is convex in WACC near the root; what matters is that we recover the WACC."""
    inputs = _make_inputs()
    forward = calculate_dcf(inputs, wacc_override=0.10)

    reverse = solve_for_implied_wacc(inputs, target_price=forward.implied_price)
    assert reverse["implied_wacc"] is not None
    assert abs(reverse["implied_wacc"] - 0.10) < 0.0005
    assert abs(reverse["computed_price"] - forward.implied_price) < 1.0


def test_reverse_wacc_monotonic_in_target_price():
    """Higher target price → LOWER implied WACC (less risk priced in)."""
    inputs = _make_inputs()
    low_target = solve_for_implied_wacc(inputs, target_price=250.0)
    high_target = solve_for_implied_wacc(inputs, target_price=500.0)
    assert low_target["implied_wacc"] > high_target["implied_wacc"]


def test_reverse_wacc_target_too_low_returns_none():
    """Target far below what the cheapest WACC in bracket produces → no solution."""
    inputs = _make_inputs()
    out = solve_for_implied_wacc(
        inputs,
        target_price=5.0,
        bracket=(0.05, 0.15),
    )
    assert out["implied_wacc"] is None
    assert "无解" in out["message"]


def test_reverse_wacc_clips_bracket_above_terminal_growth():
    """WACC lower bound must stay above terminal growth to keep the Gordon
    Growth Model defined. Solver should silently bump lo, not crash."""
    inputs = _make_inputs(terminal_growth_rate=0.03)
    # Bracket lo=0.02 is BELOW terminal growth — must be clipped
    out = solve_for_implied_wacc(
        inputs,
        target_price=300.0,
        bracket=(0.02, 0.20),
    )
    assert out["bracket"][0] > 0.03  # bumped above tg
