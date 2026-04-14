"""LBO (Leveraged Buyout) compute module.

All formulas from Rosenbaum & Pearl, Investment Banking, Chapter 8.
Deterministic arithmetic — no LLM involvement.

Key formula notes:
- FCF = NetIncome + D&A - CapEx - ΔNWC  (standard indirect method)
- IRR = (Exit_Equity / Entry_Equity)^(1/n) - 1  (closed-form, no external solver)
  Valid for single hold-to-exit profile (no interim dividends modeled).
  Returns -1.0 for total loss (exit_equity ≤ 0 or entry_equity ≤ 0).
- MandAmort = Entry Debt × mandatory_amort_pct  (constant each year)
- Cash sweep absorbs excess FCF after mandatory amort, capped at remaining debt.
"""

import logging

from finagent.engine.models.financial import LBOInputs, LBOResult, LBOYear

logger = logging.getLogger(__name__)


def calculate_lbo(inputs: LBOInputs) -> LBOResult:
    """Run full LBO model: build schedule, compute MOIC/IRR, attach sensitivity grid."""
    result = _calculate_lbo_core(inputs)
    sensitivity = calculate_lbo_sensitivity(inputs)
    return result.model_copy(update={"sensitivity": sensitivity})


def _calculate_lbo_core(inputs: LBOInputs) -> LBOResult:
    """Core LBO calculation without sensitivity grid.

    Called by calculate_lbo_sensitivity to avoid infinite recursion.
    """
    entry_ev = inputs.entry_ev_ebitda * inputs.ltm_ebitda
    entry_debt = inputs.leverage_multiple * inputs.ltm_ebitda
    entry_equity = entry_ev - entry_debt

    schedule, exit_ebitda, _ = _run_schedule(inputs, entry_debt)

    exit_ev = inputs.exit_ev_ebitda * exit_ebitda
    remaining_debt = schedule[-1].ending_debt
    exit_equity = exit_ev - remaining_debt

    moic = exit_equity / entry_equity if entry_equity > 0 else 0.0
    irr = _compute_irr(entry_equity, exit_equity, inputs.holding_period_years)

    return LBOResult(
        entry_ev=entry_ev,
        entry_debt=entry_debt,
        entry_equity=entry_equity,
        schedule=schedule,
        exit_ebitda=exit_ebitda,
        exit_ev=exit_ev,
        exit_equity=exit_equity,
        moic=moic,
        irr=irr,
        irr_formula_warning=(
            "IRR uses closed-form (entry_equity → exit_equity)^(1/n) − 1, assuming "
            "no interim cash flows. Dividend recaps, management fee recaps, and "
            "partial exits are ignored — actual IRR may be materially different. "
            "For complex LBO structures, use a full NPV=0 solver."
        ),
    )


def _run_schedule(
    inputs: LBOInputs, entry_debt: float
) -> tuple[list[LBOYear], float, float]:
    """Build year-by-year operating and debt schedule.

    Returns:
        (schedule, exit_ebitda, exit_equity)
        exit_equity is recomputed in calculate_lbo from exit_ev - remaining_debt.
    """
    schedule: list[LBOYear] = []
    prev_revenue = inputs.revenue_base
    current_debt = entry_debt
    mandatory_amort = entry_debt * inputs.mandatory_amort_pct

    for yr in range(1, inputs.holding_period_years + 1):
        revenue = prev_revenue * (1 + inputs.revenue_growth_rate)
        ebitda = revenue * inputs.ebitda_margin
        da = revenue * inputs.da_pct_revenue
        ebit = ebitda - da
        interest_expense = current_debt * inputs.interest_rate
        ebt = ebit - interest_expense
        taxes = max(ebt * inputs.tax_rate, 0.0)
        net_income = ebt - taxes
        capex = revenue * inputs.capex_pct_revenue
        delta_nwc = (revenue - prev_revenue) * inputs.nwc_change_pct_revenue
        fcf = net_income + da - capex - delta_nwc

        # Debt paydown: mandatory + optional sweep
        if inputs.cash_sweep:
            sweep = max(fcf - mandatory_amort, 0.0)
        else:
            sweep = 0.0

        paydown = min(mandatory_amort + sweep, current_debt)
        ending_debt = current_debt - paydown

        schedule.append(
            LBOYear(
                year=yr,
                revenue=revenue,
                ebitda=ebitda,
                da=da,
                ebit=ebit,
                interest_expense=interest_expense,
                ebt=ebt,
                taxes=taxes,
                net_income=net_income,
                capex=capex,
                delta_nwc=delta_nwc,
                fcf=fcf,
                mandatory_amort=mandatory_amort,
                cash_sweep_amount=sweep,
                total_debt_paydown=paydown,
                ending_debt=ending_debt,
            )
        )
        prev_revenue = revenue
        current_debt = ending_debt

    exit_ebitda = schedule[-1].ebitda
    exit_ev = inputs.exit_ev_ebitda * exit_ebitda
    exit_equity = exit_ev - current_debt
    return schedule, exit_ebitda, exit_equity


def _compute_irr(entry_equity: float, exit_equity: float, years: int) -> float:
    """Closed-form IRR for a single-investment, single-exit profile.

    IRR = (exit_equity / entry_equity)^(1/n) - 1

    LIMITATION: This formula assumes a single cash outflow at entry and a single
    cash inflow at exit. It does NOT account for interim cash flows such as:
    - Management fee recapitalizations
    - Dividend recaps
    - Partial exits or follow-on investments

    For LBOs with interim distributions, a full NPV=0 solver (e.g. Newton-Raphson
    on the cash flow vector) is required. This simplification overstates IRR when
    significant interim cash flows exist.

    Returns -1.0 (total loss) if:
    - entry_equity <= 0 (invalid)
    - exit_equity <= 0 (equity wiped out)
    """
    if entry_equity <= 0 or exit_equity <= 0:
        return -1.0
    return (exit_equity / entry_equity) ** (1.0 / years) - 1.0


def calculate_lbo_sensitivity(
    inputs: LBOInputs,
    entry_range: list[float] | None = None,
    exit_range: list[float] | None = None,
) -> dict[str, list]:
    """Build IRR and MOIC sensitivity grids vs entry/exit EV/EBITDA multiples.

    Grid axes:
    - Rows: entry EV/EBITDA multiples (entry_range)
    - Cols: exit EV/EBITDA multiples (exit_range)

    Returns dict with keys:
        entry_multiples, exit_multiples, irr_grid, moic_grid
    """
    if entry_range is None:
        base_entry = inputs.entry_ev_ebitda
        entry_range = [
            round(base_entry - 1.5 + i * 0.5, 2) for i in range(7)
        ]
        entry_range = [e for e in entry_range if e > 0]

    if exit_range is None:
        base_exit = inputs.exit_ev_ebitda
        exit_range = [
            round(base_exit - 2.0 + i * 0.5, 2) for i in range(9)
        ]
        exit_range = [e for e in exit_range if e > 0]

    irr_grid: list[list[float | None]] = []
    moic_grid: list[list[float | None]] = []

    for e_entry in entry_range:
        irr_row: list[float | None] = []
        moic_row: list[float | None] = []
        for e_exit in exit_range:
            try:
                override = inputs.model_copy(
                    update={"entry_ev_ebitda": e_entry, "exit_ev_ebitda": e_exit}
                )
                r = _calculate_lbo_core(override)
                irr_row.append(round(r.irr, 4))
                moic_row.append(round(r.moic, 2))
            except (ValueError, ArithmeticError, ZeroDivisionError):
                irr_row.append(None)
                moic_row.append(None)
        irr_grid.append(irr_row)
        moic_grid.append(moic_row)

    return {
        "entry_multiples": entry_range,
        "exit_multiples": exit_range,
        "irr_grid": irr_grid,
        "moic_grid": moic_grid,
    }
