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


def unlever_beta(levered_beta: float, tax_rate: float, debt_equity: float) -> float:
    """Remove the effect of financial leverage from beta (Hamada equation).

    Strips out the capital structure risk to isolate pure business (asset) risk.
    Use this when deriving beta from comparable companies with different leverage.

    Formula (Hamada, 1972):
        β_U = β_L / [1 + (1 - T) × (D/E)]

    Args:
        levered_beta: Observed equity beta from market data.
        tax_rate: Corporate tax rate as decimal (e.g. 0.21).
        debt_equity: Debt-to-equity ratio (D/E), not D/(D+E).

    Returns:
        Unlevered (asset) beta. Always positive if levered_beta > 0.

    Reference: Hamada, R.S. (1972). "The Effect of the Firm's Capital Structure
    on the Systematic Risk of Common Stocks." Journal of Finance, 27(2), 435-452.
    Also Damodaran, "Investment Valuation" 3rd Ed., Chapter 8.
    """
    denom = 1 + (1 - tax_rate) * debt_equity
    if denom <= 1e-9:
        # A firm so net-cash that D/E ≤ ~−1/(1−T): the Hamada denominator hits 0
        # (ZeroDivisionError — or, via float residue, ~1e-16 that explodes the ratio
        # to ~1e16) or goes negative (flipping a positive levered beta to a negative
        # unlevered beta, breaking the contract above). At that singularity there is
        # no meaningful leverage to strip, so the asset beta ≈ the equity beta —
        # return it unchanged. Keeps peer_beta robust: one deeply-net-cash peer must
        # not crash (or sign-/explosion-poison the median of) the whole WACC.
        return levered_beta
    return levered_beta / denom


def relever_beta(unlevered_beta: float, tax_rate: float, debt_equity: float) -> float:
    """Apply financial leverage to an unlevered (asset) beta (Hamada equation).

    Use this to compute the equity beta for a target capital structure after
    deriving the asset beta from peer comparables via unlever_beta().

    Formula (Hamada, 1972):
        β_L = β_U × [1 + (1 - T) × (D/E)]

    Args:
        unlevered_beta: Asset beta (from peer median or industry average).
        tax_rate: Target company's tax rate as decimal.
        debt_equity: Target debt-to-equity ratio (D/E).

    Returns:
        Relevered equity beta for the target capital structure.
    """
    return unlevered_beta * (1 + (1 - tax_rate) * debt_equity)


def peer_beta(
    peer_betas: list[float],
    peer_tax_rates: list[float],
    peer_debt_equity: list[float],
    target_tax_rate: float,
    target_debt_equity: float,
) -> float:
    """Derive a target company's beta from peer comparables via Hamada.

    Standard workflow for private company valuation or when the target's
    observed beta is unreliable:
    1. Unlever each peer's observed beta to get asset beta.
    2. Take the median asset beta (robust to outliers).
    3. Relever at the target's capital structure.

    Args:
        peer_betas: Observed equity betas for each peer.
        peer_tax_rates: Tax rates for each peer (same order).
        peer_debt_equity: D/E ratios for each peer (same order).
        target_tax_rate: Target company's tax rate.
        target_debt_equity: Target company's D/E ratio.

    Returns:
        Relevered equity beta for the target company.

    Raises:
        ValueError: If input lists are empty or different lengths.
    """
    if not peer_betas:
        raise ValueError("At least one peer required")
    if len(peer_betas) != len(peer_tax_rates) or len(peer_betas) != len(peer_debt_equity):
        raise ValueError("peer_betas, peer_tax_rates, and peer_debt_equity must have same length")

    # Step 1: Unlever each peer
    asset_betas = [
        unlever_beta(b, t, de) for b, t, de in zip(peer_betas, peer_tax_rates, peer_debt_equity)
    ]

    # Step 2: Median (more robust than mean for small peer sets)
    sorted_betas = sorted(asset_betas)
    n = len(sorted_betas)
    if n % 2 == 1:
        median_beta = sorted_betas[n // 2]
    else:
        median_beta = (sorted_betas[n // 2 - 1] + sorted_betas[n // 2]) / 2

    # Step 3: Relever at target structure
    return relever_beta(median_beta, target_tax_rate, target_debt_equity)
