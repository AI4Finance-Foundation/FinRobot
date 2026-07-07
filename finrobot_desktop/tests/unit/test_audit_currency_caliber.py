"""Family-1 verifier: currency caliber. A derived ratio computed across two
currencies (quote-ccy market_cap over reporting-ccy earnings/EBITDA) is
dimensionally corrupt — the SAP/TSM/TM class of bug, generalized to EV multiples.

This is the REPORT-path defense-in-depth backstop. Two layers now sit in front of
it: the canonical FX gate (class A) makes a foreign ADR single-currency before any
ratio forms, and the FinancialData cross-currency invariant (class B) withholds the
mixed ratios at construction. So a FinancialData built normally can never carry a
mixed ratio — this verifier only catches a snapshot that BYPASSED construction-time
validation (``model_construct`` / a post-hoc currency-tag mutation). The fixtures
below deliberately reproduce that bypass (set the tags AFTER construction, which
skips the invariant) to exercise the backstop's detection logic in isolation.
"""

from __future__ import annotations

from datetime import datetime, timezone

from finrobot.engine.compute.operators.audit.currency_caliber import (
    audit_currency_caliber,
    audit_foreign_issuer_usd_tags,
)
from finrobot.engine.data.normalize.contracts import DEGRADED_FX_NORMALIZED
from finrobot.engine.models.financial import (
    DataProvenance,
    FinancialData,
    IncomeStatement,
    MarketData,
    ValuationMetrics,
)


def _fd(
    *,
    reporting_currency: str = "USD",
    quote_currency: str = "USD",
    pe_ratio: float | None = None,
    enterprise_value: float | None = None,
    ev_ebitda: float | None = None,
    ev_revenue: float | None = None,
    country: str | None = None,
    is_adr: bool | None = None,
    degraded: tuple[str, ...] = (),
) -> FinancialData:
    fd = FinancialData(
        ticker="X",
        timestamp=datetime.now(tz=timezone.utc),
        income=IncomeStatement(revenue=100e9, net_income=20e9),
        market=MarketData(
            market_cap=500e9,
            shares_outstanding=5e9,
            current_price=100.0,
            pe_ratio=pe_ratio,
            country=country,
            is_adr=is_adr,
        ),
        valuation=ValuationMetrics(
            enterprise_value=enterprise_value, ev_ebitda=ev_ebitda, ev_revenue=ev_revenue
        ),
        provenance=DataProvenance(provider="test", degraded=list(degraded)),
        # Construct single-currency so the FinancialData invariant keeps the ratios,
        reporting_currency="USD",
        quote_currency="USD",
    )
    # then set the (possibly mismatched) tags by direct assignment — this skips the
    # construction-time invariant (no validate_assignment), reproducing the bypass
    # path the report-layer backstop exists to catch.
    fd.reporting_currency = reporting_currency
    fd.quote_currency = quote_currency
    return fd


def _checks(findings) -> set[tuple[str, str, str]]:
    return {(f.field_key, f.check, f.severity) for f in findings}


class TestCrossCurrencyRatio:
    def test_adr_mixed_ev_blocked(self):
        f = audit_currency_caliber(
            _fd(reporting_currency="EUR", quote_currency="USD", enterprise_value=2.1e11)
        )
        assert ("enterprise_value", "cross_currency_ratio", "blocked_field") in _checks(f)

    def test_adr_mixed_pe_and_ev_ebitda_blocked(self):
        f = audit_currency_caliber(
            _fd(reporting_currency="TWD", quote_currency="USD", pe_ratio=1.11, ev_ebitda=0.16)
        )
        flagged = {fk for fk, _, _ in _checks(f)}
        assert {"pe_ratio", "ev_ebitda"} <= flagged
        assert all(sev == "blocked_field" for _, _, sev in _checks(f))

    def test_usd_issuer_no_finding(self):
        f = audit_currency_caliber(
            _fd(reporting_currency="USD", quote_currency="USD", pe_ratio=30.0, ev_ebitda=18.0)
        )
        assert f == []

    def test_normalized_adr_no_finding(self):
        # After fx_normalize both tags are USD — the ratio is now currency-clean.
        f = audit_currency_caliber(
            _fd(reporting_currency="USD", quote_currency="USD", enterprise_value=2.1e11)
        )
        assert f == []

    def test_mismatched_currency_but_no_ratios_no_finding(self):
        # Currencies disagree but no derived ratio was computed → nothing to flag.
        f = audit_currency_caliber(_fd(reporting_currency="TWD", quote_currency="USD"))
        assert f == []


class TestForeignIssuerUsdTags:
    """Family-1 country acceptor: a foreign issuer whose snapshot shows BOTH
    tags USD with no FX-normalization trace is unverifiable from tags alone —
    either yfinance mis-tagged a home-currency reporter as USD/USD (the red-team
    BP class: ratios close on the wrong currency and the cross_currency check
    is blind because the tags agree) or it is a genuine USD reporter
    (SHEL/BP/LULU). Severity ``review`` only — banner, target stays.

    Country string evidence (probes 2026-06-06 + 2026-06-10): FMP /profile
    returns ISO-2 ("US"/"TW"/"CN"); yfinance .info returns full names
    ("United States"/"Taiwan"/"United Kingdom"). The US set covers both.
    """

    def test_foreign_iso2_double_usd_review(self):
        f = audit_foreign_issuer_usd_tags(_fd(country="TW"))
        assert _checks(f) == {("reporting_currency", "foreign_issuer_usd_tags", "review")}

    def test_foreign_full_name_double_usd_review(self):
        f = audit_foreign_issuer_usd_tags(_fd(country="United Kingdom"))
        assert _checks(f) == {("reporting_currency", "foreign_issuer_usd_tags", "review")}

    def test_us_issuer_clean(self):
        assert audit_foreign_issuer_usd_tags(_fd(country="US")) == []
        assert audit_foreign_issuer_usd_tags(_fd(country="United States")) == []

    def test_unknown_country_clean(self):
        # Absent country is "unknown", not "foreign" — never guess.
        assert audit_foreign_issuer_usd_tags(_fd(country=None)) == []
        assert audit_foreign_issuer_usd_tags(_fd(country="  ")) == []

    def test_fx_normalized_foreign_clean(self):
        # SAP via the canonical FX gate: was EUR/USD, converted to USD/USD with
        # the fx_normalized provenance marker — single-currency by construction,
        # NOT a suspicious double-USD original.
        f = audit_foreign_issuer_usd_tags(
            _fd(country="Germany", degraded=(DEGRADED_FX_NORMALIZED,))
        )
        assert f == []

    def test_mixed_tags_owned_by_cross_currency_check(self):
        # reporting≠quote belongs to cross_currency_ratio — no double flag here.
        f = audit_foreign_issuer_usd_tags(
            _fd(reporting_currency="TWD", quote_currency="USD", country="TW")
        )
        assert f == []

    def test_no_provenance_object_still_fires(self):
        # provenance=None (model_construct / bypass path) carries no trace —
        # treat as un-normalized, same philosophy as the backstop fixtures.
        fd = _fd(country="TW")
        fd.provenance = None
        f = audit_foreign_issuer_usd_tags(fd)
        assert _checks(f) == {("reporting_currency", "foreign_issuer_usd_tags", "review")}

    def test_confirmed_adr_suppressed(self):
        # FMP /profile isAdr=True (SAP/SHEL/TSM/BABA/NVO/TM/BP): a confirmed ADR
        # files in USD legitimately, so a USD/USD foreign snapshot is expected,
        # not a mis-tag — no banner. (SHEL country=GB, TSM=TW etc. all isAdr=True.)
        assert audit_foreign_issuer_usd_tags(_fd(country="GB", is_adr=True)) == []
        assert audit_foreign_issuer_usd_tags(_fd(country="TW", is_adr=True)) == []

    def test_is_adr_none_still_fires(self):
        # None = "unknown" — the yfinance path hardcodes is_adr=None and its
        # financialCurrency is unreliable (can read USD for a home-currency
        # reporter). This is the genuine mis-tag risk path, so None still fires:
        # a possibly mis-tagged home-currency reporter is never waved through.
        f = audit_foreign_issuer_usd_tags(_fd(country="JP", is_adr=None))
        assert _checks(f) == {("reporting_currency", "foreign_issuer_usd_tags", "review")}

    def test_is_adr_false_suppressed(self):
        # isAdr=False comes ONLY from FMP /profile (yfinance hardcodes is_adr=None),
        # and FMP's reportedCurrency is empirically reliable (2026-07-06 20-ticker
        # live pull, 0 mis-tags). A confirmed non-ADR foreign USD reporter
        # (LULU/SHOP/NVS/FERG/RIO/WCN: direct listings / foreign private issuers
        # genuinely filing in USD) is legit, not a mis-tag — no banner. The
        # mis-tag risk lives on the yfinance path (is_adr=None), which still fires
        # above. Only a CONFIRMED ADR status (True or False) from the reliable FMP
        # profile suppresses; unknown (None) keeps the net.
        assert audit_foreign_issuer_usd_tags(_fd(country="CA", is_adr=False)) == []
        assert audit_foreign_issuer_usd_tags(_fd(country="GB", is_adr=False)) == []
