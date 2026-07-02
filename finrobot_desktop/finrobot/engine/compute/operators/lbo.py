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
    # Price the entry EV and the acquisition debt on entry_ebitda when the seed
    # supplied it (a commodity/deep-cyclical's NORMALIZED through-cycle EBITDA),
    # else on ltm_ebitda (every non-cyclical — byte-identical to before). Pricing a
    # cyclical's entry on its cycle-peak LTM while the projection reverts to the
    # normalized margin sets entry debt at a multiple of PEAK EBITDA the projected
    # NORMALIZED EBITDA cannot service, so the schedule blows up and exit equity
    # goes negative purely as a caliber artifact (MU: 5× peak = 10.6× normalized).
    entry_ebitda = inputs.entry_ebitda if inputs.entry_ebitda is not None else inputs.ltm_ebitda
    entry_ev = inputs.entry_ev_ebitda * entry_ebitda
    entry_debt = inputs.leverage_multiple * entry_ebitda
    entry_equity = entry_ev - entry_debt

    schedule, exit_ebitda, _ = _run_schedule(inputs, entry_debt)

    exit_ev = inputs.exit_ev_ebitda * exit_ebitda
    remaining_debt = schedule[-1].ending_debt
    exit_equity = exit_ev - remaining_debt

    # entry_equity <= 0 means entry_debt >= entry_ev: the sponsor would put in
    # NO positive equity — an impossible LBO capital structure, not a trade with
    # an outcome. Returns are UNDEFINED there (None), NOT a total loss. Forcing
    # moic=0/irr=-1 reads as "你血本无归" when exit_equity may even be positive —
    # the opposite signal. Mirror the sensitivity grid, which already None-s
    # these cells, and disclose the口径 via capital_structure_warning.
    #
    # With POSITIVE entry equity, a wipeout (exit_equity <= 0) is a real total
    # loss: moic floors at 0× (never a negative multiple) and _compute_irr emits
    # -1.0 — the two agree.
    moic: float | None
    irr: float | None
    if entry_equity > 0:
        moic = max(exit_equity / entry_equity, 0.0)
        irr = _compute_irr(entry_equity, exit_equity, inputs.holding_period_years)
    else:
        moic = None
        irr = None

    # Self-financing test: an LBO must DELEVERAGE from the target's own levered FCF —
    # the acquisition debt is paid down over the hold. When projected FCF is negative
    # across the hold the revolver funds the shortfall every year and net debt RISES
    # (ending_debt ≥ entry_debt) instead of amortizing; the deal does NOT self-finance,
    # and any positive exit equity is a pure exit-multiple artifact on a debt-financed
    # larger EBITDA base, not operating deleveraging. The test is UNIVERSAL — it keys on
    # the computed schedule, not on the industry or a ticker list — so a non-cyclical
    # capital-hungry name trips it on the same footing as a cyclical one (live-validated:
    # MU memory capex 42% > margin 36% AND DUK regulated-utility rate-base capex 43% both
    # fail at 5× leverage; XOM/AAPL/KO/VZ deleverage cleanly and pass). Undefined (None)
    # for the impossible structure (entry_equity ≤ 0), where returns are already None.
    self_financing: bool | None = (remaining_debt < entry_debt) if entry_equity > 0 else None

    capital_structure_warning = (
        "Simplified sources & uses: entry debt is modeled as new debt of "
        "the leverage multiple × LTM EBITDA. The target's existing balance-sheet "
        "cash (which would reduce sponsor equity) and existing debt (which "
        "would be refinanced) are NOT netted into the equity check, and "
        "transaction/financing fees and a minimum operating-cash requirement "
        "are not modeled. Entry equity and returns may differ from a full "
        "sources-&-uses build."
    )
    if inputs.entry_ebitda is not None and inputs.entry_ebitda != inputs.ltm_ebitda:
        # Cyclical: entry priced on NORMALIZED through-cycle EBITDA, not the current
        # LTM. Disclose both so an analyst never reads the modeled returns as an
        # at-market deal. Branch the direction on the cycle PHASE — a peak issuer
        # (LTM > normalized) is priced DOWN so its ability-to-pay sits below the current
        # market EV; a trough issuer (LTM < normalized) is priced UP from the depressed
        # current LTM toward sustainable earnings. The seed provenance carries the exact
        # market-EV ratio; the operator has no market cap, so it states only the
        # direction — a trough name (XOM) is never mislabeled "cycle-peak".
        if inputs.ltm_ebitda > entry_ebitda:
            phase_clause = (
                "for a cycle-peak issuer this normalized entry EV sits below the current "
                "market enterprise value, so an LBO at today's market price is not feasible"
            )
        else:
            phase_clause = (
                "for a cycle-trough issuer this marks the entry UP from the depressed "
                "current-LTM basis to sustainable through-cycle earnings"
            )
        capital_structure_warning = (
            f"Cyclical entry normalization: the entry EV (${entry_ev / 1e6:.0f}M) and "
            f"acquisition debt are priced on the NORMALIZED through-cycle EBITDA "
            f"(${entry_ebitda / 1e6:.0f}M), not the current LTM EBITDA "
            f"(${inputs.ltm_ebitda / 1e6:.0f}M) — a sponsor underwrites leverage against "
            f"sustainable through-cycle earnings, not the current cycle phase; "
            f"{phase_clause}. " + capital_structure_warning
        )
    if entry_equity <= 0:
        capital_structure_warning = (
            f"Entry equity is non-positive (entry EV ${entry_ev / 1e6:.0f}M − entry debt "
            f"${entry_debt / 1e6:.0f}M = ${entry_equity / 1e6:.0f}M): debt ≥ enterprise "
            f"value, an impossible LBO structure. MOIC / IRR are UNDEFINED (not a total "
            f"loss) — the leverage multiple ({inputs.leverage_multiple:.1f}×) exceeds the entry "
            f"multiple ({inputs.entry_ev_ebitda:.1f}×). " + capital_structure_warning
        )
    if self_financing is False:
        # Lead the warning with the feasibility verdict (prepended last so it sits
        # first): the deal does not deleverage, so the headline MOIC / IRR must not be
        # read as achievable sponsor returns.
        cumulative_fcf = sum(y.fcf for y in schedule)
        capital_structure_warning = (
            f"LBO NOT self-financing as modeled: projected levered free cash flow is "
            f"negative across the {inputs.holding_period_years}-year hold (cumulative "
            f"${cumulative_fcf / 1e6:.0f}M), so the revolver funds the shortfall every year "
            f"and net debt RISES from ${entry_debt / 1e6:.0f}M at entry to "
            f"${remaining_debt / 1e6:.0f}M at exit rather than amortizing. The modeled MOIC / "
            f"IRR are therefore NOT the product of operating deleveraging — they depend "
            f"entirely on the {inputs.exit_ev_ebitda:.1f}× exit multiple applied to a larger, "
            f"debt-financed EBITDA base. A sponsor could not underwrite this structure at "
            f"{inputs.leverage_multiple:.1f}× leverage; the returns are shown for transparency "
            f"but are exit-multiple-dependent, not achievable through the LBO's own cash "
            f"generation. " + capital_structure_warning
        )

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
        self_financing=self_financing,
        irr_formula_warning=(
            "IRR computed via Newton-Raphson NPV=0 solver on the cash flow vector "
            "[-entry equity, 0, ..., 0, exit equity]. Currently models a single "
            "entry and single exit with no interim cash flows. Dividend recaps, "
            "management fee recaps, and partial exits are not yet modeled — "
            "actual IRR may differ if these are material."
        ),
        capital_structure_warning=capital_structure_warning,
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

    Runs the debt schedule once (it depends on leverage_multiple × the entry
    EBITDA anchor, not on entry/exit multiples), then computes MOIC and IRR for each
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
    # Price entry debt/equity on entry_ebitda (cyclical normalized EBITDA) when the
    # seed supplied it, else ltm_ebitda — the SAME anchor _calculate_lbo_core uses,
    # so the grid and the headline never diverge on caliber.
    entry_ebitda = inputs.entry_ebitda if inputs.entry_ebitda is not None else inputs.ltm_ebitda
    entry_debt = inputs.leverage_multiple * entry_ebitda
    schedule, exit_ebitda, _ = _run_schedule(inputs, entry_debt)
    remaining_debt = schedule[-1].ending_debt
    years = inputs.holding_period_years

    # --- Compute MOIC/IRR for each (entry, exit) pair ---
    irr_grid: list[list[float | None]] = []
    moic_grid: list[list[float | None]] = []

    for e_entry in entry_range:
        irr_row: list[float | None] = []
        moic_row: list[float | None] = []
        entry_equity = e_entry * entry_ebitda - entry_debt
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
