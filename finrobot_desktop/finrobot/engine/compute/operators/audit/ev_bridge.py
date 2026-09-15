"""Family-3 verifier: enterprise-value bridge completeness.

``calculate_ev`` now includes preferred equity and noncontrolling (minority)
interest, so a REPORTED component is folded into EV — no longer dropped. The
residual gap is a component the provider did NOT report (``None``): the extractor
coerces it to 0, which is right for the overwhelming majority of issuers but
UNVERIFIABLE. If the issuer actually carries preferred / NCI, EV — and every EV
multiple (EV/EBITDA, EV/Revenue) — is understated, and the omission stays INVISIBLE
to the ``market_cap + debt + preferred + NCI − cash`` identity, which still closes
to the dollar.

Flagged at ``review`` (not ``blocked_field``): the assumed-0 is usually correct, so
surface the unverifiable bridge so the analyst can confirm rather than auto-withhold
the whole valuation.
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
        # Reported (0.0 or a value) → already in EV via calculate_ev → nothing to
        # flag. None → provider didn't report it, EV assumed 0 → unverifiable.
        if value is None:
            findings.append(
                Finding(
                    field_key="enterprise_value",
                    check="ev_bridge_unverified",
                    severity="review",
                    evidence=(
                        f"{fin.ticker}: {label} not reported by the provider — EV "
                        f"assumes 0 for it. If the issuer carries {label}, this EV "
                        f"(and EV/EBITDA, EV/Revenue) is understated by that amount."
                    ),
                )
            )
    return findings
