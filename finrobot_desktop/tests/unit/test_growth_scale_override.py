"""Tests for apply_growth_scale_override — the 'Revenue Growth Scale'
override path through /api/compute/dcf-seed.

Verifies:
- scale=None is the identity
- positive scale multiplies every year's growth by (1 + scale)
- negative scale shrinks every year by (1 + scale)
- scale=0.0 is the identity (degenerate but valid input)
- provenance dict is preserved across the model_copy
- the original DCFInputs object is not mutated
"""

from __future__ import annotations

import pytest

from finrobot.engine.models.financial import DCFInputs
from finrobot.routes.compute import apply_growth_scale_override


def _inputs(growth_rates: list[float]) -> DCFInputs:
    return DCFInputs(
        revenue_base=1_000_000_000.0,
        revenue_growth_rates=growth_rates,
        ebitda_margin=0.30,
        capex_pct_revenue=0.04,
        nwc_pct_revenue=0.02,
        da_pct_revenue=0.03,
        tax_rate=0.21,
        risk_free_rate=0.04,
        beta=1.1,
        equity_risk_premium=0.055,
        cost_of_debt=0.05,
        debt_ratio=0.20,
        terminal_growth_rate=0.025,
        shares_outstanding=100_000_000.0,
        net_debt=50_000_000.0,
        assumption_provenance={"revenue_growth_rates": "AAPL 3y median"},
    )


def test_none_scale_returns_identity_growth() -> None:
    base = _inputs([0.10, 0.08, 0.06, 0.04, 0.03])
    out = apply_growth_scale_override(base, None)
    assert out.revenue_growth_rates == [0.10, 0.08, 0.06, 0.04, 0.03]


def test_positive_scale_uniformly_lifts_every_year() -> None:
    base = _inputs([0.10, 0.08, 0.06])
    out = apply_growth_scale_override(base, 0.5)  # +50%
    assert out.revenue_growth_rates == pytest.approx([0.15, 0.12, 0.09])


def test_negative_scale_uniformly_cuts_every_year() -> None:
    base = _inputs([0.10, 0.08, 0.06])
    out = apply_growth_scale_override(base, -0.5)  # halve
    assert out.revenue_growth_rates == pytest.approx([0.05, 0.04, 0.03])


def test_zero_scale_is_identity() -> None:
    base = _inputs([0.10, 0.08, 0.06])
    out = apply_growth_scale_override(base, 0.0)
    assert out.revenue_growth_rates == pytest.approx([0.10, 0.08, 0.06])


def test_provenance_preserved_through_override() -> None:
    base = _inputs([0.10])
    out = apply_growth_scale_override(base, 0.2)
    assert out.assumption_provenance == {"revenue_growth_rates": "AAPL 3y median"}


def test_original_inputs_not_mutated() -> None:
    base = _inputs([0.10, 0.08])
    _ = apply_growth_scale_override(base, 0.5)
    assert base.revenue_growth_rates == [0.10, 0.08]


def test_max_positive_scale_on_high_growth_seed_stays_under_40_percent() -> None:
    """Composition sanity: ``seed_dcf_inputs`` caps the seeded decay at ~25%
    per year (top-of-range fast grower). With the +50% maximum the slider
    allows, every scaled rate must stay below 40% — anything above is the
    Pydantic field bound or the seed cap regressing, and DCFs computed with
    >50%/yr growth are not defensible for a research tool.
    """
    base = _inputs([0.25, 0.22, 0.18, 0.14, 0.10])
    out = apply_growth_scale_override(base, 0.5)
    assert all(g < 0.40 for g in out.revenue_growth_rates), out.revenue_growth_rates


def test_max_negative_scale_on_decaying_seed_does_not_invert_to_growth() -> None:
    """A -50% scale must monotonically *reduce* every year's growth; it must
    never accidentally invert sign or amplify magnitude. Guards against a
    future refactor that flips the multiplier."""
    base = _inputs([0.10, 0.08, 0.06, 0.04])
    out = apply_growth_scale_override(base, -0.5)
    for original, scaled in zip(base.revenue_growth_rates, out.revenue_growth_rates):
        assert 0 < scaled < original
