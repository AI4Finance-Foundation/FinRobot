"""Financial data processing: historical metrics extraction and deterministic forecasting.

What this code does that raw LLM cannot: deterministic, reproducible financial
calculations — YoY growth, margin analysis, CAGR, and multi-year forecasting.
Given identical inputs, always produces identical outputs with auditable formulas.
An LLM would produce plausible-but-varying numbers; this code guarantees CFA-standard
arithmetic every time.
"""

from __future__ import annotations

import math

from finrobot.engine.models.financial import (
    ForecastAssumptions,
    ForecastResult,
    HistoricalMetrics,
    MarginAssumptions,
)


def calculate_cagr(start: float, end: float, years: int) -> float | None:
    """Compound Annual Growth Rate per CFA Institute formula.

    CAGR = (end / start) ^ (1 / years) - 1

    Returns None if:
    - start <= 0 or years <= 0 (formula undefined)
    - start or end is NaN (upstream NaN-polluted data; caller should log and fall back)
    """
    if math.isnan(start) or math.isnan(end):
        return None
    if start <= 0 or years <= 0:
        return None
    return float((end / start) ** (1 / years) - 1)


def forecast_financials(
    historical: HistoricalMetrics,
    revenue_growth_assumptions: list[float],
    margin_assumptions: MarginAssumptions,
    tax_rate: float = 0.21,
) -> ForecastResult:
    """Deterministic multi-year financial forecast.

    Revenue = prev_revenue * (1 + growth_rate)
    EBITDA = revenue * ebitda_margin
    Net income = EBITDA * (1 - tax_rate)
    EPS = net_income / shares_outstanding

    Args:
        tax_rate: Corporate tax rate as decimal. Default 0.21 (US federal).
            Override for non-US companies (e.g. 0.196 Japan, 0.25 EU average).

    Uses target margins from margin_assumptions if provided, otherwise
    historical averages. Records all assumptions in ForecastAssumptions.
    """

    # Derive shares_outstanding from most recent year with non-zero EPS.
    # Refuse fallback to 1.0 — that would make EPS ≈ net_income (off by ~10⁹x).
    shares_outstanding: float | None = None
    for i in range(len(historical.eps) - 1, -1, -1):
        if historical.eps[i] != 0:
            shares_outstanding = historical.net_income[i] / historical.eps[i]
            break

    can_compute_eps = shares_outstanding is not None and shares_outstanding > 0

    # Determine margins: use target if provided, else historical average
    ebitda_margin = (
        margin_assumptions.ebitda_margin_target
        if margin_assumptions.ebitda_margin_target is not None
        else _mean(historical.ebitda_margin)
    )

    gross_margin = (
        margin_assumptions.gross_margin_target
        if margin_assumptions.gross_margin_target is not None
        else _mean(historical.gross_margin)
    )

    sga_ratio = (
        margin_assumptions.sga_ratio_target
        if margin_assumptions.sga_ratio_target is not None
        else _mean(historical.sga_ratio)
    )

    # Build forecast
    last_year = historical.years[-1]
    base_revenue = historical.revenue[-1]

    forecast_years: list[int] = []
    forecast_revenue: list[float] = []
    forecast_ebitda: list[float] = []
    forecast_net_income: list[float] = []
    forecast_eps: list[float] = []

    prev_revenue = base_revenue
    for i, growth_rate in enumerate(revenue_growth_assumptions):
        year = last_year + 1 + i
        revenue = prev_revenue * (1 + growth_rate)
        ebitda = revenue * ebitda_margin
        # Simplified: net_income ≈ EBITDA × (1 - tax_rate)
        # This over-taxes by not deducting D&A before tax.
        # Standard formula: net_income = (EBITDA - D&A) × (1 - tax_rate) + D&A
        # Impact: understates net income by ~5-15% for capital-intensive companies.
        # P2d will add D&A support when available from FMP provider.
        net_income = ebitda * (1 - tax_rate)
        eps = net_income / shares_outstanding if can_compute_eps and shares_outstanding else 0.0

        forecast_years.append(year)
        forecast_revenue.append(revenue)
        forecast_ebitda.append(ebitda)
        forecast_net_income.append(net_income)
        forecast_eps.append(eps)

        prev_revenue = revenue

    assumptions = ForecastAssumptions(
        revenue_growth_rates=revenue_growth_assumptions,
        gross_margin=gross_margin,
        ebitda_margin=ebitda_margin,
        sga_ratio=sga_ratio,
        tax_rate=tax_rate,
    )

    warnings: list[str] = [
        "Net income uses simplified formula: EBITDA*(1-tax). "
        "Understates by ~5-15% for capital-intensive companies. "
        "Standard formula requires D&A (available via FMP provider in P2d)."
    ]
    if not can_compute_eps:
        warnings.append(
            "Cannot derive shares_outstanding from historical data "
            "(all years have zero EPS). Forecast EPS set to 0.0 — "
            "do not use for per-share valuation."
        )

    return ForecastResult(
        years=forecast_years,
        revenue=forecast_revenue,
        ebitda=forecast_ebitda,
        net_income=forecast_net_income,
        eps=forecast_eps,
        assumptions=assumptions,
        warnings=warnings,
    )


def _mean(values: list[float]) -> float:
    """Simple arithmetic mean. Raises ValueError on empty list."""
    if not values:
        raise ValueError("Cannot compute mean of empty list")
    return sum(values) / len(values)
