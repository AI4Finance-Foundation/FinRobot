"""Financial formula sanity tests — pin key calculations to external sources.

These are FAST gate checks (<1s total) that catch formula regressions.
Every expected value comes from an external source, never from the code itself.

Sources:
  - Apple FY2024 10-K (filed 2024-11-01)
  - Damodaran, "Investment Valuation" — terminal growth, CAPM
  - Rosenbaum & Pearl, "Investment Banking" 3rd Ed., Ch. 8 — LBO ValueCo
  - CFA Level I, Corporate Finance — WACC formula
"""

from __future__ import annotations

import pytest

from finrobot.engine.compute.operators.wacc import calculate_wacc
from finrobot.engine.compute.operators.dcf import calculate_dcf, calculate_sensitivity
from finrobot.engine.compute.operators.lbo import calculate_lbo
from finrobot.engine.compute.operators.multiples import calculate_ev
from finrobot.engine.models.financial import DCFInputs, LBOInputs


# ---------------------------------------------------------------------------
# WACC — CAPM formula (CFA Level I reference)
# ---------------------------------------------------------------------------


class TestWACCSanity:
    """WACC = E/(D+E) * CoE + D/(D+E) * CoD * (1-T), CoE = Rf + B*ERP."""

    def test_capm_basic(self) -> None:
        """Rf=4%, Beta=1.2, ERP=5% → CoE = 4% + 1.2*5% = 10%."""
        coe, _ = calculate_wacc(
            risk_free_rate=0.04,
            beta=1.2,
            equity_risk_premium=0.05,
            cost_of_debt=0.06,
            tax_rate=0.25,
            debt_ratio=0.3,
        )
        assert abs(coe - 0.10) < 1e-10

    def test_wacc_weighted(self) -> None:
        """70% equity at 10%, 30% debt at 6% after 25% tax → WACC = 8.35%."""
        _, wacc = calculate_wacc(
            risk_free_rate=0.04,
            beta=1.2,
            equity_risk_premium=0.05,
            cost_of_debt=0.06,
            tax_rate=0.25,
            debt_ratio=0.3,
        )
        # 0.7 * 0.10 + 0.3 * 0.06 * 0.75 = 0.07 + 0.0135 = 0.0835
        assert abs(wacc - 0.0835) < 1e-10

    def test_zero_debt(self) -> None:
        """All-equity firm: WACC = CoE."""
        coe, wacc = calculate_wacc(
            risk_free_rate=0.04,
            beta=1.0,
            equity_risk_premium=0.05,
            cost_of_debt=0.0,
            tax_rate=0.21,
            debt_ratio=0.0,
        )
        assert abs(wacc - coe) < 1e-10
        assert abs(coe - 0.09) < 1e-10

    def test_zero_beta(self) -> None:
        """Beta=0 (risk-free asset): CoE = Rf."""
        coe, _ = calculate_wacc(
            risk_free_rate=0.04,
            beta=0.0,
            equity_risk_premium=0.05,
            cost_of_debt=0.03,
            tax_rate=0.21,
            debt_ratio=0.5,
        )
        assert abs(coe - 0.04) < 1e-10


# ---------------------------------------------------------------------------
# DCF — Apple FY2024 reference (simplified formula)
# ---------------------------------------------------------------------------


class TestDCFSanity:
    """Pin DCF arithmetic to hand-calculated Apple 10-K reference."""

    @pytest.fixture()
    def apple_inputs(self) -> DCFInputs:
        """Apple FY2024 10-K: Rev $391B, EBITDA margin 33.5%, 5% growth."""
        return DCFInputs(
            revenue_base=391_000_000_000,
            revenue_growth_rates=[0.05] * 5,
            ebitda_margin=0.335,
            capex_pct_revenue=0.028,
            nwc_pct_revenue=0.015,
            tax_rate=0.21,
            risk_free_rate=0.0425,
            beta=1.24,
            equity_risk_premium=0.046,
            cost_of_debt=0.0325,
            debt_ratio=96.8 / (3450 + 96.8),
            terminal_growth_rate=0.025,
            shares_outstanding=15_120_000_000,
            net_debt=66_900_000_000,
            # Pin to 0: D&A=0 means no tax shield, the standard formula collapses
            # to EBITDA(1-T) - CapEx - ΔNWC in the explicit years. With the
            # terminal-capex→D&A normalization, terminal capex = 0 here, lifting
            # the perpetuity FCF — the hand-calc reference is now $90.48.
            da_pct_revenue=0.0,
        )

    def test_apple_implied_price(self, apple_inputs: DCFInputs) -> None:
        """WACC override 10%, tg 2.5% → implied price ~$90.48 (hand-calculated;
        terminal capex→D&A normalization, up from the legacy $82.68)."""
        result = calculate_dcf(apple_inputs, wacc_override=0.10)
        assert abs(result.implied_price - 90.48) < 1.0, f"Got {result.implied_price:.2f}"

    def test_da_zero_collapses_to_simplified_arithmetic(self, apple_inputs: DCFInputs) -> None:
        """When D&A=0 the standard formula collapses to EBITDA(1-T) - CapEx - ΔNWC.

        Phase B removed the explicit 'simplified' branch and its warning —
        every DCFInputs now carries a non-None da_pct_revenue (filings or
        Damodaran fallback). This sanity check confirms a D&A=0 input still
        produces a coherent positive price.
        """
        result = calculate_dcf(apple_inputs, wacc_override=0.10)
        assert result.implied_price > 0
        # FCF[0] = EBITDA(1-T) - CapEx - ΔNWC when D&A=0
        rev0 = result.projected_revenue[0]
        ebitda0 = result.projected_ebitda[0]
        expected = ebitda0 * (1 - apple_inputs.tax_rate) - rev0 * (
            apple_inputs.capex_pct_revenue + apple_inputs.nwc_pct_revenue
        )
        assert abs(result.projected_fcf[0] - expected) < 1

    def test_tg_exceeds_wacc_raises(self, apple_inputs: DCFInputs) -> None:
        """Gordon Growth undefined when tg >= WACC."""
        with pytest.raises(ValueError, match="Terminal growth rate"):
            calculate_dcf(apple_inputs, wacc_override=0.02, tg_override=0.03)

    def test_negative_net_debt_increases_equity(self, apple_inputs: DCFInputs) -> None:
        """Net cash position (negative net debt) → equity > EV."""
        inputs = apple_inputs.model_copy(update={"net_debt": -50_000_000_000})
        result = calculate_dcf(inputs, wacc_override=0.10)
        assert result.equity_value > result.enterprise_value

    def test_sensitivity_table_shape(self, apple_inputs: DCFInputs) -> None:
        """Sensitivity grid returns correct dimensions."""
        wacc_range = [0.08, 0.09, 0.10, 0.11, 0.12]
        tg_range = [0.015, 0.020, 0.025, 0.030]
        table = calculate_sensitivity(apple_inputs, wacc_range, tg_range)
        assert len(table["implied_prices"]) == 5
        assert len(table["implied_prices"][0]) == 4

    def test_sensitivity_none_when_tg_ge_wacc(self, apple_inputs: DCFInputs) -> None:
        """Cells where tg >= wacc must be None, not a number."""
        table = calculate_sensitivity(apple_inputs, [0.03], [0.03, 0.04])
        # tg=0.03 == wacc=0.03 → None; tg=0.04 > wacc=0.03 → None
        assert table["implied_prices"][0][0] is None
        assert table["implied_prices"][0][1] is None


# ---------------------------------------------------------------------------
# LBO — Rosenbaum & Pearl ValueCo reference
# ---------------------------------------------------------------------------


class TestLBOSanity:
    """Pin LBO to Rosenbaum & Pearl Investment Banking Ch. 8 ValueCo."""

    @pytest.fixture()
    def valueco_inputs(self) -> LBOInputs:
        """ValueCo: LTM EBITDA $200M, 8x entry, 4x leverage, 5yr hold."""
        return LBOInputs(
            ticker="VALUECO",
            ltm_ebitda=200_000_000,
            revenue_base=1_000_000_000,
            entry_ev_ebitda=8.0,
            exit_ev_ebitda=8.0,
            leverage_multiple=4.0,
            interest_rate=0.06,
            tax_rate=0.25,
            revenue_growth_rate=0.05,
            ebitda_margin=0.20,
            capex_pct_revenue=0.03,
            nwc_change_pct_revenue=0.02,
            da_pct_revenue=0.02,
            mandatory_amort_pct=0.02,
            holding_period_years=5,
        )

    def test_entry_equity(self, valueco_inputs: LBOInputs) -> None:
        """Entry EV = 8 * 200M = 1600M, Debt = 4 * 200M = 800M, Equity = 800M."""
        result = calculate_lbo(valueco_inputs)
        assert abs(result.entry_equity - 800_000_000) < 1.0

    def test_moic_positive(self, valueco_inputs: LBOInputs) -> None:
        """5yr hold with growth → MOIC > 1.0 (money was made)."""
        result = calculate_lbo(valueco_inputs)
        assert result.moic > 1.0

    def test_irr_positive(self, valueco_inputs: LBOInputs) -> None:
        """Profitable deal → IRR > 0."""
        result = calculate_lbo(valueco_inputs)
        assert result.irr > 0.0

    def test_schedule_length(self, valueco_inputs: LBOInputs) -> None:
        """Schedule should have exactly hold_period years."""
        result = calculate_lbo(valueco_inputs)
        assert len(result.schedule) == 5

    def test_debt_decreases_over_time(self, valueco_inputs: LBOInputs) -> None:
        """With mandatory amort + cash sweep, debt should decrease."""
        result = calculate_lbo(valueco_inputs)
        first_debt = result.schedule[0].ending_debt
        last_debt = result.schedule[-1].ending_debt
        assert last_debt < first_debt


# ---------------------------------------------------------------------------
# Multiples — basic EV arithmetic
# ---------------------------------------------------------------------------


class TestMultiplesSanity:
    """EV = Market Cap + Total Debt - Cash."""

    def test_ev_positive(self) -> None:
        """$100B market cap + $50B debt - $20B cash = $130B EV."""
        ev = calculate_ev(
            market_cap=100_000_000_000,
            total_debt=50_000_000_000,
            cash=20_000_000_000,
        )
        assert abs(ev - 130_000_000_000) < 1.0

    def test_ev_net_cash(self) -> None:
        """More cash than debt → EV < market cap."""
        ev = calculate_ev(
            market_cap=100_000_000_000,
            total_debt=10_000_000_000,
            cash=30_000_000_000,
        )
        assert ev < 100_000_000_000
