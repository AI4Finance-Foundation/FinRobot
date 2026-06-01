"""Tests for LBO compute module.

Reference case (Rosenbaum & Pearl, Ch. 8):
  ltm_ebitda=100, entry_ev_ebitda=8.0, exit_ev_ebitda=10.0
  leverage=5.0, hold=5yr, rev_base=500, rev_growth=5%
  ebitda_margin=20%, da_pct=4%, capex_pct=4%, nwc_pct=1%
  interest=7%, amort=1%, tax=25%, cash_sweep=True

Entry: EV=800, Debt=500, Equity=300

Year 1: Rev=525, EBITDA=105, DA=21, EBIT=84
        Interest=500×0.07=35, EBT=49, Tax=12.25, NetInc=36.75
        CapEx=21, ΔNWC=(525-500)×0.01=0.25
        FCF=36.75+21-21-0.25=36.5
        Amort=500×0.01=5, Sweep=max(36.5-5,0)=31.5
        Paydown=36.5, Debt_end=500-36.5=463.5
"""

import pytest
from finrobot.engine.models.financial import LBOInputs
from finrobot.engine.compute.lbo import (
    calculate_lbo,
    calculate_lbo_sensitivity,
    _compute_irr,
)


def _base_inputs(**overrides) -> LBOInputs:
    defaults = dict(
        ticker="TEST",
        ltm_ebitda=100.0,
        entry_ev_ebitda=8.0,
        exit_ev_ebitda=10.0,
        holding_period_years=5,
        revenue_base=500.0,
        revenue_growth_rate=0.05,
        ebitda_margin=0.20,
        da_pct_revenue=0.04,
        capex_pct_revenue=0.04,
        nwc_change_pct_revenue=0.01,
        leverage_multiple=5.0,
        interest_rate=0.07,
        mandatory_amort_pct=0.01,
        cash_sweep=True,
        tax_rate=0.25,
    )
    defaults.update(overrides)
    return LBOInputs(**defaults)


class TestLBOEntry:
    def test_entry_ev(self):
        result = calculate_lbo(_base_inputs())
        assert result.entry_ev == pytest.approx(800.0)

    def test_entry_debt(self):
        result = calculate_lbo(_base_inputs())
        assert result.entry_debt == pytest.approx(500.0)

    def test_entry_equity(self):
        result = calculate_lbo(_base_inputs())
        assert result.entry_equity == pytest.approx(300.0)


class TestLBOYear1:
    def test_year1_interest_expense(self):
        result = calculate_lbo(_base_inputs())
        assert result.schedule[0].interest_expense == pytest.approx(35.0)

    def test_year1_fcf(self):
        result = calculate_lbo(_base_inputs())
        # FCF = NetInc + DA - CapEx - ΔNWC = 36.75 + 21 - 21 - 0.25 = 36.5
        assert result.schedule[0].fcf == pytest.approx(36.5)

    def test_year1_ending_debt(self):
        result = calculate_lbo(_base_inputs())
        # Paydown = 36.5, Debt_end = 500 - 36.5 = 463.5
        assert result.schedule[0].ending_debt == pytest.approx(463.5)

    def test_year1_mandatory_amort(self):
        result = calculate_lbo(_base_inputs())
        # MandAmort = Entry Debt × 1% = 500 × 0.01 = 5
        assert result.schedule[0].mandatory_amort == pytest.approx(5.0)

    def test_year1_cash_sweep(self):
        result = calculate_lbo(_base_inputs())
        # Sweep = FCF - MandAmort = 36.5 - 5 = 31.5
        assert result.schedule[0].cash_sweep_amount == pytest.approx(31.5)


class TestLBOReturns:
    def test_moic_above_two(self):
        result = calculate_lbo(_base_inputs())
        assert result.moic > 2.0

    def test_irr_in_range(self):
        result = calculate_lbo(_base_inputs())
        assert 0.15 < result.irr < 0.40

    def test_schedule_length(self):
        result = calculate_lbo(_base_inputs())
        assert len(result.schedule) == 5

    def test_year_numbers(self):
        result = calculate_lbo(_base_inputs())
        assert [y.year for y in result.schedule] == [1, 2, 3, 4, 5]


class TestLBOEdgeCases:
    def test_irr_total_loss(self):
        """When exit_equity <= 0, IRR should be -1.0 (total loss)."""
        # High leverage, very low exit multiple → debt > exit EV → equity < 0
        inputs = _base_inputs(
            exit_ev_ebitda=1.0,
            leverage_multiple=10.0,
            interest_rate=0.15,
            cash_sweep=False,
        )
        result = calculate_lbo(inputs)
        assert result.irr == pytest.approx(-1.0)

    def test_moic_floored_at_zero_when_equity_wiped(self):
        """MOIC must floor at 0.0 when exit_equity < 0 — you can lose at most
        100% of your equity, never a negative multiple. A negative MOIC would
        contradict the IRR=-1.0 total-loss signal for the same deal (BUG-011)."""
        # Default leverage 5 keeps entry_equity > 0 (300); a 1.0x exit + high
        # interest + no sweep wipes exit_equity negative — the exact (entry>0,
        # exit<0) combo that produced a negative MOIC.
        inputs = _base_inputs(exit_ev_ebitda=1.0, interest_rate=0.15, cash_sweep=False)
        result = calculate_lbo(inputs)
        assert result.entry_equity > 0  # division path is exercised
        assert result.moic == 0.0
        assert result.irr == pytest.approx(-1.0)  # MOIC and IRR agree: total loss

    def test_sensitivity_moic_never_negative(self):
        """No MOIC grid cell may be negative — wiped-out equity floors at 0×,
        matching the grid's IRR=-1.0 cells instead of showing a nonsensical
        negative multiple in the heatmap (BUG-011). A low exit-multiple center +
        high interest + no sweep pushes the low-exit cells to negative equity."""
        inputs = _base_inputs(exit_ev_ebitda=2.0, interest_rate=0.15, cash_sweep=False)
        result = calculate_lbo(inputs)
        for row in result.sensitivity["moic_grid"]:
            for cell in row:
                if cell is not None:
                    assert cell >= 0.0

    def test_no_cash_sweep(self):
        """Without cash sweep, ending debt is higher than with sweep."""
        with_sweep = calculate_lbo(_base_inputs(cash_sweep=True))
        without_sweep = calculate_lbo(_base_inputs(cash_sweep=False))
        assert without_sweep.schedule[-1].ending_debt > with_sweep.schedule[-1].ending_debt

    def test_negative_taxes_clamped_to_zero(self):
        """EBT < 0 should not produce negative taxes."""
        # Very high interest to force negative EBT
        inputs = _base_inputs(interest_rate=0.50)
        result = calculate_lbo(inputs)
        for year in result.schedule:
            assert year.taxes >= 0.0

    def test_negative_fcf_draws_revolver_instead_of_paying_debt(self):
        """A cash-burn year (FCF < mandatory amort) cannot pay down debt with
        cash that doesn't exist — the shortfall must be funded by a revolver draw,
        so total debt RISES, not falls.

        Regression for the bug where mandatory amort was always applied: a 50%
        interest burden drives year-1 FCF to ~-166 yet the old model still cut
        debt by 5, understating leverage and inflating exit equity / IRR exactly
        where credit risk is highest."""
        inputs = _base_inputs(interest_rate=0.50, cash_sweep=False)
        result = calculate_lbo(inputs)
        yr1 = result.schedule[0]
        assert yr1.fcf < 0, "scenario must produce a cash-burn year"
        assert yr1.revolver_draw > 0, "shortfall must draw the revolver"
        assert yr1.ending_debt > result.entry_debt, "debt must rise, not fall, on a cash-burn year"
        # debt must rise by the cash burn (revolver funds the gap beyond mandatory)
        assert yr1.ending_debt == pytest.approx(result.entry_debt - yr1.fcf)


class TestLBOSensitivity:
    def test_sensitivity_shapes_match(self):
        result = calculate_lbo(_base_inputs())
        assert len(result.sensitivity["irr_grid"]) == len(result.sensitivity["entry_multiples"])

    def test_sensitivity_exit_axis(self):
        result = calculate_lbo(_base_inputs())
        assert len(result.sensitivity["irr_grid"][0]) == len(result.sensitivity["exit_multiples"])

    def test_standalone_sensitivity_keys(self):
        inputs = _base_inputs()
        sens = calculate_lbo_sensitivity(inputs)
        assert set(sens.keys()) == {"entry_multiples", "exit_multiples", "irr_grid", "moic_grid"}

    def test_higher_exit_multiple_higher_irr(self):
        """Holding entry fixed, higher exit multiple → higher IRR (monotone)."""
        inputs = _base_inputs()
        sens = calculate_lbo_sensitivity(inputs)
        # Pick a fixed entry row (first) and check IRR increases across exit columns
        row = sens["irr_grid"][0]
        valid = [v for v in row if v is not None]
        assert valid == sorted(valid)


class TestComputeIRR:
    def test_irr_formula(self):
        # MOIC=2, years=5 → IRR = 2^(1/5) - 1 ≈ 14.87%
        irr = _compute_irr(entry_equity=100.0, exit_equity=200.0, years=5)
        assert irr == pytest.approx(2 ** (1 / 5) - 1, rel=1e-6)

    def test_irr_total_loss(self):
        assert _compute_irr(100.0, 0.0, 5) == pytest.approx(-1.0)
        assert _compute_irr(100.0, -50.0, 5) == pytest.approx(-1.0)

    def test_irr_zero_entry_equity(self):
        assert _compute_irr(0.0, 200.0, 5) == pytest.approx(-1.0)


class TestIRRFormulaWarning:
    """C4 regression: LBOResult must carry irr_formula_warning for user transparency."""

    def test_irr_formula_warning_present(self):
        result = calculate_lbo(_base_inputs())
        assert result.irr_formula_warning is not None
        assert "Newton-Raphson" in result.irr_formula_warning

    def test_irr_formula_warning_mentions_interim_flows(self):
        result = calculate_lbo(_base_inputs())
        assert "interim" in result.irr_formula_warning.lower()
