from __future__ import annotations

import pytest

from finrobot.engine.compute.operators.dcf import calculate_dcf
from finrobot.engine.compute.operators.monte_carlo import MonteCarloRequest, run_monte_carlo
from finrobot.engine.models.financial import DCFInputs


def _inputs() -> DCFInputs:
    return DCFInputs(
        revenue_base=400_000_000_000.0,
        revenue_growth_rates=[0.06, 0.05, 0.04, 0.04, 0.03],
        ebitda_margin=0.30,
        capex_pct_revenue=0.06,
        nwc_pct_revenue=0.02,
        da_pct_revenue=0.05,
        tax_rate=0.21,
        risk_free_rate=0.04,
        beta=1.2,
        equity_risk_premium=0.05,
        cost_of_debt=0.04,
        debt_ratio=0.25,
        terminal_growth_rate=0.025,
        shares_outstanding=15_500_000_000.0,
        net_debt=60_000_000_000.0,
    )


def test_monte_carlo_request_rejects_odd_simulation_count() -> None:
    with pytest.raises(ValueError, match="even"):
        MonteCarloRequest(inputs=_inputs(), current_price=160.0, n_simulations=101)


def test_run_monte_carlo_rejects_odd_simulation_count() -> None:
    with pytest.raises(ValueError, match="even"):
        run_monte_carlo(_inputs(), current_price=160.0, n_simulations=101, seed=1)


def test_run_monte_carlo_preserves_even_simulation_count_assumption() -> None:
    result = run_monte_carlo(_inputs(), current_price=160.0, n_simulations=100, seed=1)

    assert result.assumptions_used["n_simulations"] == 100
    assert result.n_valid <= 100


@pytest.mark.parametrize("mid_year", [False, True])
def test_perturbation_zero_mc_equals_deterministic_dcf(mid_year: bool) -> None:
    """Equivalence gate: MC and calculate_dcf must speak the SAME terminal
    economics (dcf._terminal_fcf's capex→D&A normalization).

    With every perturbation std at 0 each simulated path is the base case, so
    the whole distribution must collapse onto calculate_dcf's implied price.
    The fixture is deliberately capex-heavy (capex 6% vs D&A 5% of revenue):
    the pre-fix MC capitalized the LAST EXPLICIT-YEAR FCF (full growth-phase
    capex) into the perpetuity, which pinned the distribution ~26% below the
    deterministic DCF chapter of the same report.
    """
    inputs = _inputs()
    deterministic = calculate_dcf(inputs, mid_year=mid_year).implied_price

    result = run_monte_carlo(
        inputs,
        current_price=160.0,
        n_simulations=200,
        revenue_growth_std=0.0,
        ebitda_margin_std=0.0,
        wacc_std=0.0,
        terminal_growth_std=0.0,
        seed=42,
        mid_year=mid_year,
    )

    expected = round(deterministic, 2)
    assert result.percentiles["5"] == pytest.approx(expected, abs=0.01)
    assert result.percentiles["50"] == pytest.approx(expected, abs=0.01)
    assert result.percentiles["95"] == pytest.approx(expected, abs=0.01)
    assert result.mean == pytest.approx(expected, abs=0.01)
    # All noise sources (including beta, which scales with wacc_std) are off,
    # so the distribution must be a degenerate point.
    assert result.std == pytest.approx(0.0, abs=0.01)


def test_non_positive_terminal_fcf_paths_are_dropped() -> None:
    """calculate_dcf raises when the steady-state terminal FCF is <= 0
    (BUG-074: a trough must not be capitalized into a perpetual negative).
    The vectorized analogue drops those paths as invalid simulations instead
    of shipping a nonsense distribution."""
    sick = _inputs().model_copy(update={"ebitda_margin": 0.04})

    with pytest.raises(ValueError, match="positive simulations"):
        run_monte_carlo(sick, current_price=160.0, n_simulations=200, seed=7)
