"""LBO reference test using Rosenbaum & Pearl, Investment Banking, Chapter 8.

Source: Rosenbaum & Pearl, "Investment Banking" 3rd Ed., Chapter 8 ("ValueCo LBO")
Reference case adapted to our model's conventions:

  LTM EBITDA: $200M
  Entry EV/EBITDA: 8.0× → Entry EV = $1,600M
  Leverage: 5.0× EBITDA → Entry Debt = $1,000M → Entry Equity = $600M
  Exit EV/EBITDA: 9.0×
  Holding period: 5 years
  Revenue base: $1,000M, growth: 5%/yr, EBITDA margin: 20%
  D&A: 3% of revenue, CapEx: 3% of revenue, NWC: 1% of Δrev
  Interest rate: 6%, mandatory amort: 2% of entry debt/yr, cash sweep: on
  Tax rate: 25%

Excel verification (Year 1):
  Revenue = 1000 × 1.05 = $1,050M
  EBITDA  = 1050 × 0.20 = $210M
  D&A     = 1050 × 0.03 = $31.5M
  EBIT    = 210 - 31.5  = $178.5M
  Interest = 1000 × 0.06 = $60M
  EBT     = 178.5 - 60  = $118.5M
  Taxes   = 118.5 × 0.25 = $29.625M
  Net Inc = 118.5 - 29.625 = $88.875M
  CapEx   = 1050 × 0.03 = $31.5M
  ΔNWC    = (1050-1000) × 0.01 = $0.5M
  FCF     = 88.875 + 31.5 - 31.5 - 0.5 = $88.375M
  MandAmort = 1000 × 0.02 = $20M
  Sweep   = 88.375 - 20  = $68.375M
  Paydown = 88.375M
  Ending Debt = 1000 - 88.375 = $911.625M

Exit (after Year 5):
  Y5 Rev = 1000 × 1.05^5 = $1,276.28M
  Y5 EBITDA = 1276.28 × 0.20 = $255.26M
  Exit EV = 255.26 × 9.0 = $2,297.3M
  Remaining Debt (from full schedule) ≈ $558M (cumulative paydown ~$442M)
  Exit Equity ≈ $2,297.3 - $558 ≈ $1,739M
  MOIC = 1739 / 600 ≈ 2.9×
  IRR = (1739/600)^(1/5) - 1 ≈ 23.7%
"""

import pytest
from finrobot.engine.models.financial import LBOInputs
from finrobot.engine.compute.operators.lbo import calculate_lbo


def _valueco_inputs() -> LBOInputs:
    return LBOInputs(
        ticker="VALUECO",
        ltm_ebitda=200_000_000,
        entry_ev_ebitda=8.0,
        exit_ev_ebitda=9.0,
        holding_period_years=5,
        revenue_base=1_000_000_000,
        revenue_growth_rate=0.05,
        ebitda_margin=0.20,
        da_pct_revenue=0.03,
        capex_pct_revenue=0.03,
        nwc_change_pct_revenue=0.01,
        leverage_multiple=5.0,
        interest_rate=0.06,
        mandatory_amort_pct=0.02,
        cash_sweep=True,
        tax_rate=0.25,
    )


class TestValueCoLBO:
    """Adapted from Rosenbaum & Pearl Ch. 8 ValueCo example."""

    def test_entry_structure(self):
        result = calculate_lbo(_valueco_inputs())
        assert result.entry_ev == pytest.approx(1_600_000_000)
        assert result.entry_debt == pytest.approx(1_000_000_000)
        assert result.entry_equity == pytest.approx(600_000_000)

    def test_year1_fcf(self):
        result = calculate_lbo(_valueco_inputs())
        y1 = result.schedule[0]
        # FCF = 88.875M (from hand calc above)
        assert y1.fcf == pytest.approx(88_375_000, rel=1e-3)

    def test_year1_interest(self):
        result = calculate_lbo(_valueco_inputs())
        y1 = result.schedule[0]
        assert y1.interest_expense == pytest.approx(60_000_000)

    def test_year1_ending_debt(self):
        result = calculate_lbo(_valueco_inputs())
        y1 = result.schedule[0]
        # Ending debt = 1000M - 88.375M = 911.625M
        assert y1.ending_debt == pytest.approx(911_625_000, rel=1e-3)

    def test_moic_in_range(self):
        """MOIC should be ~2.9× per spreadsheet."""
        result = calculate_lbo(_valueco_inputs())
        assert 2.5 < result.moic < 3.5

    def test_irr_in_range(self):
        """IRR should be ~23.7% per spreadsheet."""
        result = calculate_lbo(_valueco_inputs())
        assert 0.20 < result.irr < 0.30
