"""DCF reference test using Apple FY2024 public data + Damodaran terminal growth.

Sources:
- Apple 10-K FY2024 (filed 2024-11-01):
  - Revenue: $391.0B (10-K p.26)
  - EBITDA margin: ~33.5% (derived from operating income $123.2B + D&A ~$11.5B)
  - Net debt: $96.8B - $29.9B = $66.9B (10-K p.47)
  - Shares outstanding: 15.12B (10-K p.1)
- Damodaran (Jan 2024): Terminal growth 2.5% for mature tech
- Analyst consensus: ~5% revenue growth (FactSet, Oct 2024)
- CapEx/Rev: ~2.8%, NWC/Rev: ~1.5% (5Y avg from 10-K)

Simplified formula (no D&A split) for tractable hand calculation.

Excel verification (wacc_override=10%, tg=2.5%):
  Y1 rev: 391×1.05 = 410.55B, EBITDA = 137.53B
  Y1 FCF: 137.53×0.79 - 410.55×0.028 - 410.55×0.015 = 108.65 - 11.50 - 6.16 = 90.99B
  Y2 rev: 431.08B, FCF: 95.54B
  Y3 rev: 452.63B, FCF: 100.32B
  Y4 rev: 475.26B, FCF: 105.34B
  Y5 rev: 499.03B, FCF: 110.60B
  PV_FCF = 90.99/1.1 + 95.54/1.21 + 100.32/1.331 + 105.34/1.4641 + 110.60/1.61051
         = 82.72 + 78.96 + 75.37 + 71.95 + 68.67 = 377.67B
  Terminal FCF normalizes capex→D&A×(1+g); with da_pct=0 terminal capex=0, so
  terminal FCF = EBITDA₅×(1-tax) - NWC₅ = 167.18×0.79 - 7.49 = 124.59B (vs the
  $110.60 explicit-year FCF, which still carried the 2.8% growth-phase capex).
  TV = 124.59×1.025/(0.10-0.025) = 1702.74B
  PV_TV = 1702.74/1.61051 = 1057.27B
  EV = 377.67 + 1057.27 = 1434.94B
  Equity = 1434.94 - 66.9 = 1368.04B
  Price = 1368.04 / 15.12 = $90.48/share

This is NOT a real Apple valuation (simplified FCF formula understates value
because it over-taxes D&A). It's a test of the DCF arithmetic engine.
"""

from finrobot.engine.models.financial import DCFInputs
from finrobot.engine.compute.operators.dcf import calculate_dcf


def test_dcf_apple_fy2024_simplified():
    inputs = DCFInputs(
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
        # da_pct_revenue=0 keeps the legacy hand-calc result aligned with the
        # standard-only formula (D&A=0 → no tax shield → equal to simplified).
        da_pct_revenue=0.0,
    )
    result = calculate_dcf(inputs, wacc_override=0.10)

    # Implied price within $1 of hand-calculated $90.48 (see module docstring;
    # terminal capex→D&A normalization lifted it from the legacy $82.68).
    assert abs(result.implied_price - 90.48) < 1.0, f"Got {result.implied_price:.2f}"
    assert result.projection_years == 5
