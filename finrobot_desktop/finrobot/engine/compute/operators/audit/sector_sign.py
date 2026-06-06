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

   Classifier (probe 2026-06-06): FMP labels every financial ``sector="Financial
   Services"`` — no discriminating power. The INDUSTRY string distinguishes:
   ``Banks - Diversified`` (JPM), ``Insurance - Life`` (MET), ``Financial -
   Capital Markets`` (GS) → suppress; ``Financial - Credit Services`` (Visa) and
   ``Asset Management`` (BlackRock) are asset-light → EV IS meaningful, keep.

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

# Industry tokens whose issuers are balance-sheet-funded financials: deposits /
# float / wholesale funding are operating, and there is no clean EBITDA. Token
# match on the FMP industry string naturally excludes "Credit Services" (payments)
# and "Asset Management" (fee-based), which keep a meaningful EV.
_EV_MEANINGLESS_INDUSTRY_TOKENS = ("bank", "insurance", "capital markets")


def _is_balance_sheet_financial(industry: str | None) -> bool:
    if not industry:
        return False
    low = industry.lower()
    return any(token in low for token in _EV_MEANINGLESS_INDUSTRY_TOKENS)


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
                        severity="blocked_field",
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
