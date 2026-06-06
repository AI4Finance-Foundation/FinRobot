"""Assembly: audit_company runs every definitional verifier over one snapshot."""

from __future__ import annotations

from datetime import datetime, timezone

from finrobot.engine.compute.operators.audit import audit_company
from finrobot.engine.models.financial import (
    FinancialData,
    IncomeStatement,
    MarketData,
    ValuationMetrics,
)


def _fd(
    *,
    industry: str | None = None,
    net_income: float | None = 20e9,
    reporting_currency: str = "USD",
    quote_currency: str = "USD",
    ev_ebitda: float | None = None,
    pe_ratio: float | None = None,
) -> FinancialData:
    return FinancialData(
        ticker="X",
        timestamp=datetime.now(tz=timezone.utc),
        income=IncomeStatement(revenue=100e9, net_income=net_income),
        market=MarketData(
            market_cap=500e9,
            shares_outstanding=5e9,
            current_price=100.0,
            industry=industry,
            pe_ratio=pe_ratio,
        ),
        valuation=ValuationMetrics(ev_ebitda=ev_ebitda),
        reporting_currency=reporting_currency,
        quote_currency=quote_currency,
    )


def test_clean_us_company_no_findings():
    assert audit_company(_fd(industry="Software", ev_ebitda=18.0, pe_ratio=30.0)) == []


def test_collects_findings_from_multiple_verifiers():
    # A loss-making bank ADR trips all three definitional checks at once.
    findings = audit_company(
        _fd(
            industry="Banks - Diversified",
            net_income=-1e9,
            reporting_currency="EUR",
            quote_currency="USD",
            ev_ebitda=5.0,
            pe_ratio=12.0,
        )
    )
    checks = {f.check for f in findings}
    assert "financial_sector_ev_meaningless" in checks  # sector_sign
    assert "non_positive_earnings_pe_nm" in checks  # sector_sign
    assert "cross_currency_ratio" in checks  # currency_caliber
