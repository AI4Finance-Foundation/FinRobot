"""Reverse-DCF kernels must refuse a non-positive terminal FCF, exactly like the
forward DCF (W3-B路 · degenerate-state guard symmetry).

calculate_dcf / calculate_sensitivity guard ``terminal_fcf <= 0`` (BUG-074): a
negative steady-state terminal FCF capitalised into a Gordon perpetuity gives a
negative terminal value, so the DCF is not applicable. The reverse pricing
kernels (_price_for / _price_at) lacked that guard, so solve_for_implied_growth /
classify_market_implied_nature happily returned a "converged" implied growth (a
confident ~18% "fundamental" number) built on a negative terminal value — a
traceable-LOOKING figure that contradicts the deterministic core. The kernels
must speak the same terminal economics: refuse it everywhere the forward DCF
refuses it.
"""

from __future__ import annotations

import pytest

from finrobot.engine.compute.operators.dcf import (
    calculate_dcf,
    solve_for_implied_growth,
    solve_for_implied_wacc,
)
from finrobot.engine.models.financial import DCFInputs


def _negative_terminal_inputs() -> DCFInputs:
    # ebitda_margin 0.20 ≈ D&A 0.18 drives steady-state NOPAT+D&A−capex−ΔNWC
    # negative — terminal_fcf < 0 regardless of the explicit growth searched.
    return DCFInputs(
        revenue_base=100_000_000_000,
        revenue_growth_rates=[0.05] * 5,
        ebitda_margin=0.20,
        da_pct_revenue=0.18,
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


def test_forward_dcf_refuses_negative_terminal_fcf() -> None:
    # Sanity: the forward path already refuses (BUG-074).
    with pytest.raises(ValueError):
        calculate_dcf(_negative_terminal_inputs(), wacc_override=0.10)


def test_solve_for_implied_growth_refuses_negative_terminal_fcf() -> None:
    # The reverse solver must NOT return a converged implied growth built on a
    # negative terminal value — it must refuse, like the forward DCF.
    with pytest.raises(ValueError):
        solve_for_implied_growth(
            _negative_terminal_inputs(), target_price=50.0, horizon_years=5, wacc_override=0.10
        )


def test_solve_for_implied_wacc_refuses_negative_terminal_fcf() -> None:
    with pytest.raises(ValueError):
        solve_for_implied_wacc(_negative_terminal_inputs(), target_price=50.0)
