"""Reverse-DCF solver tests.

These tests do NOT re-derive the DCF formula — they only verify the bisection
inverter converges to the same growth (or WACC) that calculate_dcf would
produce, plus edge cases. The forward formula itself is already covered by
test_dcf.py and tests/audit/test_financial_sanity.py.
"""

from finrobot.engine.compute.operators.dcf import (
    ReverseSolveReason,
    _price_for,
    calculate_dcf,
    solve_for_implied_growth,
    solve_for_implied_horizon,
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
    # $5000 sits above the high-bracket (10% growth) price → above-range code.
    assert out["reason_code"] is ReverseSolveReason.TARGET_ABOVE_RANGE
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


def test_reverse_growth_flags_convergence():
    """A normal solve reports converged=True and carries no non-convergence
    message — the caller can trust the implied_growth value."""
    inputs = _make_inputs()
    out = solve_for_implied_growth(inputs, target_price=300.0, wacc_override=0.10)
    assert out["converged"] is True


def test_reverse_growth_marks_non_convergence_when_iterations_capped():
    """When max_iterations is too small for the bracket to collapse below
    tolerance, the result is flagged converged=False with an approximate-value
    warning — never presented as an exact solve (D6)."""
    inputs = _make_inputs()
    out = solve_for_implied_growth(
        inputs,
        target_price=300.0,
        wacc_override=0.10,
        tolerance=1e-9,
        max_iterations=3,
    )
    assert out["implied_growth"] is not None  # still returns the best estimate
    assert out["converged"] is False
    assert out["iterations"] == 3
    assert out["reason_code"] is ReverseSolveReason.NOT_CONVERGED


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
    assert out["reason_code"] is ReverseSolveReason.OUT_OF_WACC_RANGE


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


# ───────────────────────────────────────────────────────────────────
# solve_for_implied_horizon — the third reverse axis (asymmetric)
# ───────────────────────────────────────────────────────────────────


def test_reverse_horizon_round_trip():
    """Price at a constant 12% growth over exactly 8 explicit years → solving for
    horizon at that price (same fixed growth) should return ~8 years."""
    inputs = _make_inputs()
    target = _price_for(inputs, 0.12, 0.10, inputs.terminal_growth_rate, 8, False)
    out = solve_for_implied_horizon(
        inputs, target_price=target, growth_rate=0.12, wacc_override=0.10
    )
    assert out["implied_horizon"] is not None
    assert abs(out["implied_horizon"] - 8.0) < 0.05


def test_reverse_horizon_depends_on_assumed_growth():
    """The load-bearing property: implied horizon is a FUNCTION of the fixed
    growth, not a standalone market reading. A lower assumed growth needs a
    LONGER high-growth window to reach the same price. This is exactly why the
    solver is asymmetric and must echo assumed_growth."""
    inputs = _make_inputs()
    # Pick a target reachable by both growth assumptions.
    target = _price_for(inputs, 0.20, 0.10, inputs.terminal_growth_rate, 9, False)
    hi_growth = solve_for_implied_horizon(
        inputs, target_price=target, growth_rate=0.20, wacc_override=0.10
    )
    lo_growth = solve_for_implied_horizon(
        inputs, target_price=target, growth_rate=0.12, wacc_override=0.10
    )
    assert hi_growth["implied_horizon"] is not None
    assert lo_growth["implied_horizon"] is not None
    # Same price, lower growth ⇒ strictly more years required.
    assert lo_growth["implied_horizon"] > hi_growth["implied_horizon"]


def test_reverse_horizon_echoes_assumed_growth():
    """assumed_growth must round-trip so the UI can show 'under g=X%, ~N years'."""
    inputs = _make_inputs()
    out = solve_for_implied_horizon(
        inputs, target_price=300.0, growth_rate=0.18, wacc_override=0.10
    )
    assert out["assumed_growth"] == 0.18


def test_reverse_horizon_unreachable_returns_none_with_growth_caveat():
    """A target above what even max_horizon of the fixed growth can reach ⇒ no
    horizon solves it; reason_code flags above-range so the UI can say the growth
    assumption is too low (the localized sentence still echoes assumed_growth)."""
    inputs = _make_inputs()
    out = solve_for_implied_horizon(
        inputs,
        target_price=10_000_000.0,  # absurdly high — unreachable at any horizon
        growth_rate=0.05,
        wacc_override=0.10,
        max_horizon=20,
    )
    assert out["implied_horizon"] is None
    assert out["assumed_growth"] == 0.05
    assert out["reason_code"] is ReverseSolveReason.TARGET_ABOVE_RANGE


# ───────────────────────────────────────────────────────────────────
# build_equivalence_line — the (growth → horizon) line at fixed WACC
# ───────────────────────────────────────────────────────────────────


def test_equivalence_line_holds_wacc_fixed_and_descends_with_growth():
    """Every point reprices to the SAME target at the SAME WACC; as growth rises,
    the explicit window needed shrinks (the line slopes down). This is the curve
    the expert probe draws — a family of (growth, horizon) combos, not one point."""
    from finrobot.routes.compute import build_equivalence_line

    inputs = _make_inputs()
    # A target reachable across the mid/high growth range.
    target = _price_for(inputs, 0.30, 0.10, inputs.terminal_growth_rate, 8, False)
    wacc, tg, points = build_equivalence_line(
        inputs, target, wacc_override=0.10, growth_lo=0.20, growth_hi=0.50, steps=7
    )
    assert wacc == 0.10  # fixed for the whole line
    assert len(points) == 7
    defined = [(p.growth, p.implied_horizon) for p in points if p.implied_horizon is not None]
    assert len(defined) >= 2
    # Strictly descending horizon as growth increases (higher growth ⇒ fewer years).
    horizons = [h for _, h in defined]
    assert all(horizons[i] > horizons[i + 1] for i in range(len(horizons) - 1))


def test_equivalence_line_marks_unreachable_growths_as_none():
    """Below some growth the target is unreachable at any horizon — those points
    are None (a gap in the line), never fabricated to 0."""
    from finrobot.routes.compute import build_equivalence_line

    inputs = _make_inputs()
    target = _price_for(inputs, 0.45, 0.10, inputs.terminal_growth_rate, 9, False)
    _, _, points = build_equivalence_line(
        inputs, target, wacc_override=0.10, growth_lo=0.05, growth_hi=0.50, steps=10
    )
    # The very lowest growths cannot reach a target set by 45% growth × 9 years.
    assert points[0].implied_horizon is None
    # And the highest growth definitely can.
    assert points[-1].implied_horizon is not None


# ───────────────────────────────────────────────────────────────────
# BUG-035 — the converged flag must survive into the API response model
# ───────────────────────────────────────────────────────────────────


def test_dcf_reverse_result_preserves_converged_flag():
    """The bisection reports converged in its dict, but DcfReverseResult silently
    dropped the key (extra ignored), so an API caller couldn't tell an exact solve
    from a capped approximation. The model must carry it through (BUG-035)."""
    from finrobot.routes.compute import DcfReverseResult

    inputs = _make_inputs()
    out = solve_for_implied_growth(inputs, target_price=300.0, wacc_override=0.10)
    assert "converged" in out
    result = DcfReverseResult(solve_for="growth", **out)
    assert result.converged == out["converged"]


def test_dcf_reverse_result_converged_defaults_true_for_horizon():
    """solve_for_implied_horizon emits no converged key; the model defaults it to
    True so the horizon path (which reports solvability via implied_horizon/message)
    doesn't read as non-converged."""
    from finrobot.routes.compute import DcfReverseResult

    inputs = _make_inputs()
    out = solve_for_implied_horizon(
        inputs, target_price=300.0, growth_rate=0.08, wacc_override=0.10
    )
    result = DcfReverseResult(solve_for="horizon", **out)
    assert result.converged is True


# ───────────────────────────────────────────────────────────────────
# market_implied_check — the typed reality-check wrapper used by the report
# ───────────────────────────────────────────────────────────────────


def _capm_wacc(inputs):
    from finrobot.engine.compute.operators.wacc import calculate_wacc

    _, wacc = calculate_wacc(
        inputs.risk_free_rate,
        inputs.beta,
        inputs.equity_risk_premium,
        inputs.cost_of_debt,
        inputs.tax_rate,
        inputs.debt_ratio,
    )
    return wacc


def test_market_implied_check_reachable_round_trip():
    """When the market price equals what 8% growth justifies (under CAPM WACC),
    the reality check reports ~8% implied growth and growth_unreachable=False."""
    from finrobot.engine.compute.operators.dcf import _price_for, market_implied_check

    inputs = _make_inputs()
    wacc = _capm_wacc(inputs)
    price_at_8 = _price_for(inputs, 0.08, wacc, inputs.terminal_growth_rate, 5, False)

    mi = market_implied_check(inputs, price_at_8, horizon_years=5)
    assert mi.growth_unreachable is False
    assert mi.implied_growth is not None
    assert abs(mi.implied_growth - 0.08) < 0.005
    assert mi.horizon_years == 5
    assert mi.ceiling_price is None  # only populated on the unreachable path


def test_market_implied_check_unreachable_option_value():
    """A price far above what even +50% growth justifies (the TSLA case) must set
    growth_unreachable=True, implied_growth=None, and surface the ceiling so the
    narrative can say 'even 50% growth implies only $X'."""
    from finrobot.engine.compute.operators.dcf import _price_for, market_implied_check

    inputs = _make_inputs()
    wacc = _capm_wacc(inputs)
    ceiling = _price_for(inputs, 0.50, wacc, inputs.terminal_growth_rate, 5, False)

    mi = market_implied_check(inputs, ceiling * 4.0, horizon_years=5)
    assert mi.growth_unreachable is True
    assert mi.implied_growth is None
    assert mi.growth_ceiling == 0.50
    assert mi.ceiling_price is not None
    assert abs(mi.ceiling_price - ceiling) / ceiling < 0.01
