from __future__ import annotations

import pytest

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
