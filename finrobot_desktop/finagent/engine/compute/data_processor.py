"""Financial data processing: historical metrics extraction and deterministic forecasting.

What this code does that raw LLM cannot: deterministic, reproducible financial
calculations — YoY growth, margin analysis, CAGR, and multi-year forecasting.
Given identical inputs, always produces identical outputs with auditable formulas.
An LLM would produce plausible-but-varying numbers; this code guarantees CFA-standard
arithmetic every time.
"""

from __future__ import annotations

from finagent.engine.models.financial import (
    FinancialData,
    ForecastAssumptions,
    ForecastResult,
    HistoricalMetrics,
    MarginAssumptions,
    PriceHistory,
)


def calculate_cagr(start: float, end: float, years: int) -> float | None:
    """Compound Annual Growth Rate per CFA Institute formula.

    CAGR = (end / start) ^ (1 / years) - 1

    Returns None if start <= 0 or years <= 0 (formula undefined).
    """
    if start <= 0 or years <= 0:
        return None
    return float((end / start) ** (1 / years) - 1)


def extract_historical_metrics(
    financial_data: list[FinancialData],
    price_data: PriceHistory | None = None,
    years: int = 5,
) -> HistoricalMetrics:
    """Extract multi-year historical metrics from FinancialData list.

    Sorts data oldest-first. Computes: YoY revenue growth, margins (gross,
    EBITDA, operating), SGA ratio, EPS, PE ratio (if price_data), and CAGR.

    COGS is derived as revenue * (1 - gross_margin).
    Operating income is derived as revenue * operating_margin.
    """
    # Sort oldest-first by timestamp
    sorted_data = sorted(financial_data, key=lambda d: d.timestamp)

    # Limit to requested number of years (take most recent N)
    if len(sorted_data) > years:
        sorted_data = sorted_data[-years:]

    year_list: list[int] = []
    revenue_list: list[float] = []
    revenue_growth: list[float | None] = []
    cogs_list: list[float] = []
    gross_profit_list: list[float] = []
    gross_margin_list: list[float] = []
    sga_list: list[float] = []
    sga_ratio_list: list[float] = []
    ebitda_list: list[float] = []
    ebitda_margin_list: list[float] = []
    operating_income_list: list[float] = []
    operating_margin_list: list[float] = []
    net_income_list: list[float] = []
    eps_list: list[float] = []
    pe_ratio_list: list[float | None] = []

    for i, fd in enumerate(sorted_data):
        year_list.append(fd.timestamp.year)
        revenue_list.append(fd.income.revenue)

        # YoY revenue growth: None for first year
        if i == 0:
            revenue_growth.append(None)
        else:
            prev_rev = sorted_data[i - 1].income.revenue
            if prev_rev != 0:
                revenue_growth.append((fd.income.revenue - prev_rev) / prev_rev)
            else:
                revenue_growth.append(None)

        # COGS = revenue * (1 - gross_margin)
        cogs = fd.income.revenue * (1 - fd.income.gross_margin)
        cogs_list.append(cogs)

        # Gross profit = revenue - COGS
        gross_profit_list.append(fd.income.revenue - cogs)

        # Margins (passthrough from provider)
        gross_margin_list.append(fd.income.gross_margin)

        # SGA
        sga = fd.income.sga_expense if fd.income.sga_expense is not None else 0.0
        sga_list.append(sga)
        sga_ratio_list.append(sga / fd.income.revenue if fd.income.revenue != 0 else 0.0)

        # EBITDA
        ebitda_list.append(fd.income.ebitda)
        ebitda_margin_list.append(fd.income.ebitda / fd.income.revenue if fd.income.revenue != 0 else 0.0)

        # Operating income = revenue * operating_margin
        operating_income_list.append(fd.income.revenue * fd.income.operating_margin)
        operating_margin_list.append(fd.income.operating_margin)

        # Net income
        net_income_list.append(fd.income.net_income)

        # EPS = net_income / shares_outstanding
        so = fd.market.shares_outstanding
        eps = fd.income.net_income / so
        eps_list.append(eps)

        # PE ratio: only if price_data is provided
        if price_data is not None and eps != 0:
            pe_ratio_list.append(price_data.current_price / eps)
        else:
            pe_ratio_list.append(None)

    # Revenue CAGR across all years
    n_periods = len(sorted_data) - 1
    cagr_revenue = calculate_cagr(revenue_list[0], revenue_list[-1], n_periods) if n_periods > 0 else None

    return HistoricalMetrics(
        years=year_list,
        revenue=revenue_list,
        revenue_growth_yoy=revenue_growth,
        cogs=cogs_list,
        gross_profit=gross_profit_list,
        gross_margin=gross_margin_list,
        sga=sga_list,
        sga_ratio=sga_ratio_list,
        ebitda=ebitda_list,
        ebitda_margin=ebitda_margin_list,
        operating_income=operating_income_list,
        operating_margin=operating_margin_list,
        net_income=net_income_list,
        eps=eps_list,
        pe_ratio=pe_ratio_list,
        cagr_revenue=cagr_revenue,
        ticker=sorted_data[0].ticker,
        price_data_available=price_data is not None,
    )


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
