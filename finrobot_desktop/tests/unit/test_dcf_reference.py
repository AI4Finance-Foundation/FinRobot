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
  TV = 110.60×1.025/(0.10-0.025) = 1512.87B
  PV_TV = 1512.87/1.61051 = 939.37B
  EV = 377.67 + 939.37 = 1317.04B
  Equity = 1317.04 - 66.9 = 1250.14B
  Price = 1250.14 / 15.12 = $82.68/share

This is NOT a real Apple valuation (simplified FCF formula understates value
because it over-taxes D&A). It's a test of the DCF arithmetic engine.
"""

from finagent.engine.models.financial import DCFInputs
from finagent.engine.compute.dcf import calculate_dcf


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
    )
    result = calculate_dcf(inputs, wacc_override=0.10)

    # Implied price within $1 of hand-calculated $82.68
    assert abs(result.implied_price - 82.68) < 1.0, f"Got {result.implied_price:.2f}"
    assert result.fcf_formula == "simplified"
    assert result.projection_years == 5
