"""Family-1 verifier: currency caliber. A derived ratio computed across two
currencies (quote-ccy market_cap over reporting-ccy earnings/EBITDA) is
dimensionally corrupt — the SAP/TSM/TM class of bug, generalized to EV multiples.

This is a defense-in-depth guard: when the pipeline FX-normalized the snapshot to
USD/USD before forming the ratio, reporting == quote and nothing fires. It only
fires when normalization was SKIPPED and a mixed-currency ratio reached the model.
"""

from __future__ import annotations

from datetime import datetime, timezone

from finrobot.engine.compute.operators.audit.currency_caliber import audit_currency_caliber
from finrobot.engine.models.financial import (
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
) -> FinancialData:
    return FinancialData(
        ticker="X",
        timestamp=datetime.now(tz=timezone.utc),
        income=IncomeStatement(revenue=100e9, net_income=20e9),
        market=MarketData(
            market_cap=500e9, shares_outstanding=5e9, current_price=100.0, pe_ratio=pe_ratio
        ),
        valuation=ValuationMetrics(
            enterprise_value=enterprise_value, ev_ebitda=ev_ebitda, ev_revenue=ev_revenue
        ),
        reporting_currency=reporting_currency,
        quote_currency=quote_currency,
    )


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
