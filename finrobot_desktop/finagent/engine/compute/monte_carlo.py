"""Monte Carlo fair value simulation — NumPy-vectorized.

Runs N DCF simulations with randomized assumption distributions
to produce a probability distribution of implied share prices.

This is deterministic code the LLM cannot replicate: it runs thousands of
DCF valuations with statistically varied inputs and computes percentile
statistics on the resulting price distribution.

Performance: vectorized with NumPy — all N simulations computed as array
operations (no Python for-loop over simulations). Typical 10K-sim run
completes in ~10ms vs ~2s for the scalar loop it replaced.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from pydantic import BaseModel, Field

from finagent.engine.models.financial import DCFInputs


class MonteCarloResult(BaseModel):
    """Result of Monte Carlo DCF simulation."""

    implied_prices: list[float] = Field(description="All valid simulated prices, sorted")
    percentiles: dict[str, float] = Field(
        description="Percentile -> price mapping, e.g. {'5': 165.2, '50': 198.0}"
    )
    mean: float
    std: float
    current_price_percentile: float = Field(
        description="Where current price falls in distribution (0-100)"
    )
    histogram_bins: list[float] = Field(description="Bin edges for histogram")
    histogram_counts: list[int] = Field(description="Counts per histogram bin")
    assumptions_used: dict[str, Any] = Field(description="Distribution parameters used")
    n_valid: int = Field(description="Number of valid simulations (out of n_simulations)")


class MonteCarloRequest(BaseModel):
    """Request body for Monte Carlo endpoint."""

    inputs: DCFInputs
    current_price: float = Field(gt=0)
    n_simulations: int = Field(default=10_000, ge=100, le=100_000)
    n_bins: int = Field(default=50, ge=10, le=200)
    revenue_growth_std: float = Field(default=0.02, ge=0, le=0.10)
    ebitda_margin_std: float = Field(default=0.02, ge=0, le=0.10)
    wacc_std: float = Field(default=0.01, ge=0, le=0.05)
    terminal_growth_std: float = Field(default=0.005, ge=0, le=0.02)
    mid_year: bool = Field(default=False)


def run_monte_carlo(
    inputs: DCFInputs,
    current_price: float,
    n_simulations: int = 10_000,
    n_bins: int = 50,
    revenue_growth_std: float = 0.02,
    ebitda_margin_std: float = 0.02,
    wacc_std: float = 0.01,
    terminal_growth_std: float = 0.005,
    seed: int | None = None,
    mid_year: bool = False,
) -> MonteCarloResult:
    """Run N DCF simulations with randomized assumptions — fully vectorized.

    All N simulations execute as NumPy array operations: revenue projections,
    FCF computation, discounting, and terminal value are computed across all
    simulations simultaneously. No Python for-loop over simulations.

    Uses antithetic variates for variance reduction: generates N/2 random draws,
    then mirrors them (negates the noise) to create N total simulations. Because
    DCF valuation is monotonic in its inputs (higher growth → higher price),
    the paired simulations are negatively correlated, reducing estimator variance
    by ~30-50% compared to plain random sampling at zero computational cost.
    Reference: Glasserman, "Monte Carlo Methods in Financial Engineering", Ch. 4.

    Each simulation perturbs the base assumptions with Gaussian noise:
    - Revenue growth rates: each year +-revenue_growth_std
    - EBITDA margin: +-ebitda_margin_std
    - WACC (via CAPM components): +-wacc_std
    - Terminal growth rate: +-terminal_growth_std

    Args:
        inputs: Base DCF assumptions (from pipeline or user).
        current_price: Current stock price for percentile calculation.
        n_simulations: Number of Monte Carlo iterations.
        n_bins: Number of histogram bins.
        revenue_growth_std: Std dev for revenue growth perturbation.
        ebitda_margin_std: Std dev for EBITDA margin perturbation.
        wacc_std: Std dev for WACC component perturbation.
        terminal_growth_std: Std dev for terminal growth perturbation.
        seed: Optional RNG seed for reproducibility (used in tests).
        mid_year: If True, use mid-year discounting convention (consistent
            with calculate_dcf mid_year parameter). Typically increases
            valuations by 3-6%.

    Returns:
        MonteCarloResult with distribution statistics.

    Raises:
        ValueError: If fewer than 100 valid simulations complete.
    """
    rng = np.random.default_rng(seed)
    n = n_simulations
    n_years = len(inputs.revenue_growth_rates)
    base_growth = np.array(inputs.revenue_growth_rates)  # (n_years,)

    # --- Antithetic variates: generate N/2 draws, mirror to get N total ---
    # For each noise vector Z, we also use -Z. The paired simulations are
    # negatively correlated (high-growth paired with low-growth), reducing
    # the variance of the mean estimator.
    n_half = n // 2
    n = n_half * 2  # ensure even count

    # Revenue growth: (n_half, n_years) + antithetic
    growth_noise_half = rng.normal(0, revenue_growth_std, size=(n_half, n_years))
    growth_noise = np.concatenate([growth_noise_half, -growth_noise_half], axis=0)
    sim_growth = base_growth[np.newaxis, :] + growth_noise  # (n, n_years)

    # EBITDA margin: (n,) vector, floored at 1%
    margin_noise_half = rng.normal(0, ebitda_margin_std, size=n_half)
    margin_noise = np.concatenate([margin_noise_half, -margin_noise_half])
    sim_margin = np.maximum(0.01, inputs.ebitda_margin + margin_noise)

    # Terminal growth rate: (n,) vector, floored at 0.5%
    tgr_noise_half = rng.normal(0, terminal_growth_std, size=n_half)
    tgr_noise = np.concatenate([tgr_noise_half, -tgr_noise_half])
    sim_tgr = np.maximum(0.005, inputs.terminal_growth_rate + tgr_noise)

    # WACC via CAPM: perturb risk-free rate, ERP, beta → compute WACC vectorized
    rfr_noise_half = rng.normal(0, wacc_std * 0.5, size=n_half)
    erp_noise_half = rng.normal(0, wacc_std, size=n_half)
    beta_noise_half = rng.normal(0, 0.1, size=n_half)
    sim_rfr = np.maximum(
        0.005, inputs.risk_free_rate + np.concatenate([rfr_noise_half, -rfr_noise_half])
    )
    sim_erp = np.maximum(
        0.02, inputs.equity_risk_premium + np.concatenate([erp_noise_half, -erp_noise_half])
    )
    sim_beta = np.maximum(0.3, inputs.beta + np.concatenate([beta_noise_half, -beta_noise_half]))

    # CAPM: CoE = rf + beta * ERP
    sim_coe = sim_rfr + sim_beta * sim_erp
    equity_ratio = 1 - inputs.debt_ratio
    after_tax_debt = inputs.cost_of_debt * (1 - inputs.tax_rate)
    sim_wacc = equity_ratio * sim_coe + inputs.debt_ratio * after_tax_debt  # (n,)

    # Gordon Growth requires WACC > TGR — enforce minimum 1.5% spread.
    # A 0.5% spread creates terminal values of 200× last FCF that get filtered
    # as outliers anyway. 1.5% is the practical minimum (Damodaran recommends
    # TGR ≤ risk-free rate, implying spread ≥ equity premium).
    _MIN_WACC_TGR_SPREAD = 0.015
    sim_tgr = np.minimum(sim_tgr, sim_wacc - _MIN_WACC_TGR_SPREAD)

    # --- Vectorized DCF projection ---
    # Project revenue year by year: rev[t] = rev[t-1] * (1 + growth[t])
    # cumulative_growth[i, t] = product(1 + growth[i, 0..t])
    cumulative_growth = np.cumprod(1 + sim_growth, axis=1)  # (n, n_years)
    sim_revenue = inputs.revenue_base * cumulative_growth  # (n, n_years)

    # EBITDA = revenue * margin
    sim_ebitda = sim_revenue * sim_margin[:, np.newaxis]  # (n, n_years)

    # Standard FCF: EBIT(1-T) + D&A - CapEx - ΔNWC. The simplified branch that
    # dropped the D&A tax shield (Phase B refactor) is gone — da_pct_revenue
    # is now required on DCFInputs.
    sim_da = sim_revenue * inputs.da_pct_revenue
    sim_ebit = sim_ebitda - sim_da
    sim_fcf = (
        sim_ebit * (1 - inputs.tax_rate)
        + sim_da
        - sim_revenue * inputs.capex_pct_revenue
        - sim_revenue * inputs.nwc_pct_revenue
    )

    # --- Discount factors: 1 / (1 + wacc)^t for t = 1..n_years ---
    # Mid-year convention: discount at (t - 0.5) instead of t, consistent
    # with calculate_dcf(mid_year=True).
    offset = 0.5 if mid_year else 0.0
    periods = np.arange(1, n_years + 1, dtype=np.float64) - offset  # (n_years,)
    # (n, n_years) = (n,1)^(1, n_years)
    discount_factors = 1.0 / (1 + sim_wacc[:, np.newaxis]) ** periods[np.newaxis, :]

    # PV of projected FCFs
    pv_fcf_total = np.sum(sim_fcf * discount_factors, axis=1)  # (n,)

    # Terminal value (Gordon Growth Model)
    last_fcf = sim_fcf[:, -1]  # (n,)
    terminal_value = last_fcf * (1 + sim_tgr) / (sim_wacc - sim_tgr)  # (n,)
    pv_terminal = terminal_value / (1 + sim_wacc) ** (n_years - offset)  # (n,)

    # Enterprise value → equity value → implied price
    enterprise_value = pv_fcf_total + pv_terminal
    equity_value = enterprise_value - inputs.net_debt
    implied_prices = equity_value / inputs.shares_outstanding  # (n,)

    # --- Filter valid prices (IQR-based outlier removal) ---
    # Step 1: keep only positive prices
    positive_mask = implied_prices > 0
    positive_prices = implied_prices[positive_mask]

    if len(positive_prices) < 100:
        raise ValueError(
            f"Only {len(positive_prices)} positive simulations out of {n_simulations}. "
            "Try widening assumptions or increasing n_simulations."
        )

    # Step 2: IQR-based outlier fence (Tukey's far fence, 3×IQR).
    # Removes extreme tails caused by near-zero WACC-TGR spreads while
    # preserving the realistic spread of the distribution.
    q1 = float(np.percentile(positive_prices, 25))
    q3 = float(np.percentile(positive_prices, 75))
    iqr = q3 - q1
    lower_fence = q1 - 3 * iqr
    upper_fence = q3 + 3 * iqr
    valid_mask = positive_mask & (implied_prices >= lower_fence) & (implied_prices <= upper_fence)
    valid_prices = implied_prices[valid_mask]

    if len(valid_prices) < 100:
        raise ValueError(
            f"Only {len(valid_prices)} valid simulations out of {n_simulations} "
            f"after outlier removal (IQR fence: ${lower_fence:,.0f}–${upper_fence:,.0f}). "
            "Try widening assumptions or increasing n_simulations."
        )

    valid_prices.sort()
    prices_list = [round(float(p), 2) for p in valid_prices]

    # --- Statistics (NumPy percentile/mean/std) ---
    pct_keys = [5, 10, 25, 50, 75, 90, 95]
    pct_values = np.percentile(valid_prices, pct_keys)
    percentiles = {str(p): round(float(v), 2) for p, v in zip(pct_keys, pct_values)}

    mean_price = float(np.mean(valid_prices))
    std_price = float(np.std(valid_prices, ddof=1)) if len(valid_prices) > 1 else 0.0

    # Histogram via NumPy
    counts_arr, edges_arr = np.histogram(valid_prices, bins=n_bins)

    # Current price percentile
    below_count = int(np.searchsorted(valid_prices, current_price, side="right"))
    current_pct = (below_count / len(valid_prices)) * 100

    return MonteCarloResult(
        implied_prices=prices_list,
        percentiles=percentiles,
        mean=round(mean_price, 2),
        std=round(std_price, 2),
        current_price_percentile=round(current_pct, 1),
        histogram_bins=[round(float(b), 2) for b in edges_arr],
        histogram_counts=[int(c) for c in counts_arr],
        n_valid=len(valid_prices),
        assumptions_used={
            "n_simulations": n_simulations,
            "valid_simulations": len(valid_prices),
            "revenue_growth_std": revenue_growth_std,
            "ebitda_margin_std": ebitda_margin_std,
            "wacc_std": wacc_std,
            "terminal_growth_std": terminal_growth_std,
            "variance_reduction": "antithetic_variates",
            "mid_year_convention": mid_year,
        },
    )
