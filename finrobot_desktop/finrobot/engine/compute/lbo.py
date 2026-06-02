"""LBO (Leveraged Buyout) compute module.

All formulas from Rosenbaum & Pearl, Investment Banking, Chapter 8.
Deterministic arithmetic — no LLM involvement.

Key formula notes:
- FCF = NetIncome + D&A - CapEx - ΔNWC  (standard indirect method)
- IRR solved via Newton-Raphson on NPV=0 (_solve_irr); with no interim cash
  flows it degenerates to the closed form (Exit_Equity / Entry_Equity)^(1/n) - 1.
  Valid for single hold-to-exit profile (no interim dividends modeled).
  Returns -1.0 for total loss (exit_equity ≤ 0 or entry_equity ≤ 0).
- MandAmort = Entry Debt × mandatory_amort_pct  (constant each year)
- Cash sweep absorbs excess FCF after mandatory amort, capped at remaining debt.
"""

import logging
from typing import Any

from finrobot.engine.models.financial import LBOInputs, LBOResult, LBOYear

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

    # Floor at 0×: equity can be wiped out (total loss) but never returns a
    # negative multiple — a negative MOIC would contradict the IRR=-1.0 total-loss
    # signal _compute_irr emits for the same exit_equity<=0 case.
    moic = max(exit_equity / entry_equity, 0.0) if entry_equity > 0 else 0.0
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
            "IRR computed via Newton-Raphson NPV=0 solver on the cash flow vector "
            "[-entry_equity, 0, ..., 0, exit_equity]. Currently models a single "
            "entry and single exit with no interim cash flows. Dividend recaps, "
            "management fee recaps, and partial exits are not yet modeled — "
            "actual IRR may differ if these are material."
        ),
        capital_structure_warning=(
            "Simplified sources & uses: entry debt is modeled as new debt of "
            "leverage_multiple × LTM EBITDA. The target's existing balance-sheet "
            "cash (which would reduce sponsor equity) and existing debt (which "
            "would be refinanced) are NOT netted into the equity check, and "
            "transaction/financing fees and a minimum operating-cash requirement "
            "are not modeled. Entry equity and returns may differ from a full "
            "sources-&-uses build."
        ),
    )


def _run_schedule(inputs: LBOInputs, entry_debt: float) -> tuple[list[LBOYear], float, float]:
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

        # Debt-service waterfall. fcf is the levered cash available for principal.
        # Mandatory amortization is contractual; if fcf cannot cover it, the
        # shortfall is funded by a revolver draw (debt rises) rather than paid
        # down with cash that does not exist. Optional cash sweep applies only the
        # excess cash above mandatory amort. Without this, a cash-burn year would
        # understate leverage and inflate exit equity / IRR.
        mandatory = min(mandatory_amort, current_debt)
        if inputs.cash_sweep:
            sweep = max(fcf - mandatory, 0.0)
        else:
            sweep = 0.0
        sweep = min(sweep, current_debt - mandatory)
        term_paydown = mandatory + sweep
        revolver_draw = max(mandatory - fcf, 0.0)
        ending_debt = current_debt - term_paydown + revolver_draw

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
                mandatory_amort=mandatory,
                cash_sweep_amount=sweep,
                total_debt_paydown=term_paydown,
                revolver_draw=revolver_draw,
                ending_debt=ending_debt,
            )
        )
        prev_revenue = revenue
        current_debt = ending_debt

    exit_ebitda = schedule[-1].ebitda
    exit_ev = inputs.exit_ev_ebitda * exit_ebitda
    exit_equity = exit_ev - current_debt
    return schedule, exit_ebitda, exit_equity


def _compute_irr(
    entry_equity: float,
    exit_equity: float,
    years: int,
    interim_flows: list[float] | None = None,
) -> float:
    """Compute IRR via Newton-Raphson on the cash flow NPV polynomial.

    Builds the cash flow vector: [-entry_equity, cf_1, cf_2, ..., cf_n + exit_equity]
    where cf_i are interim cash flows (default 0). Then solves NPV(r) = 0 using
    Newton-Raphson iteration.

    For the simple case (no interim flows), this is equivalent to the closed-form
    (exit/entry)^(1/n) - 1, but the solver generalizes to dividend recaps,
    partial exits, and management fee recapitalizations.

    Returns -1.0 (total loss) if:
    - entry_equity <= 0 (invalid)
    - exit_equity <= 0 (equity wiped out)
    - Solver fails to converge (degenerate cash flows)

    Reference: Rosenbaum & Pearl, "Investment Banking" 3rd Ed., Chapter 8.
    Newton-Raphson convergence: typically 5-10 iterations for LBO cash flows.
    """
    if entry_equity <= 0 or exit_equity <= 0:
        return -1.0

    # Build cash flow vector
    flows = [0.0] * (years + 1)
    flows[0] = -entry_equity
    if interim_flows:
        for i, cf in enumerate(interim_flows[:years]):
            flows[i + 1] += cf
    flows[years] += exit_equity

    return _solve_irr(flows)


def _solve_irr(
    cash_flows: list[float],
    guess: float = 0.10,
    max_iter: int = 100,
) -> float:
    """Newton-Raphson IRR solver for an arbitrary cash flow vector.

    Solves: NPV(r) = Σ cf_t / (1+r)^t = 0

    The derivative: NPV'(r) = Σ -t * cf_t / (1+r)^(t+1)

    Convergence uses a scale-relative tolerance: NPV is considered zero when
    it is < 1e-8 × max(|cf|). This handles both small (unit) and large
    (billion-dollar) cash flows without precision issues.

    Args:
        cash_flows: Cash flow vector [cf_0, cf_1, ..., cf_n]. cf_0 is typically negative.
        guess: Initial IRR guess (default 10%).
        max_iter: Maximum iterations before giving up.

    Returns:
        IRR as a decimal. Returns -1.0 if solver fails to converge.
    """
    # Scale-relative tolerance: NPV < 1e-8 × largest cash flow
    scale = max(abs(cf) for cf in cash_flows) if cash_flows else 1.0
    tol = scale * 1e-8

    r = guess
    for _ in range(max_iter):
        npv = 0.0
        dnpv = 0.0
        for t, cf in enumerate(cash_flows):
            denom = (1 + r) ** t
            npv += cf / denom
            if t > 0:
                dnpv -= t * cf / ((1 + r) ** (t + 1))

        if abs(npv) < tol:
            return r

        if abs(dnpv) < 1e-14:
            return -1.0

        r_new = r - npv / dnpv

        # Guard against divergence: if step would push r below -0.999
        # (which makes discount factors explode), clamp it
        if r_new <= -0.999:
            r_new = -0.5

        r = r_new

    return -1.0


def calculate_lbo_sensitivity(
    inputs: LBOInputs,
    entry_range: list[float] | None = None,
    exit_range: list[float] | None = None,
) -> dict[str, Any]:
    """Build IRR and MOIC sensitivity grids vs entry/exit EV/EBITDA multiples.

    Runs the debt schedule once (it depends on leverage_multiple × ltm_ebitda,
    not on entry/exit multiples), then computes MOIC and IRR for each
    (entry, exit) pair from the schedule's exit EBITDA and remaining debt.

    Grid axes:
    - Rows: entry EV/EBITDA multiples (entry_range)
    - Cols: exit EV/EBITDA multiples (exit_range)

    Returns dict with keys:
        entry_multiples, exit_multiples, irr_grid, moic_grid
    """
    if entry_range is None:
        base_entry = inputs.entry_ev_ebitda
        entry_range = [round(base_entry - 1.5 + i * 0.5, 2) for i in range(7)]
        entry_range = [e for e in entry_range if e > 0]

    if exit_range is None:
        base_exit = inputs.exit_ev_ebitda
        exit_range = [round(base_exit - 2.0 + i * 0.5, 2) for i in range(9)]
        exit_range = [e for e in exit_range if e > 0]

    # --- Run schedule once (entry_debt is fixed regardless of entry multiple) ---
    entry_debt = inputs.leverage_multiple * inputs.ltm_ebitda
    schedule, exit_ebitda, _ = _run_schedule(inputs, entry_debt)
    remaining_debt = schedule[-1].ending_debt
    years = inputs.holding_period_years

    # --- Compute MOIC/IRR for each (entry, exit) pair ---
    irr_grid: list[list[float | None]] = []
    moic_grid: list[list[float | None]] = []

    for e_entry in entry_range:
        irr_row: list[float | None] = []
        moic_row: list[float | None] = []
        entry_equity = e_entry * inputs.ltm_ebitda - entry_debt
        for e_exit in exit_range:
            if entry_equity <= 0:
                irr_row.append(None)
                moic_row.append(None)
                continue
            exit_ev = e_exit * exit_ebitda
            exit_equity = exit_ev - remaining_debt
            # Floor at 0× (see headline path): wiped-out equity is 0×, never a
            # negative multiple, to stay consistent with the IRR=-1.0 cell.
            moic = max(exit_equity / entry_equity, 0.0) if entry_equity > 0 else 0.0
            irr = _compute_irr(entry_equity, exit_equity, years)
            irr_row.append(round(irr, 4))
            moic_row.append(round(moic, 2))
        irr_grid.append(irr_row)
        moic_grid.append(moic_row)

    return {
        "entry_multiples": entry_range,
        "exit_multiples": exit_range,
        "irr_grid": irr_grid,
        "moic_grid": moic_grid,
    }
