"""DDM must refuse a dividend growth rate < −1 (W3-B路 · degenerate-state).

``current_dividend *= (1 + rate)`` with rate < −1 drives the projected dividend
negative (and sign-flipping when rate < −2), so the share value comes out
negative — a "dividend" cannot shrink by more than 100%. rate == −1 (a permanent
suspension → dividend 0, value collapses to ~0) is valid and must still compute.
Symmetric with the existing tg ≥ cost-of-equity guard.
"""

from __future__ import annotations

import pytest

from finrobot.engine.compute.operators.ddm import calculate_ddm
from finrobot.engine.models.financial import DDMInputs


def _inputs(**ov: object) -> DDMInputs:
    d: dict[str, object] = dict(
        dividend_per_share=3.0,
        dividend_growth_rates=[0.05, 0.05, 0.05, 0.04, 0.03],
        payout_ratio=0.5,
        risk_free_rate=0.045,
        beta=1.0,
        equity_risk_premium=0.055,
        terminal_growth_rate=0.025,
        shares_outstanding=3_000_000_000,
        current_price=150.0,
    )
    d.update(ov)
    return DDMInputs(**d)  # type: ignore[arg-type]


def test_ddm_refuses_dividend_growth_below_minus_one() -> None:
    with pytest.raises(ValueError, match="negative dividend"):
        calculate_ddm(_inputs(dividend_growth_rates=[-1.5, -1.5, -1.5]))


def test_ddm_allows_full_suspension_at_minus_one() -> None:
    # rate == −1: dividend → 0, value collapses but stays finite and ≥ 0.
    result = calculate_ddm(_inputs(dividend_growth_rates=[-1.0, 0.0, 0.0]))
    assert result.equity_value_per_share >= 0
