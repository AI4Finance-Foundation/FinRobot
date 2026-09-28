"""Tests for ``classify_market_implied_nature`` — the per-name valuation-nature
classifier behind the Coverage desk's reverse-DCF read.

These do NOT re-derive the DCF/reverse-DCF formulas (covered by test_dcf.py /
test_dcf_reverse.py). They pin the *classification* logic: the three states and,
crucially, the one-sided WACC-robustness test that separates a robust
option-value verdict from a discount-rate artifact.
"""

from typing import Any

from finrobot.engine.compute.operators.dcf import (
    _price_for,
    classify_market_implied_nature,
    market_implied_check,
)
from finrobot.engine.compute.operators.wacc import calculate_wacc
from finrobot.engine.models.financial import DCFInputs


def _make_inputs(**overrides: Any) -> DCFInputs:
    defaults: dict[str, Any] = dict(
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


def _capm_wacc(inputs: DCFInputs) -> float:
    _, wacc = calculate_wacc(
        inputs.risk_free_rate,
        inputs.beta,
        inputs.equity_risk_premium,
        inputs.cost_of_debt,
        inputs.tax_rate,
        inputs.debt_ratio,
    )
    return wacc


def test_fundamental_when_price_is_growth_explainable():
    """A price equal to what 8% growth justifies → kind=fundamental, and the
    implied growth is carried through as per-name context."""
    inputs = _make_inputs()
    wacc = _capm_wacc(inputs)
    price = _price_for(inputs, 0.08, wacc, inputs.terminal_growth_rate, 5, False)

    nat = classify_market_implied_nature(inputs, price, horizon_years=5)

    assert nat.kind == "fundamental"
    assert nat.implied_growth is not None
    assert abs(nat.implied_growth - 0.08) < 0.005
    assert nat.horizon_years == 5
    # No ceiling fields on the reachable path.
    assert nat.growth_ceiling is None
    assert nat.ceiling_price is None


def test_option_value_when_price_far_above_ceiling_survives_lower_wacc():
    """A price 4× the +50%-growth ceiling (TSLA-type) is unreachable even at a
    plausibly lower WACC → kind=option_value, with the ceiling surfaced and no
    fabricated implied growth."""
    inputs = _make_inputs()
    wacc = _capm_wacc(inputs)
    ceiling = _price_for(inputs, 0.50, wacc, inputs.terminal_growth_rate, 5, False)

    nat = classify_market_implied_nature(inputs, ceiling * 4.0, horizon_years=5)

    assert nat.kind == "option_value"
    assert nat.implied_growth is None
    assert nat.growth_ceiling == 0.50
    assert nat.ceiling_price is not None


def test_near_ceiling_when_a_lower_plausible_wacc_rescues_the_price():
    """A price just above the own-WACC ceiling but below the ceiling at a 2pp
    lower WACC is unreachable at own WACC yet explainable at a plausible one →
    kind=near_ceiling (WACC-sensitive), NOT a robust option-value claim."""
    inputs = _make_inputs()
    own = _capm_wacc(inputs)
    ceiling_own = _price_for(inputs, 0.50, own, inputs.terminal_growth_rate, 5, False)
    ceiling_fav = _price_for(inputs, 0.50, own - 0.02, inputs.terminal_growth_rate, 5, False)
    # Sanity: a lower discount rate raises the reachable ceiling.
    assert ceiling_fav > ceiling_own
    price = (ceiling_own + ceiling_fav) / 2.0
    # Precondition: unreachable at the name's own WACC.
    assert market_implied_check(inputs, price, horizon_years=5).growth_unreachable is True

    nat = classify_market_implied_nature(inputs, price, horizon_years=5)

    assert nat.kind == "near_ceiling"
    assert nat.implied_growth is None
    assert nat.ceiling_price is not None


def test_horizon_is_threaded_through():
    """The classifier solves over the caller's horizon (the source DCF's own
    projection_years), not a hardcoded 5."""
    inputs = _make_inputs()
    wacc = _capm_wacc(inputs)
    price = _price_for(inputs, 0.08, wacc, inputs.terminal_growth_rate, 7, False)

    nat = classify_market_implied_nature(inputs, price, horizon_years=7)

    assert nat.horizon_years == 7
    assert nat.kind == "fundamental"
