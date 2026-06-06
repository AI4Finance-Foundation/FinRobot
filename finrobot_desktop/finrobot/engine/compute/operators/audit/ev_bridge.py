"""Family-3 verifier: enterprise-value bridge completeness.

The textbook ``EV = market_cap + total_debt − cash`` OMITS preferred equity and
noncontrolling (minority) interest. An issuer carrying either has its EV — and
every EV multiple (EV/EBITDA, EV/Revenue) — understated, and the omission is
INVISIBLE to the deterministic ``market_cap + debt − cash`` identity, which still
closes to the dollar. So the identity check radiates false confidence exactly
where the bridge is incomplete.

Flagged at ``review`` (not ``blocked_field``): the EV is incomplete, not a category
error or dimensionally corrupt — surface it so the analyst knows the multiple is
understated, but don't auto-withhold the whole valuation (the omission may be
immaterial). The full fix (adding preferred + NCI to ``calculate_ev``) is a
separate change to the EV formula; this verifier surfaces the gap meanwhile.
"""

from __future__ import annotations

from finrobot.engine.models.financial import FinancialData
from finrobot.engine.models.numeric_claim import Finding


def audit_ev_bridge(fin: FinancialData) -> list[Finding]:
    # No EV was computed (provider lacked debt/cash) → there is no EV to call
    # incomplete; the missing-net-debt case is its own existing warning.
    if fin.valuation.enterprise_value is None:
        return []

    findings: list[Finding] = []
    for value, label in (
        (fin.balance.preferred_stock, "preferred stock"),
        (fin.balance.noncontrolling_interest, "noncontrolling interest"),
    ):
        if value is not None and value > 0:
            findings.append(
                Finding(
                    field_key="enterprise_value",
                    check="ev_bridge_incomplete",
                    severity="review",
                    evidence=(
                        f"{fin.ticker}: EV omits {label} ({value:,.0f}). Standard EV = "
                        f"market_cap + debt + preferred + NCI − cash; this EV (and EV/EBITDA, "
                        f"EV/Revenue) is understated by that amount."
                    ),
                )
            )
    return findings
