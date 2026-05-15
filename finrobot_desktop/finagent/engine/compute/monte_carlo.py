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
) -> MonteCarloResult:
    """Run N DCF simulations with randomized assumptions — fully vectorized.

    All N simulations execute as NumPy array operations: revenue projections,
    FCF computation, discounting, and terminal value are computed across all
    simulations simultaneously. No Python for-loop over simulations.

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

    Returns:
        MonteCarloResult with distribution statistics.

    Raises:
        ValueError: If fewer than 100 valid simulations complete.
    """
    rng = np.random.default_rng(seed)
    n = n_simulations
    n_years = len(inputs.revenue_growth_rates)
    base_growth = np.array(inputs.revenue_growth_rates)  # (n_years,)

    # --- Generate all perturbations at once ---
    # Revenue growth: (n, n_years) matrix
    growth_noise = rng.normal(0, revenue_growth_std, size=(n, n_years))
    sim_growth = base_growth[np.newaxis, :] + growth_noise  # (n, n_years)

    # EBITDA margin: (n,) vector, floored at 1%
    sim_margin = np.maximum(0.01, inputs.ebitda_margin + rng.normal(0, ebitda_margin_std, size=n))

    # Terminal growth rate: (n,) vector, floored at 0.5%
    sim_tgr = np.maximum(
        0.005, inputs.terminal_growth_rate + rng.normal(0, terminal_growth_std, size=n)
    )

    # WACC via CAPM: perturb risk-free rate, ERP, beta → compute WACC vectorized
    sim_rfr = np.maximum(0.005, inputs.risk_free_rate + rng.normal(0, wacc_std * 0.5, size=n))
    sim_erp = np.maximum(0.02, inputs.equity_risk_premium + rng.normal(0, wacc_std, size=n))
    sim_beta = np.maximum(0.3, inputs.beta + rng.normal(0, 0.1, size=n))

    # CAPM: CoE = rf + beta * ERP
    sim_coe = sim_rfr + sim_beta * sim_erp
    equity_ratio = 1 - inputs.debt_ratio
    after_tax_debt = inputs.cost_of_debt * (1 - inputs.tax_rate)
    sim_wacc = equity_ratio * sim_coe + inputs.debt_ratio * after_tax_debt  # (n,)

    # Gordon Growth requires WACC > TGR — clamp TGR where violated
    violating = sim_wacc <= sim_tgr
    sim_tgr = np.where(violating, sim_wacc - 0.005, sim_tgr)

    # --- Vectorized DCF projection ---
    # Project revenue year by year: rev[t] = rev[t-1] * (1 + growth[t])
    # cumulative_growth[i, t] = product(1 + growth[i, 0..t])
    cumulative_growth = np.cumprod(1 + sim_growth, axis=1)  # (n, n_years)
    sim_revenue = inputs.revenue_base * cumulative_growth  # (n, n_years)

    # EBITDA = revenue * margin
    sim_ebitda = sim_revenue * sim_margin[:, np.newaxis]  # (n, n_years)

    # FCF computation — two paths based on D&A availability
    if inputs.da_pct_revenue is not None:
        # Standard: EBIT(1-T) + D&A - CapEx - ΔNWC
        sim_da = sim_revenue * inputs.da_pct_revenue
        sim_ebit = sim_ebitda - sim_da
        sim_fcf = (
            sim_ebit * (1 - inputs.tax_rate)
            + sim_da
            - sim_revenue * inputs.capex_pct_revenue
            - sim_revenue * inputs.nwc_pct_revenue
        )
    else:
        # Simplified: EBITDA(1-T) - CapEx - ΔNWC
        sim_fcf = (
            sim_ebitda * (1 - inputs.tax_rate)
            - sim_revenue * inputs.capex_pct_revenue
            - sim_revenue * inputs.nwc_pct_revenue
        )

    # --- Discount factors: 1 / (1 + wacc)^t for t = 1..n_years ---
    periods = np.arange(1, n_years + 1, dtype=np.float64)  # (n_years,)
    # (n, n_years) = (n,1)^(1, n_years)
    discount_factors = 1.0 / (1 + sim_wacc[:, np.newaxis]) ** periods[np.newaxis, :]

    # PV of projected FCFs
    pv_fcf_total = np.sum(sim_fcf * discount_factors, axis=1)  # (n,)

    # Terminal value (Gordon Growth Model)
    last_fcf = sim_fcf[:, -1]  # (n,)
    terminal_value = last_fcf * (1 + sim_tgr) / (sim_wacc - sim_tgr)  # (n,)
    pv_terminal = terminal_value / (1 + sim_wacc) ** n_years  # (n,)

    # Enterprise value → equity value → implied price
    enterprise_value = pv_fcf_total + pv_terminal
    equity_value = enterprise_value - inputs.net_debt
    implied_prices = equity_value / inputs.shares_outstanding  # (n,)

    # --- Filter valid prices ---
    valid_mask = (implied_prices > 0) & (implied_prices < inputs.revenue_base)
    valid_prices = implied_prices[valid_mask]

    if len(valid_prices) < 100:
        raise ValueError(
            f"Only {len(valid_prices)} valid simulations out of {n_simulations}. "
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
        },
    )
