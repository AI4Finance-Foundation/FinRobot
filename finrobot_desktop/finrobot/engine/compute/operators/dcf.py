from typing import Any

from finrobot.engine.models.financial import (
    DCFInputs,
    DCFResult,
    MarketImpliedCheck,
    MarketImpliedNature,
)
from finrobot.engine.compute.operators.wacc import calculate_wacc


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
    #
    # Gordon capitalizes the terminal-year FCF into perpetuity. With tg < wacc the
    # formula is mathematically defined even for a NEGATIVE terminal FCF — but then
    # it capitalizes a trough cash flow into a perpetual negative value, yielding a
    # negative terminal value and a negative implied price per share. That is a
    # nonsense valuation (a temporary capex/recession trough is NOT a perpetual
    # steady state), and a negative "fair value per share" must never reach the
    # report narrative or the LLM thesis prompt. Degrade the same way the tg >= wacc
    # case does: raise ValueError so the equity_research pipeline skips the DCF
    # chapter and falls back to relative valuation (see BUG-074).
    terminal_fcf = _terminal_fcf(inputs, projected_revenue[-1], tg)
    if terminal_fcf <= 0:
        raise ValueError(
            f"Steady-state terminal FCF is non-positive ({terminal_fcf:.3g}); the Gordon "
            "Growth Model would capitalize it into a perpetual negative terminal value and "
            "a negative implied price. DCF is not applicable — use relative valuation "
            "instead."
        )

    terminal_value = terminal_fcf * (1 + tg) / (wacc - tg)
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
        currency=inputs.currency,
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
    projected_revenue, _, projected_fcf = _project_full(inputs)
    n = len(projected_fcf)
    offset = 0.5 if mid_year else 0.0

    # --- Discount at each (WACC, TG) pair ---
    implied_prices: list[list[float | None]] = []
    for w in wacc_range:
        row: list[float | None] = []
        for g in tg_range:
            # Terminal FCF normalizes capex→D&A at the cell's own g (see
            # _terminal_fcf), so the grid centre matches calculate_dcf's base case.
            terminal_fcf = _terminal_fcf(inputs, projected_revenue[-1], g)
            if g >= w or terminal_fcf <= 0:
                row.append(None)
            else:
                pv_fcf = sum(
                    fcf / (1 + w) ** (i + 1 - offset) for i, fcf in enumerate(projected_fcf)
                )
                tv = terminal_fcf * (1 + g) / (w - g)
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
    rates = (
        growth_rates_override if growth_rates_override is not None else inputs.revenue_growth_rates
    )
    revenue: list[float] = []
    ebitda_list: list[float] = []
    fcfs: list[float] = []
    prev_revenue = inputs.revenue_base
    for g in rates:
        rev = prev_revenue * (1 + g)
        ebitda = rev * inputs.ebitda_margin
        # Standard FCF: EBIT(1-t) + D&A - CapEx - ΔNWC, where EBIT = EBITDA - D&A.
        # da_pct_revenue is always set by dcf_seed (filings → industry median fallback).
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


def _terminal_fcf(inputs: DCFInputs, terminal_revenue: float, terminal_growth: float) -> float:
    """Steady-state free cash flow that feeds the Gordon perpetuity.

    In stable growth, reinvestment normalizes: capex converges to maintenance
    (≈ D&A) plus the small net investment that funds perpetual growth, so
    ``capex = D&A × (1 + g)`` (net capex = g × D&A grows the asset base at g).
    Capitalizing the LAST EXPLICIT-YEAR FCF instead — which still carries the
    full growth-phase capex — capitalizes a perpetually-suppressed cash flow: a
    company growing at GDP (3%) cannot out-invest its depreciation by 67% forever.
    For a capex-heavy grower (TSLA: capex 9.2% vs D&A 5.5% of revenue, held into
    the perpetuity) that pinned the Gordon terminal value ~40% too low — implied
    $28 vs the steady-state-normalized ~$38. Only the perpetuity BASE normalizes;
    the explicit-forecast FCFs keep their growth-phase capex unchanged.

    The same normalization runs in calculate_dcf, calculate_sensitivity, and the
    reverse-DCF kernel (_price_for) so the base case, the sensitivity grid centre,
    and the market-implied solver all speak the same terminal economics.
    """
    rev = terminal_revenue
    da = rev * inputs.da_pct_revenue
    ebit = rev * inputs.ebitda_margin - da
    capex = da * (1 + terminal_growth)
    return ebit * (1 - inputs.tax_rate) + da - capex - rev * inputs.nwc_pct_revenue


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
        raise ValueError(f"Terminal growth {terminal_growth} must be less than WACC {wacc}")
    revenue, _, fcfs = _project_full(inputs, [growth_rate] * horizon_years)
    offset = 0.5 if mid_year else 0.0
    n = horizon_years
    pv_fcf: float = sum(f / (1 + wacc) ** (i + 1 - offset) for i, f in enumerate(fcfs))
    terminal_fcf = _terminal_fcf(inputs, revenue[-1], terminal_growth)
    tv = terminal_fcf * (1 + terminal_growth) / (wacc - terminal_growth)
    pv_tv = tv / (1 + wacc) ** (n - offset)
    enterprise_value = pv_fcf + pv_tv
    equity_value = enterprise_value - inputs.net_debt
    return float(equity_value / inputs.shares_outstanding)


def market_implied_check(
    inputs: DCFInputs,
    current_price: float,
    horizon_years: int,
    growth_bracket: tuple[float, float] = (-0.10, 0.50),
) -> MarketImpliedCheck:
    """Reverse-DCF reality check: what constant growth / discount rate does the
    CURRENT market price imply, over the same horizon the forward DCF used?

    Composes ``solve_for_implied_growth`` + ``solve_for_implied_wacc`` into the
    typed ``MarketImpliedCheck``. The key product signal is ``growth_unreachable``:
    when no growth in ``growth_bracket`` reaches the market price (e.g. TSLA —
    even +50%/yr implies only ~$65 vs a $418 price), the market is pricing option
    value no cash-flow model can capture, and a fundamentals point target must
    not be presented as the headline. ``horizon_years`` is threaded from the
    caller (the forward DCF's projection_years) so implied vs seeded growth are
    compared over the same window.
    """
    g = solve_for_implied_growth(
        inputs, current_price, horizon_years=horizon_years, bracket=growth_bracket
    )
    w = solve_for_implied_wacc(inputs, current_price)
    implied_growth = g.get("implied_growth")
    # Unreachable on the HIGH side (price above what even max growth justifies)
    # is the option-value signal we care about; surface the ceiling so the
    # narrative can quantify the gap ("even {ceiling:.0%} growth → ${ceiling_price}").
    hi_growth = growth_bracket[1]
    ceiling_price = g.get("price_at_hi")
    unreachable = implied_growth is None and (
        ceiling_price is not None and current_price > ceiling_price
    )
    return MarketImpliedCheck(
        horizon_years=horizon_years,
        implied_growth=implied_growth,
        implied_wacc=w.get("implied_wacc"),
        growth_unreachable=unreachable,
        growth_ceiling=hi_growth if unreachable else None,
        ceiling_price=ceiling_price if unreachable else None,
    )


# An "option-value" verdict (no growth in the bracket explains the price) is
# only asserted if it survives the most FAVOURABLE plausible WACC — one this
# much lower. A lower discount rate raises the reachable ceiling, so if a WACC
# this far below the name's own CAPM rate rescues the price into the solvable
# range, the unreachability is a discount-rate artifact (near_ceiling), not
# robust optionality. 2pp ≈ the routine estimation error in beta / ERP, so it's
# the honest "could a reasonable analyst's WACC explain this?" test.
_WACC_SENSITIVITY_BAND = 0.02


def classify_market_implied_nature(
    inputs: DCFInputs,
    current_price: float,
    horizon_years: int,
    growth_bracket: tuple[float, float] = (-0.10, 0.50),
) -> MarketImpliedNature:
    """Classify what the LIVE price says about a name, re-solved from scratch.

    Composes :func:`market_implied_check` with a one-sided WACC-robustness test
    so the option-value verdict is never a silent function of the discount-rate
    assumption. See :class:`MarketImpliedNature` for why this is a per-name
    *classification* and not a cross-name implied-growth ranking.

    Pure: no I/O. ``current_price`` is the caller's live price; ``inputs`` and
    ``horizon_years`` come from the name's own stored DCF (so the implied growth
    is anchored to the same window the forward DCF used).
    """
    base = market_implied_check(inputs, current_price, horizon_years, growth_bracket)
    if not base.growth_unreachable:
        # Reachable (or below the bracket floor — implied_growth None but not the
        # high-side option-value signal). Carry the per-name implied growth as
        # context; do NOT promote it to a cross-name rank.
        return MarketImpliedNature(
            kind="fundamental",
            implied_growth=base.implied_growth,
            implied_wacc=base.implied_wacc,
            horizon_years=horizon_years,
        )

    # Unreachable at the name's own WACC. Re-solve at the most favourable
    # plausible WACC (a band lower); if that rescues the price, the verdict is
    # WACC-sensitive, not robust optionality.
    _, own_wacc = calculate_wacc(
        inputs.risk_free_rate,
        inputs.beta,
        inputs.equity_risk_premium,
        inputs.cost_of_debt,
        inputs.tax_rate,
        inputs.debt_ratio,
    )
    favorable = own_wacc - _WACC_SENSITIVITY_BAND
    robust = True
    # The Gordon model needs WACC > terminal growth; only probe a lower WACC if
    # there's room. With no room (WACC already near terminal growth) we can't
    # rescue it, so the unreachability stands.
    if favorable > inputs.terminal_growth_rate + 0.005:
        rescue = solve_for_implied_growth(
            inputs,
            current_price,
            horizon_years=horizon_years,
            bracket=growth_bracket,
            wacc_override=favorable,
        )
        if rescue.get("implied_growth") is not None:
            robust = False

    return MarketImpliedNature(
        kind="option_value" if robust else "near_ceiling",
        horizon_years=horizon_years,
        implied_wacc=base.implied_wacc,
        growth_ceiling=base.growth_ceiling,
        ceiling_price=base.ceiling_price,
    )


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

    # converged ⇔ the bracket actually collapsed below tolerance. If we exited
    # because we hit max_iterations on a wide/flat bracket, `mid` is only a
    # coarse approximation — flag it instead of presenting it as a solved value.
    converged = (hi - lo) < tolerance
    result = {
        **base,
        "implied_growth": mid,
        "computed_price": p_mid,
        "iterations": iterations,
        "converged": converged,
    }
    if not converged:
        result["message"] = (
            f"反推增长率在 {iterations} 次迭代后未收敛（区间宽度 {hi - lo:.2e} > "
            f"容差 {tolerance:.0e}）。${target_price:.2f} 对应的隐含增长率约为 {mid:.2%}，"
            "为近似值，请勿当作精确解。"
        )
    return result


def compute_dcf_implied_price(
    inputs: DCFInputs,
    overrides: dict[str, float],
) -> float:
    """Thin entry point: run a full DCF with one or more assumption overrides
    and return only the implied equity price per share.

    Used by the IC debate divergence recomputation layer so that bull/bear
    sides can each substitute their own WACC or terminal-growth assumption into
    the *same* DCF arithmetic that the single-stock report used — zero DCF math
    lives outside dcf.py.

    Supported override keys:
        ``"wacc"``              — replaces the CAPM-derived WACC.
        ``"terminal_growth"``   — replaces ``inputs.terminal_growth_rate``.

    Any key not in the supported set raises ``KeyError`` so callers discover
    mismatches immediately rather than silently ignoring them.

    Args:
        inputs:    Frozen DCFInputs produced by seed_dcf_inputs for the ticker.
        overrides: Subset of assumption overrides; must not be empty.

    Returns:
        Implied equity price per share as a plain float.

    Raises:
        KeyError:   An unsupported override key was supplied.
        ValueError: terminal_growth >= wacc (Gordon Growth Model undefined).
    """
    _SUPPORTED = {"wacc", "terminal_growth"}
    unknown = set(overrides) - _SUPPORTED
    if unknown:
        raise KeyError(f"Unsupported DCF override key(s): {unknown!r}")

    wacc_override: float | None = overrides.get("wacc")
    tg_override: float | None = overrides.get("terminal_growth")

    result = calculate_dcf(inputs, wacc_override=wacc_override, tg_override=tg_override)
    return result.implied_price


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
    revenue, _, fcfs = _project_full(inputs)
    n = len(fcfs)
    offset = 0.5 if mid_year else 0.0
    # Terminal capex normalizes to D&A (see _terminal_fcf) — same perpetuity base
    # calculate_dcf uses, so the reverse-WACC solve round-trips the forward DCF.
    terminal_fcf = _terminal_fcf(inputs, revenue[-1], tg)

    def _price_at(wacc: float) -> float:
        pv_fcf: float = sum(f / (1 + wacc) ** (i + 1 - offset) for i, f in enumerate(fcfs))
        tv = terminal_fcf * (1 + tg) / (wacc - tg)
        pv_tv = tv / (1 + wacc) ** (n - offset)
        return float(((pv_fcf + pv_tv) - inputs.net_debt) / inputs.shares_outstanding)

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

    # See solve_for_implied_growth: distinguish a collapsed bracket from a
    # max-iterations bail-out so the caller never treats a coarse mid as exact.
    converged = (hi - lo) < tolerance
    result = {
        **base,
        "implied_wacc": mid,
        "computed_price": p_mid,
        "iterations": iterations,
        "converged": converged,
    }
    if not converged:
        result["message"] = (
            f"反推 WACC 在 {iterations} 次迭代后未收敛（区间宽度 {hi - lo:.2e} > "
            f"容差 {tolerance:.0e}）。${target_price:.2f} 对应的隐含 WACC 约为 {mid:.2%}，"
            "为近似值，请勿当作精确解。"
        )
    return result


def solve_for_implied_horizon(
    inputs: DCFInputs,
    target_price: float,
    growth_rate: float,
    max_horizon: int = 30,
    wacc_override: float | None = None,
    tg_override: float | None = None,
    mid_year: bool = False,
) -> dict[str, Any]:
    """Reverse DCF — solve for the number of explicit high-growth years that
    justifies ``target_price``, holding a CONSTANT ``growth_rate`` and the
    discount rate fixed. Completes the reverse-DCF trio (growth / WACC / horizon).

    Asymmetry caveat — this solver is NOT a drop-in sibling of
    ``solve_for_implied_growth`` / ``solve_for_implied_wacc``. Those hold a fully
    determined input set and solve one scalar. This one needs an *additional*
    free choice — the constant ``growth_rate`` to hold — because horizon and
    growth trade off against each other: at 40% growth the market price may imply
    ~7 years, at 25% the same price implies ~14, at 20% it may be unreachable.
    The returned ``assumed_growth`` echoes that fixed axis; callers MUST surface
    it so the answer is never read as a standalone "the market implies N years"
    (it is "under g = X%, the market implies N years"). There is no objective
    load-bearing axis — only this slice through the (growth, horizon, WACC) face.

    horizon is integer-grained (a count of explicit forecast years), so the
    returned ``implied_horizon`` is a LINEAR INTERPOLATION between the two
    bracketing integer years — an approximation, never an exact root.

    Returns a dict shaped to fill ``DcfReverseResult`` (``solve_for="horizon"``),
    with ``bracket`` / ``price_at_lo`` / ``price_at_hi`` carrying the horizon-axis
    bracket and its edge prices.
    """
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

    # Price at each integer horizon, holding the constant growth_rate. Stops if
    # the Gordon perpetuity becomes undefined (tg >= wacc) — _price_for raises.
    prices: list[tuple[int, float]] = []
    for h in range(1, max_horizon + 1):
        try:
            prices.append((h, _price_for(inputs, growth_rate, wacc, tg, h, mid_year)))
        except ValueError:
            break

    base: dict[str, Any] = {
        "target_price": target_price,
        "wacc": wacc,
        "terminal_growth": tg,
        "assumed_growth": growth_rate,
        "horizon_years": max_horizon,
        "implied_horizon": None,
        "computed_price": None,
        "iterations": len(prices),
    }
    if not prices:
        return {
            **base,
            "bracket": [1.0, float(max_horizon)],
            "price_at_lo": 0.0,
            "price_at_hi": 0.0,
            "message": (
                f"在固定增长率 {growth_rate:.0%} 下，永续增长率 {tg:.1%} 不低于 WACC "
                f"{wacc:.1%}，Gordon 模型无定义，无法反推年限。"
            ),
        }

    p_lo = prices[0][1]
    p_hi = prices[-1][1]
    base["bracket"] = [float(prices[0][0]), float(prices[-1][0])]
    base["price_at_lo"] = p_lo
    base["price_at_hi"] = p_hi

    # Price is monotonically increasing in horizon (longer high-growth window ⇒
    # more value). Target outside [p_lo, p_hi] ⇒ no horizon in range justifies it.
    if not (p_lo <= target_price <= p_hi):
        return {
            **base,
            "message": (
                f"在固定增长率 {growth_rate:.0%} 下，目标价 ${target_price:.2f} 落在 "
                f"1–{max_horizon} 年可达区间 [${p_lo:.2f}, ${p_hi:.2f}] 之外。"
                f"{'增长假设太低、再长的高增长窗口也够不着' if target_price > p_hi else '当前价已低于最短窗口隐含价'}。"
                f"换一个固定增长率会得到不同年限——隐含年限是增长假设的函数。"
            ),
        }

    # Linear-interpolate the fractional horizon between the two bracketing years.
    implied = float(prices[-1][0])
    for (h0, p0), (h1, p1) in zip(prices, prices[1:]):
        if p0 <= target_price <= p1:
            implied = h0 + (target_price - p0) / (p1 - p0) * (h1 - h0) if p1 != p0 else float(h0)
            break
    return {
        **base,
        "implied_horizon": implied,
        "computed_price": target_price,
        "message": (
            f"在固定增长率 {growth_rate:.0%}、WACC {wacc:.1%} 下，${target_price:.2f} 隐含约 "
            f"{implied:.1f} 年高增长窗口（整数年线性插值近似）。注意：这个年限取决于所固定的 "
            f"{growth_rate:.0%} 增长——换一个同样合理的增长率会得到不同年限。"
        ),
    }
