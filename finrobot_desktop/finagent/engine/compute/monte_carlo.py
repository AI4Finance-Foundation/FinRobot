"""Monte Carlo fair value simulation.

Runs N DCF simulations with randomized assumption distributions
to produce a probability distribution of implied share prices.

This is deterministic code the LLM cannot replicate: it runs thousands of
DCF valuations with statistically varied inputs and computes percentile
statistics on the resulting price distribution.
"""

from __future__ import annotations

import math
import random
import statistics
from typing import Any

from pydantic import BaseModel, Field

from finagent.engine.compute.dcf import calculate_dcf
from finagent.engine.compute.wacc import calculate_wacc
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


def _percentile(sorted_data: list[float], pct: float) -> float:
    """Compute percentile from sorted data using linear interpolation."""
    if not sorted_data:
        return 0.0
    n = len(sorted_data)
    k = (pct / 100) * (n - 1)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    return sorted_data[f] * (c - k) + sorted_data[c] * (k - f)


def _histogram(data: list[float], n_bins: int) -> tuple[list[int], list[float]]:
    """Compute histogram counts and bin edges."""
    if not data:
        return [], []
    lo = min(data)
    hi = max(data)
    if lo == hi:
        return [len(data)], [lo, hi + 1.0]

    bin_width = (hi - lo) / n_bins
    edges = [lo + i * bin_width for i in range(n_bins + 1)]
    counts = [0] * n_bins

    for val in data:
        idx = int((val - lo) / bin_width)
        if idx >= n_bins:
            idx = n_bins - 1
        counts[idx] += 1

    return counts, edges


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
    """Run N DCF simulations with randomized assumptions.

    Each simulation perturbs the base assumptions with Gaussian noise:
    - Revenue growth rates: each year +-revenue_growth_std
    - EBITDA margin: +-ebitda_margin_std
    - WACC components (risk-free rate, ERP, beta): +-wacc_std
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
    rng = random.Random(seed)
    prices: list[float] = []

    for _ in range(n_simulations):
        # Perturb revenue growth rates
        sim_growth = [
            g + rng.gauss(0, revenue_growth_std)
            for g in inputs.revenue_growth_rates
        ]

        # Perturb EBITDA margin (floor at 1%)
        sim_margin = max(0.01, inputs.ebitda_margin + rng.gauss(0, ebitda_margin_std))

        # Perturb terminal growth rate (floor at 0.5%)
        sim_tgr = max(0.005, inputs.terminal_growth_rate + rng.gauss(0, terminal_growth_std))

        # Perturb WACC components
        sim_rfr = max(0.005, inputs.risk_free_rate + rng.gauss(0, wacc_std * 0.5))
        sim_erp = max(0.02, inputs.equity_risk_premium + rng.gauss(0, wacc_std))
        sim_beta = max(0.3, inputs.beta + rng.gauss(0, 0.1))

        _, sim_wacc = calculate_wacc(
            risk_free_rate=sim_rfr,
            beta=sim_beta,
            equity_risk_premium=sim_erp,
            cost_of_debt=inputs.cost_of_debt,
            tax_rate=inputs.tax_rate,
            debt_ratio=inputs.debt_ratio,
        )

        # Gordon Growth Model requires WACC > TGR
        if sim_wacc <= sim_tgr:
            sim_tgr = sim_wacc - 0.005

        # Build perturbed inputs
        sim_inputs = inputs.model_copy(
            update={
                "revenue_growth_rates": sim_growth,
                "ebitda_margin": sim_margin,
                "terminal_growth_rate": sim_tgr,
                "risk_free_rate": sim_rfr,
                "equity_risk_premium": sim_erp,
                "beta": sim_beta,
            }
        )

        try:
            result = calculate_dcf(sim_inputs, wacc_override=sim_wacc)
            # Sanity check: price must be positive and not astronomically large
            if 0 < result.implied_price < inputs.revenue_base:
                prices.append(result.implied_price)
        except (ValueError, ZeroDivisionError):
            continue

    if len(prices) < 100:
        raise ValueError(
            f"Only {len(prices)} valid simulations out of {n_simulations}. "
            "Try widening assumptions or increasing n_simulations."
        )

    prices.sort()

    # Percentiles
    pct_keys = [5, 10, 25, 50, 75, 90, 95]
    percentiles = {str(p): round(_percentile(prices, p), 2) for p in pct_keys}

    # Mean and std
    mean_price = statistics.mean(prices)
    std_price = statistics.stdev(prices) if len(prices) > 1 else 0.0

    # Histogram
    counts, edges = _histogram(prices, n_bins)

    # Current price percentile
    below_count = sum(1 for p in prices if p <= current_price)
    current_pct = (below_count / len(prices)) * 100

    return MonteCarloResult(
        implied_prices=prices,
        percentiles=percentiles,
        mean=round(mean_price, 2),
        std=round(std_price, 2),
        current_price_percentile=round(current_pct, 1),
        histogram_bins=[round(b, 2) for b in edges],
        histogram_counts=counts,
        n_valid=len(prices),
        assumptions_used={
            "n_simulations": n_simulations,
            "valid_simulations": len(prices),
            "revenue_growth_std": revenue_growth_std,
            "ebitda_margin_std": ebitda_margin_std,
            "wacc_std": wacc_std,
            "terminal_growth_std": terminal_growth_std,
        },
    )
