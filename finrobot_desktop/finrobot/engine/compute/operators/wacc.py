def calculate_wacc(
    risk_free_rate: float,
    beta: float,
    equity_risk_premium: float,
    cost_of_debt: float,
    tax_rate: float,
    debt_ratio: float,
) -> tuple[float, float]:
    """Calculate Weighted Average Cost of Capital.

    Returns:
        (cost_of_equity, wacc)

    Formula:
        Cost of Equity = Risk-Free Rate + Beta × Equity Risk Premium  (CAPM)
        WACC = E/(D+E) × Cost of Equity + D/(D+E) × Cost of Debt × (1 - Tax Rate)
    """
    cost_of_equity = risk_free_rate + beta * equity_risk_premium
    equity_ratio = 1 - debt_ratio
    after_tax_debt = cost_of_debt * (1 - tax_rate)
    wacc = equity_ratio * cost_of_equity + debt_ratio * after_tax_debt
    return cost_of_equity, wacc


def adjust_beta_blume(raw_beta: float) -> float:
    """Blume / Bloomberg adjustment: mean-revert a raw regression beta toward 1.0.

    Formula:  β_adj = 2/3 × β_raw + 1/3 × 1.0   (Blume 1971; Bloomberg default)

    A stock's historical 5y regression beta is a noisy estimate of its FORWARD
    beta, and empirically betas mean-revert toward the market beta of 1.0 over
    time. Using the raw beta directly is what put NVDA's raw 2.24 into a 16.6%
    CAPM cost of equity — a discount rate no analyst applies to a mega-cap. The
    adjustment pulls extremes in (2.24 → 1.83, 0.50 → 0.67) and leaves names
    already near 1.0 almost untouched, matching how the sell-side actually
    discounts these franchises.

    Reference: Blume, M. (1971/1975), "Betas and Their Regression Tendencies",
    Journal of Finance; the 2/3–1/3 weighting is the Bloomberg terminal default.
    """
    return 2.0 / 3.0 * raw_beta + 1.0 / 3.0
