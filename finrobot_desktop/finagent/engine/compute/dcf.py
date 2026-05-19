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

    # 2-4. Project revenue, EBITDA, FCF (WACC/TG-independent) in a single pass
    projected_revenue, projected_ebitda, projected_fcf = _project_full(inputs)
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
    _, _, projected_fcf = _project_full(inputs)
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


def _project_full(
    inputs: DCFInputs,
    growth_rates_override: list[float] | None = None,
) -> tuple[list[float], list[float], list[float]]:
    """Project revenue, EBITDA, and free cash flows in a single pass.

    WACC/TG-independent. Returns parallel lists indexed by projection year.
    Shared by calculate_dcf, calculate_sensitivity, and the reverse-DCF
    solvers so we only walk the growth schedule once per call.

    Args:
        growth_rates_override: When provided, replaces inputs.revenue_growth_rates.
            Used by reverse-DCF to project under a hypothetical constant rate.
    """
    rates = growth_rates_override if growth_rates_override is not None else inputs.revenue_growth_rates
    revenue: list[float] = []
    ebitda_list: list[float] = []
    fcfs: list[float] = []
    prev_revenue = inputs.revenue_base
    for g in rates:
        rev = prev_revenue * (1 + g)
        ebitda = rev * inputs.ebitda_margin
        # Standard FCF: EBIT(1-t) + D&A - CapEx - ΔNWC, where EBIT = EBITDA - D&A.
        # The simplified branch that dropped the D&A tax shield is gone — dcf_seed
        # guarantees da_pct_revenue is non-None (filings → industry median fallback).
        da = rev * inputs.da_pct_revenue
        ebit = ebitda - da
        fcf = (
            ebit * (1 - inputs.tax_rate)
            + da
            - rev * inputs.capex_pct_revenue
            - rev * inputs.nwc_pct_revenue
        )
        revenue.append(rev)
        ebitda_list.append(ebitda)
        fcfs.append(fcf)
        prev_revenue = rev
    return revenue, ebitda_list, fcfs


def _price_for(
    inputs: DCFInputs,
    growth_rate: float,
    wacc: float,
    terminal_growth: float,
    horizon_years: int,
    mid_year: bool,
) -> float:
    """Inner pricing kernel for reverse-DCF: deterministic implied price under
    a constant annual growth rate.

    Inverse-DCF solvers call this with a candidate growth rate (or WACC), so we
    keep it free of model construction overhead — pure arithmetic over Pydantic
    field reads.

    Raises:
        ValueError: when terminal_growth >= wacc (Gordon Growth Model undefined).
    """
    if terminal_growth >= wacc:
        raise ValueError(
            f"Terminal growth {terminal_growth} must be less than WACC {wacc}"
        )
    _, _, fcfs = _project_full(inputs, [growth_rate] * horizon_years)
    offset = 0.5 if mid_year else 0.0
    n = horizon_years
    pv_fcf = sum(f / (1 + wacc) ** (i + 1 - offset) for i, f in enumerate(fcfs))
    tv = fcfs[-1] * (1 + terminal_growth) / (wacc - terminal_growth)
    pv_tv = tv / (1 + wacc) ** (n - offset)
    enterprise_value = pv_fcf + pv_tv
    equity_value = enterprise_value - inputs.net_debt
    return equity_value / inputs.shares_outstanding


def solve_for_implied_growth(
    inputs: DCFInputs,
    target_price: float,
    horizon_years: int = 5,
    bracket: tuple[float, float] = (-0.10, 0.50),
    tolerance: float = 1e-4,
    max_iterations: int = 60,
    wacc_override: float | None = None,
    tg_override: float | None = None,
    mid_year: bool = False,
) -> dict[str, Any]:
    """Reverse DCF — solve for the constant annual revenue growth rate that
    justifies ``target_price`` (typically the current market price).

    The standard DCF answers "given my assumptions, what's fair value?". This
    inverts it: given the market's price, what growth rate is the market
    implicitly pricing in? A retail user can then judge whether that growth is
    plausible, conservative, or absurd — a Damodaran-style sanity check that
    most retail tooling skips.

    Implementation: bisection over [bracket[0], bracket[1]] on the growth axis.
    implied_price is monotonically increasing in growth, so a single root
    exists when target_price ∈ [price_at_lo, price_at_hi].

    Returns a dict with implied_growth (or None if target outside reachable
    range), the bracket-edge prices for context, and the WACC / terminal growth
    used so the caller can show the user the full assumption set.
    """
    # Resolve WACC and terminal growth (same precedence as calculate_dcf)
    if wacc_override is not None:
        wacc = wacc_override
    else:
        _, wacc = calculate_wacc(
            inputs.risk_free_rate,
            inputs.beta,
            inputs.equity_risk_premium,
            inputs.cost_of_debt,
            inputs.tax_rate,
            inputs.debt_ratio,
        )
    tg = tg_override if tg_override is not None else inputs.terminal_growth_rate

    lo, hi = bracket
    p_lo = _price_for(inputs, lo, wacc, tg, horizon_years, mid_year)
    p_hi = _price_for(inputs, hi, wacc, tg, horizon_years, mid_year)

    base = {
        "target_price": target_price,
        "wacc": wacc,
        "terminal_growth": tg,
        "horizon_years": horizon_years,
        "bracket": [lo, hi],
        "price_at_lo": p_lo,
        "price_at_hi": p_hi,
    }

    if not (p_lo <= target_price <= p_hi):
        return {
            **base,
            "implied_growth": None,
            "computed_price": None,
            "iterations": 0,
            "message": (
                f"目标价 ${target_price:.2f} 在当前模型的增长区间 [{lo:.0%}, {hi:.0%}] 内"
                f"无解。{lo:.0%} 增长 → ${p_lo:.2f}；{hi:.0%} 增长 → ${p_hi:.2f}。"
                f"市场要么在为区间外的极端增长定价，要么其他输入（毛利 / WACC / 净债）"
                f"需要重新检查。"
            ),
        }

    iterations = 0
    mid = (lo + hi) / 2.0
    p_mid = _price_for(inputs, mid, wacc, tg, horizon_years, mid_year)
    for iterations in range(1, max_iterations + 1):
        if hi - lo < tolerance:
            break
        mid = (lo + hi) / 2.0
        p_mid = _price_for(inputs, mid, wacc, tg, horizon_years, mid_year)
        if p_mid < target_price:
            lo = mid
        else:
            hi = mid

    return {
        **base,
        "implied_growth": mid,
        "computed_price": p_mid,
        "iterations": iterations,
    }


def solve_for_implied_wacc(
    inputs: DCFInputs,
    target_price: float,
    bracket: tuple[float, float] = (0.04, 0.25),
    tolerance: float = 1e-4,
    max_iterations: int = 60,
    tg_override: float | None = None,
    mid_year: bool = False,
) -> dict[str, Any]:
    """Reverse DCF — solve for the discount rate (WACC) implied by ``target_price``.

    Companion to solve_for_implied_growth: instead of "what growth does the
    market assume?", this answers "what discount rate is the market applying?".
    Useful when growth assumptions are externally anchored (analyst consensus,
    management guidance) and the question is whether the market is pricing in
    elevated risk.

    Implementation: bisection on the WACC axis. implied_price is monotonically
    DECREASING in WACC, so the comparison direction flips vs solve_for_implied_growth.
    """
    tg = tg_override if tg_override is not None else inputs.terminal_growth_rate

    lo, hi = bracket
    # tg < wacc constraint — clip bracket lower bound
    if lo <= tg:
        lo = tg + 0.001

    # Use the inputs' own growth schedule (no override here — the user is
    # solving for the discount rate they are willing to accept under their
    # own growth assumptions).
    _, _, fcfs = _project_full(inputs)
    n = len(fcfs)
    offset = 0.5 if mid_year else 0.0

    def _price_at(wacc: float) -> float:
        pv_fcf = sum(f / (1 + wacc) ** (i + 1 - offset) for i, f in enumerate(fcfs))
        tv = fcfs[-1] * (1 + tg) / (wacc - tg)
        pv_tv = tv / (1 + wacc) ** (n - offset)
        return ((pv_fcf + pv_tv) - inputs.net_debt) / inputs.shares_outstanding

    p_lo = _price_at(lo)
    p_hi = _price_at(hi)

    base = {
        "target_price": target_price,
        "terminal_growth": tg,
        "horizon_years": n,
        "bracket": [lo, hi],
        "price_at_lo": p_lo,  # higher price (lower wacc)
        "price_at_hi": p_hi,  # lower price (higher wacc)
    }

    # Price is decreasing in WACC, so target must sit between p_hi (low) and p_lo (high)
    if not (p_hi <= target_price <= p_lo):
        return {
            **base,
            "implied_wacc": None,
            "computed_price": None,
            "iterations": 0,
            "message": (
                f"目标价 ${target_price:.2f} 在 WACC 区间 [{lo:.0%}, {hi:.0%}] 内无解。"
                f"WACC {lo:.0%} → ${p_lo:.2f}；WACC {hi:.0%} → ${p_hi:.2f}。"
            ),
        }

    iterations = 0
    mid = (lo + hi) / 2.0
    p_mid = _price_at(mid)
    for iterations in range(1, max_iterations + 1):
        if hi - lo < tolerance:
            break
        mid = (lo + hi) / 2.0
        p_mid = _price_at(mid)
        if p_mid > target_price:
            lo = mid  # need a higher wacc to push price down
        else:
            hi = mid  # need a lower wacc to push price up

    return {
        **base,
        "implied_wacc": mid,
        "computed_price": p_mid,
        "iterations": iterations,
    }
