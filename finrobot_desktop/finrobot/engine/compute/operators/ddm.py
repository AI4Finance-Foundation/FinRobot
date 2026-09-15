"""Dividend Discount Model — for banks, utilities, and dividend-paying stocks.

Banks don't have traditional "free cash flow" because their earnings come from
net interest income and fee income. Dividends are the primary cash return to
equity holders, making DDM the standard valuation method.

Formula:
    Equity Value = Sum(PV of projected dividends) + PV of terminal dividend
    Terminal = Dividend_n * (1 + tg) / (cost_of_equity - tg)

Note: DDM uses cost of equity (not WACC) as discount rate,
because dividends are paid to equity holders only.

Reference: Damodaran, "Investment Valuation" 3rd Ed., Chapter 13 (Dividend
Discount Models). Also Rosenbaum & Pearl, "Investment Banking" 3rd Ed.
"""

from __future__ import annotations

from typing import TypedDict

from finrobot.engine.models.financial import DDMInputs, DDMResult
from finrobot.engine.models.valuation_thresholds import MIN_GORDON_SPREAD


class DDMSensitivity(TypedDict):
    coe_values: list[float]
    tg_values: list[float]
    implied_prices: list[list[float | None]]


def calculate_ddm(inputs: DDMInputs) -> DDMResult:
    """Run a multi-stage DDM valuation from structured inputs.

    What this code does that raw LLM cannot: deterministic arithmetic —
    projects dividends year-by-year at specified growth rates, discounts each
    dividend at the correct time period using CAPM cost of equity, computes a
    Gordon Growth terminal value on the final projected dividend, and sums to
    an equity value per share. Every number is reproducible from the typed
    DDMInputs; the LLM only selects the assumptions.

    Args:
        inputs: DDMInputs with dividend, growth rates, and CAPM parameters.

    Returns:
        DDMResult with all intermediate and final valuation numbers.

    Raises:
        ValueError: If terminal growth rate >= cost of equity (Gordon Growth
            Model perpetuity is undefined).
    """
    # 1. Cost of equity via CAPM
    cost_of_equity = inputs.risk_free_rate + inputs.beta * inputs.equity_risk_premium

    if inputs.terminal_growth_rate >= cost_of_equity:
        raise ValueError(
            f"Terminal growth ({inputs.terminal_growth_rate:.1%}) must be less than "
            f"cost of equity ({cost_of_equity:.1%}). "
            "Gordon Growth Model perpetuity is undefined when tg >= CoE."
        )
    if cost_of_equity - inputs.terminal_growth_rate < MIN_GORDON_SPREAD:
        # Same forward-Gordon floor as calculate_dcf (shared constant): a
        # sub-floor spread puts a 200×+ multiplier on the terminal dividend —
        # a blowup, not a valuation. A low-beta payer can legally produce a
        # CoE within a hair of the 5%-capped tg, so this is reachable.
        raise ValueError(
            f"CoE−terminal growth spread "
            f"{cost_of_equity - inputs.terminal_growth_rate:.2%} is below the "
            f"{MIN_GORDON_SPREAD:.1%} minimum — DDM is not applicable; use "
            "relative valuation instead."
        )

    # A dividend cannot shrink by more than 100%: a growth rate < −1 makes
    # (1 + rate) < 0, driving the projected dividend negative (and sign-flipping
    # below −2) → a nonsensical negative share value. rate == −1 (a permanent
    # suspension → dividend 0, value collapses to ~0) is valid. Symmetric with the
    # tg ≥ cost-of-equity guard above — refuse the undefined region, don't emit a
    # reverse number.
    if any(rate < -1 for rate in inputs.dividend_growth_rates):
        raise ValueError("dividend_growth_rate < −1 implies a negative dividend; DDM is undefined.")

    # 2. Project dividends at specified growth rates
    projected_dividends: list[float] = []
    current_dividend = inputs.dividend_per_share
    for rate in inputs.dividend_growth_rates:
        current_dividend *= 1 + rate
        projected_dividends.append(current_dividend)

    # 3. PV of projected dividends
    pv_dividends = [d / (1 + cost_of_equity) ** (i + 1) for i, d in enumerate(projected_dividends)]
    pv_dividends_total = sum(pv_dividends)

    # 4. Terminal value (Gordon Growth on last projected dividend)
    #
    # Terminal payout normalization: a firm whose growth has slowed to the
    # perpetuity rate no longer needs to retain earnings at its trailing rate.
    # When ``terminal_payout_ratio`` is supplied (seed_ddm_inputs sets it to the
    # payout consistent with terminal growth at the firm's ROE, ≈ 1 − g/ROE), the
    # terminal dividend is stepped up by ``terminal_payout / trailing_payout``.
    # Since EPS and DPS grow together while payout is constant in the explicit
    # window, EPS_n = D_n / trailing_payout, so the normalized terminal dividend
    # is D_n × (1 + tg) × (terminal_payout / trailing_payout). This corrects the
    # naive DDM error of discounting a low trailing payout into perpetuity — the
    # error that values a 28%-payout, 16% ROE bank like JPM at a third of price.
    # When ``terminal_payout_ratio`` is None, the factor is 1.0 (naive Gordon).
    # seed_ddm_inputs supplies it ONLY for balance-sheet financials (banks/insurers,
    # whose low trailing payout is genuine capital-building that matures into dividends);
    # non-financials seed None so their buyback-suppressed payout is NOT recaptured as
    # future dividends (that valued AAPL's dividend stream at $443 > price). See
    # ddm_seed.seed_ddm_inputs terminal_payout_ratio gating.
    n = len(projected_dividends)
    if inputs.terminal_payout_ratio is not None and inputs.payout_ratio > 0:
        terminal_payout_stepup = inputs.terminal_payout_ratio / inputs.payout_ratio
    else:
        terminal_payout_stepup = 1.0
    terminal_dividend = (
        projected_dividends[-1] * (1 + inputs.terminal_growth_rate) * terminal_payout_stepup
    )
    terminal_value = terminal_dividend / (cost_of_equity - inputs.terminal_growth_rate)
    pv_terminal = terminal_value / (1 + cost_of_equity) ** n

    # 5. Equity value per share
    equity_value_per_share = pv_dividends_total + pv_terminal

    return DDMResult(
        cost_of_equity=cost_of_equity,
        projected_dividends=projected_dividends,
        pv_dividends=pv_dividends,
        pv_dividends_total=pv_dividends_total,
        terminal_dividend=terminal_dividend,
        terminal_value=terminal_value,
        pv_terminal=pv_terminal,
        equity_value_per_share=equity_value_per_share,
        inputs=inputs,
    )


def calculate_ddm_sensitivity(
    inputs: DDMInputs,
    coe_range: list[float],
    tg_range: list[float],
) -> DDMSensitivity:
    """Generate sensitivity table: equity value per share for each (CoE, tg) pair.

    Projects dividends once (they don't depend on CoE or TG), then discounts
    at each (CoE, TG) combination. Returns None for cells where tg >= CoE
    (Gordon Growth Model undefined).
    """
    # --- Project dividends once (CoE/TG-independent) ---
    projected_dividends: list[float] = []
    current_dividend = inputs.dividend_per_share
    for rate in inputs.dividend_growth_rates:
        current_dividend *= 1 + rate
        projected_dividends.append(current_dividend)
    n = len(projected_dividends)
    last_dividend = projected_dividends[-1]

    # Same terminal-payout normalization as calculate_ddm — keep the grid
    # consistent with the headline value (see calculate_ddm step 4).
    if inputs.terminal_payout_ratio is not None and inputs.payout_ratio > 0:
        terminal_payout_stepup = inputs.terminal_payout_ratio / inputs.payout_ratio
    else:
        terminal_payout_stepup = 1.0

    # --- Discount at each (CoE, TG) pair ---
    implied_prices: list[list[float | None]] = []
    for coe in coe_range:
        row: list[float | None] = []
        for tg in tg_range:
            # Same refusal set as calculate_ddm's base case: undefined region
            # AND sub-floor Gordon spread — grid cells must not ship blowups
            # the headline refuses.
            if tg >= coe or (coe - tg) < MIN_GORDON_SPREAD:
                row.append(None)
            else:
                pv_divs = sum(d / (1 + coe) ** (i + 1) for i, d in enumerate(projected_dividends))
                tv = last_dividend * (1 + tg) * terminal_payout_stepup / (coe - tg)
                pv_tv = tv / (1 + coe) ** n
                row.append(pv_divs + pv_tv)
        implied_prices.append(row)
    return {
        "coe_values": coe_range,
        "tg_values": tg_range,
        "implied_prices": implied_prices,
    }
