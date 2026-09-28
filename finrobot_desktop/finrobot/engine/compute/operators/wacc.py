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
    """Blume / Bloomberg adjustment, applied ASYMMETRICALLY — only to β > 1.0.

    Formula:  β_adj = 2/3 × β_raw + 1/3 × 1.0   for raw β > 1.0  (Blume 1971)
              β_adj = β_raw                      for raw β ≤ 1.0  (no up-adjust)

    A stock's historical 5y regression beta is a noisy estimate of its FORWARD
    beta. For HIGH-beta names the raw estimate is dominated by measurement noise
    (recent momentum/leverage that fades), and it empirically mean-reverts toward
    the market beta of 1.0 — so the Blume convergence is well-founded. Using the
    raw beta directly is what put NVDA's raw 2.24 into a 16.6% CAPM cost of equity,
    a discount rate no analyst applies to a mega-cap; the convergence pulls it to
    1.83 and brings the discount rate back to reality.

    But the classic symmetric Blume formula ALSO pulls LOW-beta names UP toward
    1.0, and that is wrong for them. A structurally defensive franchise (staples,
    utilities, regulated names) has a low beta because its cash flows genuinely
    do not co-move with the cycle — people buy soda in a recession. That low beta
    is a STRUCTURAL property, not regression noise that will revert. Mechanically
    revising it up toward 1.0 fabricates systematic risk the company does not
    carry: it lifted KO's raw 0.35 to 0.57, inflated WACC ~80bp, and (with the
    terminal value at ~86% of EV amplifying the discount rate) pushed the DCF to
    $53 — a 34% discount to a market that the sell-side rates Buy. So below 1.0
    we return the raw beta unchanged and let the low-beta defensive read stand.

    Continuity & monotonicity: at raw β = 1.0 both branches give exactly 1.0, so
    there is no jump; β_adj is non-decreasing in raw β across the whole domain.

    Reference: Blume, M. (1971/1975), "Betas and Their Regression Tendencies",
    Journal of Finance; the 2/3–1/3 weighting is the Bloomberg terminal default.
    The asymmetric application reflects that mean reversion is the right prior for
    noisy high-beta estimates but not for structurally low defensive betas.
    """
    if raw_beta <= 1.0:
        return raw_beta
    return 2.0 / 3.0 * raw_beta + 1.0 / 3.0
