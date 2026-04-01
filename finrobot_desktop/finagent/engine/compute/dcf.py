from finagent.engine.models.financial import DCFInputs, DCFResult
from finagent.engine.compute.wacc import calculate_wacc


def calculate_dcf(
    inputs: DCFInputs,
    wacc_override: float | None = None,
    tg_override: float | None = None,
) -> DCFResult:
    """Run a full DCF valuation from structured inputs.

    What this code does that raw LLM cannot: deterministic arithmetic — projects
    revenue/EBITDA/FCF year-by-year, discounts each cash flow at the correct
    time period, computes a Gordon-Growth terminal value, and derives equity
    value from enterprise value minus net debt. Every number is reproducible
    from the typed DCFInputs; the LLM only selects the assumptions.
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

    # 2-4. Project revenue, EBITDA, FCF
    projected_revenue = []
    projected_ebitda = []
    projected_fcf = []

    prev_revenue = inputs.revenue_base
    for g in inputs.revenue_growth_rates:
        rev = prev_revenue * (1 + g)
        ebitda = rev * inputs.ebitda_margin

        if inputs.da_pct_revenue is not None:
            # P2a standard: EBIT(1-T) + D&A - CapEx - ΔNWC
            da = rev * inputs.da_pct_revenue
            ebit = ebitda - da
            fcf = (
                ebit * (1 - inputs.tax_rate)
                + da
                - rev * inputs.capex_pct_revenue
                - rev * inputs.nwc_pct_revenue
            )
        else:
            # P1.5 simplified: EBITDA(1-T) - CapEx - ΔNWC
            fcf = (
                ebitda * (1 - inputs.tax_rate)
                - rev * inputs.capex_pct_revenue
                - rev * inputs.nwc_pct_revenue
            )

        projected_revenue.append(rev)
        projected_ebitda.append(ebitda)
        projected_fcf.append(fcf)
        prev_revenue = rev

    n = len(projected_fcf)

    # 5. Discount FCFs
    pv_fcfs = [fcf / (1 + wacc) ** (i + 1) for i, fcf in enumerate(projected_fcf)]
    pv_fcf_total = sum(pv_fcfs)

    # 6-7. Terminal value (Gordon Growth Model)
    terminal_value = projected_fcf[-1] * (1 + tg) / (wacc - tg)
    pv_terminal = terminal_value / (1 + wacc) ** n

    # 8-10. Valuation bridge: EV → Equity → Price
    enterprise_value = pv_fcf_total + pv_terminal
    equity_value = enterprise_value - inputs.net_debt
    implied_price = equity_value / inputs.shares_outstanding

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
        fcf_formula="standard_with_da" if inputs.da_pct_revenue is not None else "simplified",
    )


def calculate_sensitivity(
    inputs: DCFInputs,
    wacc_range: list[float],
    tg_range: list[float],
) -> dict[str, list]:
    """Generate sensitivity table: implied price for each (WACC, terminal_growth) pair.

    Returns None for cells where tg >= wacc (Gordon Growth Model undefined).
    """
    implied_prices = []
    for w in wacc_range:
        row = []
        for g in tg_range:
            if g >= w:
                row.append(None)
            else:
                result = calculate_dcf(inputs, wacc_override=w, tg_override=g)
                row.append(result.implied_price)
        implied_prices.append(row)
    return {
        "wacc_values": wacc_range,
        "tg_values": tg_range,
        "implied_prices": implied_prices,
    }
