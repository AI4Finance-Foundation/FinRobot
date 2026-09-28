"""DCF formula monotonicity invariants — red-line guards.

Catches arithmetic / sign-flip regressions in `_project_full` and the FCF
formula. Each test moves *one* DCF input and asserts the implied price
moves in the expected direction. If any of these break, the FCF formula
got reshuffled and the deterministic DCF lost its meaning.

These are red-line tests (no LLM, no providers) — fast, hermetic, must always pass.
"""

from __future__ import annotations

import pytest

from finrobot.engine.compute.operators.dcf import calculate_dcf
from finrobot.engine.models.financial import DCFInputs, DCFResult


def _base_inputs(**overrides) -> DCFInputs:
    """A reasonable baseline DCFInputs — every monotonicity test perturbs from here."""
    defaults = dict(
        revenue_base=100e9,
        revenue_growth_rates=[0.08] * 5,
        ebitda_margin=0.30,
        capex_pct_revenue=0.05,
        nwc_pct_revenue=0.02,
        da_pct_revenue=0.04,
        tax_rate=0.21,
        risk_free_rate=0.04,
        beta=1.1,
        equity_risk_premium=0.05,
        cost_of_debt=0.04,
        debt_ratio=0.2,
        terminal_growth_rate=0.025,
        shares_outstanding=1e9,
        net_debt=10e9,
    )
    defaults.update(overrides)
    return DCFInputs(**defaults)


class TestDaTaxShield:
    """D&A is a non-cash expense; in the EXPLICIT forecast, raising it lowers EBIT
    (taxable income) and therefore increases after-tax FCF by D&A × tax_rate.

    In the TERMINAL value, D&A also sets the steady-state maintenance capex
    (capex → D&A×(1+g), see dcf._terminal_fcf), so across the WHOLE valuation D&A
    reads as a capital-intensity proxy, not a free tax shield — see first test.
    """

    def test_da_capital_intensity_lowers_total_implied_price(self):
        """With explicit capex FIXED, raising D&A is piecewise in the total price.

        The terminal maintenance anchor is min(da_pct, capex_pct):

        · BELOW the company's own capex (here 5%), D&A is depreciation of real
          assets — it sets the steady-state reinvestment, so a 5% depreciator
          must reinvest ~5% in perpetuity vs ~1% for a 1% depreciator. The
          terminal dominates the DCF → higher D&A → LOWER value, even though
          the explicit-period tax shield raises forecast FCF (tests below).

        · ABOVE the company's own capex, the excess is acquisition-intangible
          amortization — a sunk purchase price amortizing off, with NO cash
          replacement cost. The anchor saturates at capex, so the excess is a
          pure explicit-window tax shield → higher D&A → HIGHER value. Under
          the old bare-D&A anchor this regime injected phantom perpetual
          reinvestment instead (AMD post-Xilinx: GAAP D&A 12.3% vs real capex
          2.5% → terminal FCF −$4.3B for a company with +$6.7B real FCF, SEC
          FY2025 — the DCF chapter died and a single-leg comps SELL shipped).
        """
        low = calculate_dcf(_base_inputs(da_pct_revenue=0.01), wacc_override=0.10)
        mid = calculate_dcf(_base_inputs(da_pct_revenue=0.05), wacc_override=0.10)
        # Depreciation regime (da ≤ capex): capital intensity dominates.
        assert mid.implied_price < low.implied_price
        # Amortization regime (da > capex): anchor saturates at capex — the
        # excess is a pure tax shield, value rises again.
        high = calculate_dcf(_base_inputs(da_pct_revenue=0.10), wacc_override=0.10)
        assert high.implied_price > mid.implied_price

    def test_fcf_increases_with_da_each_year(self):
        no_da = calculate_dcf(_base_inputs(da_pct_revenue=0.0), wacc_override=0.10)
        with_da = calculate_dcf(_base_inputs(da_pct_revenue=0.08), wacc_override=0.10)
        for i in range(no_da.projection_years):
            assert with_da.projected_fcf[i] > no_da.projected_fcf[i], (
                f"year {i}: expected D&A tax shield to raise FCF; "
                f"got {with_da.projected_fcf[i]} <= {no_da.projected_fcf[i]}"
            )

    def test_da_difference_equals_tax_shield(self):
        """Δ FCF = D&A × tax_rate exactly. This nails the formula direction."""
        zero = calculate_dcf(_base_inputs(da_pct_revenue=0.0), wacc_override=0.10)
        ten = calculate_dcf(_base_inputs(da_pct_revenue=0.10), wacc_override=0.10)
        for i in range(zero.projection_years):
            rev = zero.projected_revenue[i]
            expected = rev * 0.10 * 0.21
            actual = ten.projected_fcf[i] - zero.projected_fcf[i]
            assert actual == pytest.approx(expected, rel=1e-9)


class TestCapexDirection:
    def test_higher_capex_lowers_implied_price(self):
        low = calculate_dcf(_base_inputs(capex_pct_revenue=0.02), wacc_override=0.10)
        high = calculate_dcf(_base_inputs(capex_pct_revenue=0.10), wacc_override=0.10)
        assert low.implied_price > high.implied_price

    def test_capex_drains_fcf_linearly(self):
        a = calculate_dcf(_base_inputs(capex_pct_revenue=0.03), wacc_override=0.10)
        b = calculate_dcf(_base_inputs(capex_pct_revenue=0.05), wacc_override=0.10)
        for i in range(a.projection_years):
            rev = a.projected_revenue[i]
            expected_diff = rev * (0.05 - 0.03)  # extra cash drained
            actual_diff = a.projected_fcf[i] - b.projected_fcf[i]
            assert actual_diff == pytest.approx(expected_diff, rel=1e-9)


class TestGrowthDirection:
    def test_higher_growth_raises_implied_price(self):
        low = calculate_dcf(_base_inputs(revenue_growth_rates=[0.03] * 5), wacc_override=0.10)
        high = calculate_dcf(_base_inputs(revenue_growth_rates=[0.15] * 5), wacc_override=0.10)
        assert high.implied_price > low.implied_price


class TestWaccDirection:
    def test_higher_wacc_lowers_implied_price(self):
        low = calculate_dcf(_base_inputs(), wacc_override=0.08)
        high = calculate_dcf(_base_inputs(), wacc_override=0.14)
        assert low.implied_price > high.implied_price


class TestEbitdaMarginDirection:
    def test_higher_margin_raises_implied_price(self):
        low = calculate_dcf(_base_inputs(ebitda_margin=0.15), wacc_override=0.10)
        high = calculate_dcf(_base_inputs(ebitda_margin=0.35), wacc_override=0.10)
        assert high.implied_price > low.implied_price


class TestTerminalGrowthDirection:
    def test_higher_terminal_growth_raises_implied_price(self):
        low = calculate_dcf(_base_inputs(), wacc_override=0.10, tg_override=0.01)
        high = calculate_dcf(_base_inputs(), wacc_override=0.10, tg_override=0.03)
        assert high.implied_price > low.implied_price


class TestRemovedFields:
    """Phase B: the simplified-FCF branch and its warning fields are gone.
    DCFResult must not expose them — otherwise downstream consumers might
    silently re-enable the wrong-direction warning copy from the bug screenshot.
    """

    def test_dcf_result_has_no_fcf_formula_field(self):
        assert "fcf_formula" not in DCFResult.model_fields
        assert "fcf_formula_warning" not in DCFResult.model_fields

    def test_dcf_result_dump_does_not_leak_removed_fields(self):
        result = calculate_dcf(_base_inputs(), wacc_override=0.10)
        d = result.model_dump()
        assert "fcf_formula" not in d
        assert "fcf_formula_warning" not in d
