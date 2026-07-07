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

from finrobot.engine.data.normalize.contracts import DEGRADED_FX_NORMALIZED
from finrobot.engine.models.financial import FinancialData
from finrobot.engine.models.numeric_claim import Finding

# Probes 2026-06-06 + 2026-06-10: FMP /profile country is ISO-2 ("US"/"TW"/"CN"),
# yfinance .info country is a full name ("United States"/"Taiwan"). Cover both.
_US_COUNTRY_TOKENS = frozenset({"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"})


def audit_foreign_issuer_usd_tags(fin: FinancialData) -> list[Finding]:
    """Foreign issuer whose snapshot shows BOTH currency tags "USD" with no
    FX-normalization trace → ``review``.

    A double-USD foreign snapshot is unverifiable from the tags alone: either
    yfinance mis-tagged a home-currency reporter as USD/USD — then every ratio
    closes on the wrong currency and ``audit_currency_caliber`` is blind
    because the tags agree (the red-team BP case) — or the issuer genuinely
    reports in USD (SHEL/BP/LULU class). Both deserve an analyst's eye, neither
    deserves a withheld target, hence severity ``review`` (banner only).

    Three deliberate suppressions:
    - ``fx_normalized`` in provenance: the canonical FX gate converted a
      reporting≠quote snapshot to single-currency and rewrote the tag — that
      double-USD is constructed, not suspicious.
    - country missing/blank: "unknown" is not "foreign"; never guess.
    - ``is_adr`` not None (True OR False): a CONFIRMED ADR status comes ONLY from
      the FMP /profile ``isAdr`` field (the yfinance path hardcodes None), and
      FMP's ``reportedCurrency`` is empirically reliable (2026-07-06 20-ticker
      live pull, 0 mis-tags). True = a confirmed ADR files in USD legitimately;
      False = a confirmed non-ADR direct lister / foreign private issuer
      (LULU/SHOP/NVS/FERG/RIO/WCN class) that genuinely reports in USD. Either
      way the USD/USD tag is trustworthy, not a mis-tag — no banner. ``is_adr``
      None still fires: the yfinance path leaves it None and its
      ``financialCurrency`` can falsely read USD for a home-currency reporter, so
      the unknown case is exactly where a genuine mis-tag hides — keep the net.
    """
    if fin.reporting_currency != "USD" or fin.quote_currency != "USD":
        return []  # mixed tags are audit_currency_caliber's jurisdiction
    degraded = fin.provenance.degraded if fin.provenance is not None else []
    if DEGRADED_FX_NORMALIZED in degraded:
        return []
    if fin.market.is_adr is not None:
        return []  # confirmed ADR status (True/False) from the reliable FMP profile
    country = (fin.market.country or "").strip()
    if not country or country.upper() in _US_COUNTRY_TOKENS:
        return []
    return [
        Finding(
            field_key="reporting_currency",
            check="foreign_issuer_usd_tags",
            severity="review",
            evidence=(
                f"{fin.ticker}: issuer country is {country!r} but both reporting_currency "
                f"and quote_currency read USD with no FX-normalization trace. Either the "
                f"provider mis-tagged a home-currency reporter as USD (ratios would close "
                f"on the wrong currency) or the issuer genuinely reports in USD — verify "
                f"the filing currency before relying on cross-statement ratios."
            ),
        )
    ]


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
