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
