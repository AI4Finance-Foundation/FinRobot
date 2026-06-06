"""Assembly: audit_company runs every definitional verifier over one snapshot."""

from __future__ import annotations

from datetime import date, datetime, timezone

from finrobot.engine.compute.operators.audit import audit_artifact, audit_company
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
    ttm_ends: list[date] | None = None,
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
        ttm_quarter_ends=ttm_ends or [],
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


def test_collects_ttm_period_finding():
    # A missing quarter (182-day gap) trips the family-4 verifier through audit_company.
    findings = audit_company(
        _fd(
            industry="Software",
            ev_ebitda=18.0,
            pe_ratio=30.0,
            ttm_ends=[date(2026, 3, 31), date(2025, 9, 30), date(2025, 6, 30), date(2025, 3, 31)],
        )
    )
    assert "ttm_quarter_gap" in {f.check for f in findings}


class TestAuditArtifact:
    def test_clean_company_publishable(self):
        a = audit_artifact(_fd(industry="Software", ev_ebitda=18.0, pe_ratio=30.0))
        assert a.artifact_status == "publishable"
        assert a.withhold_valuation is False
        assert a.findings == []

    def test_blocked_field_review_only_and_withholds_valuation(self):
        # Bank EV is a category error (blocked_field) → REVIEW_ONLY + withhold target.
        a = audit_artifact(_fd(industry="Banks - Diversified", ev_ebitda=8.0))
        assert a.artifact_status == "review_only"
        assert a.withhold_valuation is True
        assert any(f.severity == "blocked_field" for f in a.findings)

    def test_review_only_does_not_withhold_valuation(self):
        # Loss-maker P/E NM is review (advisory) — REVIEW_ONLY banner, but the
        # DCF-based target is not auto-nuked (no blocked_field).
        a = audit_artifact(_fd(industry="Software", net_income=-1e9))
        assert a.artifact_status == "review_only"
        assert a.withhold_valuation is False

    def test_ttm_quarter_gap_withholds_valuation(self):
        # A broken TTM (missing quarter) corrupts every ratio → blocked_field →
        # REVIEW_ONLY + withhold the target built on it.
        a = audit_artifact(
            _fd(
                industry="Software",
                ttm_ends=[
                    date(2026, 3, 31),
                    date(2025, 9, 30),
                    date(2025, 6, 30),
                    date(2025, 3, 31),
                ],
            )
        )
        assert a.artifact_status == "review_only"
        assert a.withhold_valuation is True
        assert any(f.check == "ttm_quarter_gap" for f in a.findings)

    def test_incomplete_ttm_review_only_keeps_valuation(self):
        # 3-quarter TTM is incomplete (review), not corrupt — banner, keep target.
        a = audit_artifact(
            _fd(
                industry="Software",
                ttm_ends=[date(2026, 3, 31), date(2025, 12, 31), date(2025, 9, 30)],
            )
        )
        assert a.artifact_status == "review_only"
        assert a.withhold_valuation is False

    def test_no_financial_data_publishable(self):
        a = audit_artifact(None)
        assert a.artifact_status == "publishable"
        assert a.withhold_valuation is False
        assert a.findings == []
