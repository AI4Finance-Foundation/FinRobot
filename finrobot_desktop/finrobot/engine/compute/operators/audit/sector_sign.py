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
   ``_is_balance_sheet_financial`` for the calibrated boundary — only deposit-taking
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


def _is_balance_sheet_financial(industry: str | None) -> bool:
    """True only for issuers whose ENTIRE industry bucket is balance-sheet-funded
    (deposits / float / reserves are operating, no clean EBITDA): deposit-taking
    banks and risk-carrying insurers. Deliberately conservative — even though the EV
    finding is now ``review`` (a caveat, no longer a target-withholding ``blocked_field``),
    a false-positive still wrongly banners a valid EV as meaningless, so keep the boundary
    tight (a false-negative — missing a real bank — is the cheaper error).

    Probe 2026-06-06 calibrated the boundary:
    - ``"bank"`` → all of "Banks - Diversified/Regional" (incl. foreign ADRs
      HSBC/MUFG/ITUB) are deposit-takers. Clean token.
    - ``"insurance"`` BUT NOT ``"broker"`` → "Insurance - Life/Diversified/P&C"
      carry float/reserves; "Insurance - Brokers" (AON/MMC/AJG/BRO/WTW) are
      asset-light fee businesses with a MEANINGFUL EV/EBITDA — must not suppress.
    - "Financial - Capital Markets" is DELIBERATELY NOT suppressed: FMP lumps
      balance-sheet investment banks (GS/MS) with asset-light advisory boutiques
      (EVR/LAZ/PJT/MC/HLI) into one indistinguishable string, so suppressing it
      would false-positive the boutiques. Keep EV for the whole bucket; a finer
      split (needs a balance-sheet-leverage signal) is deferred to Plan 2.
    Excluded by construction (EV meaningful, asset-light): "Financial - Credit
    Services" (Visa/MA), "Asset Management" (BlackRock), "Financial - Data & Stock
    Exchanges" (ICE/CME/NDAQ), all "REIT - *".
    """
    if not industry:
        return False
    low = industry.lower()
    if "bank" in low:
        return True
    if "insurance" in low and "broker" not in low:
        return True
    return False


def audit_sector_sign(fin: FinancialData) -> list[Finding]:
    findings: list[Finding] = []

    industry = fin.market.industry
    if _is_balance_sheet_financial(industry):
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
