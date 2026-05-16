from typing import Any

from finagent.engine.models.financial import DCFInputs, DCFResult
from finagent.engine.compute.wacc import calculate_wacc


def calculate_dcf(
    inputs: DCFInputs,
    wacc_override: float | None = None,
    tg_override: float | None = None,
    mid_year: bool = False,
) -> DCFResult:
    """Run a full DCF valuation from structured inputs.

    What this code does that raw LLM cannot: deterministic arithmetic — projects
    revenue/EBITDA/FCF year-by-year, discounts each cash flow at the correct
    time period, computes a Gordon-Growth terminal value, and derives equity
    value from enterprise value minus net debt. Every number is reproducible
    from the typed DCFInputs; the LLM only selects the assumptions.

    Args:
        mid_year: If True, use mid-year convention where cash flows are discounted
            at (t - 0.5) instead of t, reflecting that cash flows arrive throughout
            the year rather than at year-end. Standard in investment banking DCFs.
            Typically increases valuation by 3-6%.
            Reference: Rosenbaum & Pearl, "Investment Banking" 3rd Ed., Chapter 8.
    """
    # 1. WACC
    if wacc_override is not None:
        cost_of_equity = None
        wacc = wacc_override
    else:
        cost_of_equity, wacc = calculate_wacc(
            inputs.risk_free_rate,
            inputs.beta,
            inputs.equity_risk_premium,
            inputs.cost_of_debt,
            inputs.tax_rate,
            inputs.debt_ratio,
        )

    tg = tg_override if tg_override is not None else inputs.terminal_growth_rate
    if tg >= wacc:
        raise ValueError(
            f"Terminal growth rate {tg} must be less than WACC {wacc} "
            "(Gordon Growth Model perpetuity is undefined when tg >= wacc)"
        )

    # 2-4. Project revenue, EBITDA, FCF (WACC/TG-independent)
    projected_fcf = _project_fcfs(inputs)
    projected_revenue: list[float] = []
    projected_ebitda: list[float] = []
    prev_revenue = inputs.revenue_base
    for g in inputs.revenue_growth_rates:
        rev = prev_revenue * (1 + g)
        projected_revenue.append(rev)
        projected_ebitda.append(rev * inputs.ebitda_margin)
        prev_revenue = rev

    n = len(projected_fcf)

    # 5. Discount FCFs
    # Mid-year convention: discount at (t - 0.5) instead of t, reflecting
    # cash flows arriving throughout the year, not just at year-end.
    offset = 0.5 if mid_year else 0.0
    pv_fcfs = [fcf / (1 + wacc) ** (i + 1 - offset) for i, fcf in enumerate(projected_fcf)]
    pv_fcf_total = sum(pv_fcfs)

    # 6-7. Terminal value (Gordon Growth Model)
    terminal_value = projected_fcf[-1] * (1 + tg) / (wacc - tg)
    pv_terminal = terminal_value / (1 + wacc) ** (n - offset)

    # 8-10. Valuation bridge: EV → Equity → Price
    enterprise_value = pv_fcf_total + pv_terminal
    equity_value = enterprise_value - inputs.net_debt
    implied_price = equity_value / inputs.shares_outstanding

    using_simplified = inputs.da_pct_revenue is None
    return DCFResult(
        cost_of_equity=cost_of_equity,
        wacc=wacc,
        projection_years=n,
        projected_revenue=projected_revenue,
        projected_ebitda=projected_ebitda,
        projected_fcf=projected_fcf,
        terminal_value=terminal_value,
        pv_terminal=pv_terminal,
        pv_fcf_total=pv_fcf_total,
        enterprise_value=enterprise_value,
        equity_value=equity_value,
        implied_price=implied_price,
        inputs=inputs,
        fcf_formula="standard_with_da" if not using_simplified else "simplified",
        fcf_formula_warning=(
            "WARNING: Simplified FCF formula used (D&A unavailable). "
            "Implied price may be overstated by 10-20% for capital-intensive companies. "
            "Configure FMP or Finnhub API key for D&A data."
        )
        if using_simplified
        else None,
    )


def calculate_sensitivity(
    inputs: DCFInputs,
    wacc_range: list[float],
    tg_range: list[float],
    mid_year: bool = False,
) -> dict[str, Any]:
    """Generate sensitivity table: implied price for each (WACC, terminal_growth) pair.

    Projects FCFs once (they don't depend on WACC or TG), then discounts at
    each (WACC, TG) combination. Returns None for cells where tg >= wacc
    (Gordon Growth Model undefined).
    """
    # --- Project FCFs once (WACC/TG-independent) ---
    projected_fcf = _project_fcfs(inputs)
    n = len(projected_fcf)
    offset = 0.5 if mid_year else 0.0

    # --- Discount at each (WACC, TG) pair ---
    implied_prices: list[list[float | None]] = []
    for w in wacc_range:
        row: list[float | None] = []
        for g in tg_range:
            if g >= w:
                row.append(None)
            else:
                pv_fcf = sum(
                    fcf / (1 + w) ** (i + 1 - offset) for i, fcf in enumerate(projected_fcf)
                )
                tv = projected_fcf[-1] * (1 + g) / (w - g)
                pv_tv = tv / (1 + w) ** (n - offset)
                ev = pv_fcf + pv_tv
                equity = ev - inputs.net_debt
                row.append(equity / inputs.shares_outstanding)
        implied_prices.append(row)
    return {
        "wacc_values": wacc_range,
        "tg_values": tg_range,
        "implied_prices": implied_prices,
    }


def _project_fcfs(inputs: DCFInputs) -> list[float]:
    """Project free cash flows from inputs. WACC/TG-independent.

    Shared by calculate_dcf (via inline code) and calculate_sensitivity.
    """
    projected_fcf: list[float] = []
    prev_revenue = inputs.revenue_base
    for g in inputs.revenue_growth_rates:
        rev = prev_revenue * (1 + g)
        ebitda = rev * inputs.ebitda_margin
        if inputs.da_pct_revenue is not None:
            da = rev * inputs.da_pct_revenue
            ebit = ebitda - da
            fcf = (
                ebit * (1 - inputs.tax_rate)
                + da
                - rev * inputs.capex_pct_revenue
                - rev * inputs.nwc_pct_revenue
            )
        else:
            fcf = (
                ebitda * (1 - inputs.tax_rate)
                - rev * inputs.capex_pct_revenue
                - rev * inputs.nwc_pct_revenue
            )
        projected_fcf.append(fcf)
        prev_revenue = rev
    return projected_fcf
