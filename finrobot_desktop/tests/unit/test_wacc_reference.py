"""WACC reference test using Apple FY2024 public data.

Source: Apple 10-K (FY2024, filed 2024-11-01)
- Market cap: ~$3.45T (as of 2024-09-28 close)
- Total debt: $96.8B (10-K p.47)
- Risk-free rate: 4.25% (10Y Treasury, 2024-09-28)
- Beta: 1.24 (Yahoo Finance, 5Y monthly)
- Equity risk premium: 4.60% (Damodaran, Jan 2024 update)
- Pre-tax cost of debt: 3.25% (weighted avg coupon, 10-K p.48)
- Tax rate: 16.2% (effective, 10-K p.32)

Excel verification:
  CoE = 4.25% + 1.24 × 4.60% = 9.954%
  D/(D+E) = 96.8 / (3450 + 96.8) = 2.728%
  WACC = 97.272% × 9.954% + 2.728% × 3.25% × (1 - 0.162) = 9.757%

This expected value was computed in a spreadsheet independent of calculate_wacc().
If the test fails, either the source data changed or calculate_wacc() has a bug.
"""

from finrobot.engine.compute.operators.wacc import calculate_wacc


def test_wacc_apple_fy2024():
    coe, wacc = calculate_wacc(
        risk_free_rate=0.0425,
        beta=1.24,
        equity_risk_premium=0.046,
        cost_of_debt=0.0325,
        tax_rate=0.162,
        debt_ratio=96.8 / (3450 + 96.8),
    )
    assert abs(coe - 0.09954) < 1e-4
    assert abs(wacc - 0.09757) < 1e-3
