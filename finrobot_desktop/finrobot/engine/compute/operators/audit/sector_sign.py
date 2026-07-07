"""Family-5 verifier: sector & sign applicability.

Two definitional defects the accounting-identity checks are blind to:

1. **EV is a category error for balance-sheet-funded financials.** ``calculate_ev``
   / ``calculate_multiples`` have zero sector awareness, so they happily ship an
   EV/EBITDA for a bank — where deposits/wholesale funding sit in "debt" but are
   operating raw material, not capital structure, and there is no clean
   above-the-line EBITDA (interest IS the business). The identity
   ``EV = market_cap + debt − cash`` closes to the dollar, so the deterministic
   leg LAUNDERS a meaningless number. Banks / insurers / investment banks must be
   valued on P/B, P/TBV, ROTCE, DDM.

   Flagged at ``review`` (a caveated banner), NOT ``blocked_field`` (which withholds the
   price target). The bank's PUBLISHED valuation never consumes EV — aggregate_valuation
   suppresses the cash-flow methods (DCF / EV-EBITDA / P-FCF) for a financial-sector
   issuer and the headline anchors on DDM / P-B — so an EV that nothing builds on is an
   EXPECTED structural fact, exactly like the loss-maker's NM P/E below (also ``review``),
   not a corrupt number that should withhold an unrelated target. Real dimensional
   corruption — mixed-currency EV (currency_caliber), TTM-period defects (ttm_period) —
   still emits ``blocked_field`` from the other verifiers and still withholds, so the
   withhold mechanism is not dead code.

   Classifier (probe 2026-06-06): FMP labels every financial ``sector="Financial
   Services"`` — no discriminating power; the INDUSTRY string drives the call. See
   ``is_balance_sheet_financial`` (now shared in primitives/industry, the single
   authority also used by the valuation aggregator) for the calibrated boundary — only deposit-taking
   banks and risk-carrying (non-broker) insurers are suppressed; payment networks,
   asset managers, exchanges, advisory boutiques and insurance brokers keep EV.

2. **Non-positive earnings make P/E NM by economics**, which is distinct from NM
   by missing data. ``multiples.calculate_multiples`` computes P/E only when
   ``net_income > 0`` and otherwise leaves None — identical to a peer that simply
   lacks the field. A peer P/E median that silently omits a loss-maker is
   upward-biased with no warning. Flag the loss-maker explicitly so the verdict is
   "earnings negative, lean on EV/Revenue / P/B / DCF", not a silent drop.
"""

from __future__ import annotations

from finrobot.engine.models.financial import FinancialData
from finrobot.engine.models.numeric_claim import Finding
from finrobot.engine.primitives.industry import is_balance_sheet_financial


def audit_sector_sign(fin: FinancialData) -> list[Finding]:
    findings: list[Finding] = []

    industry = fin.market.industry
    if is_balance_sheet_financial(industry):
        for field_key, value in (
            ("enterprise_value", fin.valuation.enterprise_value),
            ("ev_ebitda", fin.valuation.ev_ebitda),
        ):
            if value is not None:
                findings.append(
                    Finding(
                        field_key=field_key,
                        check="financial_sector_ev_meaningless",
                        severity="review",
                        evidence=(
                            f"{fin.ticker} industry={industry!r}: deposits/float/funding are "
                            f"operating, not capital structure, and there is no clean above-the-line "
                            f"EBITDA — {field_key}={value} is a category error. Value on "
                            f"P/B, P/TBV, ROTCE, DDM."
                        ),
                    )
                )

    # Net income ABOVE operating income is arithmetically impossible for a
    # taxpaying operator unless non-operating items (unrealized investment
    # gains, one-off disposals, equity-method income) inflate the bottom line —
    # and every headline P/E built on that net income silently understates the
    # operating multiple. GOOGL 2026-07: $37.7B of unrealized securities gains
    # pushed net margin (37.9%) above operating margin (32.7%), the report
    # narrated "cheap vs peers" off headline P/E 27.8x while its own core P/E
    # said 39.1x (external audit C1). Disclose at ``review`` — a legitimate,
    # explainable state, but one the reader must see next to the P/E. The 2%
    # margin band absorbs rounding and small recurring interest income.
    net_income_flag = fin.income.net_income
    operating_income = fin.income.operating_income
    revenue = fin.income.revenue
    if (
        net_income_flag is not None
        and operating_income is not None
        and revenue > 0
        and net_income_flag > 0
        and (net_income_flag - operating_income) / revenue > 0.02
    ):
        findings.append(
            Finding(
                field_key="pe_ratio",
                check="net_income_exceeds_operating_income",
                severity="review",
                evidence=(
                    f"{fin.ticker} net income ({net_income_flag:,.0f}) exceeds operating "
                    f"income ({operating_income:,.0f}) — non-operating items (investment "
                    f"gains, disposals, equity-method income) inflate headline earnings, so "
                    f"the headline P/E understates the operating multiple. Judge valuation "
                    f"on the core/NOPAT-based P/E."
                ),
            )
        )

    net_income = fin.income.net_income
    if net_income is not None and net_income <= 0:
        findings.append(
            Finding(
                field_key="pe_ratio",
                check="non_positive_earnings_pe_nm",
                severity="review",
                evidence=(
                    f"{fin.ticker} net_income={net_income} ≤ 0: P/E is not meaningful by economics "
                    f"(loss-maker / cyclical trough). Lean on EV/Revenue, P/B, or DCF; a peer P/E "
                    f"median that omits this name is upward-biased."
                ),
            )
        )

    return findings
