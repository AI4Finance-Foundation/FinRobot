"""Family-1 verifier: currency caliber of derived ratios.

``market_cap`` (and price-derived fields) are in the QUOTE currency; income- and
balance-sheet items are in the REPORTING currency. For a foreign-listed ADR they
disagree (TSM USD/TWD, SAP USD/EUR), so any ratio that divides a quote-currency
numerator by a reporting-currency denominator — P/E, EV, EV/EBITDA, EV/Revenue —
is dimensionally corrupt (the SAP 29x / TSM 0.16x class of bug).

The canonical pipeline FX-normalizes the snapshot to USD/USD *before* these ratios
are formed (``fx_normalize.normalize_financialdata_to_usd``), after which both tags
are USD and nothing here fires. This verifier is the defense-in-depth backstop:
it fires only when normalization was skipped and a mixed-currency ratio survived
into the snapshot — exactly the silent defect the deterministic sanity bounds miss
(a sub-1x or plausible-looking multiple sits inside the band).
"""

from __future__ import annotations

from finrobot.engine.models.financial import FinancialData
from finrobot.engine.models.numeric_claim import Finding


def audit_currency_caliber(fin: FinancialData) -> list[Finding]:
    if fin.reporting_currency == fin.quote_currency:
        return []

    findings: list[Finding] = []
    # Ratios whose numerator is quote-currency (market_cap / EV) and denominator is
    # reporting-currency (earnings / EBITDA / revenue). EV itself mixes a
    # quote-currency market_cap with reporting-currency net debt.
    for field_key, value in (
        ("pe_ratio", fin.market.pe_ratio),
        ("enterprise_value", fin.valuation.enterprise_value),
        ("ev_ebitda", fin.valuation.ev_ebitda),
        ("ev_revenue", fin.valuation.ev_revenue),
    ):
        if value is not None:
            findings.append(
                Finding(
                    field_key=field_key,
                    check="cross_currency_ratio",
                    severity="blocked_field",
                    evidence=(
                        f"{fin.ticker}: {field_key}={value} formed with "
                        f"reporting_currency={fin.reporting_currency} ≠ "
                        f"quote_currency={fin.quote_currency} — a quote-currency numerator over a "
                        f"reporting-currency denominator is dimensionally mixed. FX-normalize to a "
                        f"single currency before forming the ratio."
                    ),
                )
            )
    return findings
