"""Family-5 verifier: sector/sign applicability. Operates on FinancialData (the
snapshot model carrying market.industry + valuation.ev + income.net_income).

External benchmarks (probe 2026-06-06, FMP industry strings):
  banks/insurers/investment banks → EV is a category error (deposits/float/funding
  are operating, no clean EBITDA) → blocked_field; payment networks (Visa) and
  asset managers (BlackRock) are asset-light → EV IS meaningful → no finding.
  Non-positive earnings → P/E not meaningful by economics → review.
"""

from __future__ import annotations

from datetime import datetime, timezone

from finrobot.engine.compute.operators.audit.sector_sign import audit_sector_sign
from finrobot.engine.models.financial import (
    FinancialData,
    IncomeStatement,
    MarketData,
    ValuationMetrics,
)


def _fd(
    *,
    ticker: str = "X",
    industry: str | None = None,
    net_income: float | None = 10e9,
    enterprise_value: float | None = None,
    ev_ebitda: float | None = None,
) -> FinancialData:
    return FinancialData(
        ticker=ticker,
        timestamp=datetime.now(tz=timezone.utc),
        income=IncomeStatement(revenue=100e9, net_income=net_income),
        market=MarketData(
            market_cap=500e9, shares_outstanding=5e9, current_price=100.0, industry=industry
        ),
        valuation=ValuationMetrics(enterprise_value=enterprise_value, ev_ebitda=ev_ebitda),
    )


def _checks(findings) -> set[str]:
    return {f.check for f in findings}


class TestFinancialSectorEvSuppression:
    def test_bank_ev_ebitda_blocked(self):
        f = audit_sector_sign(_fd(ticker="JPM", industry="Banks - Diversified", ev_ebitda=8.0))
        assert "financial_sector_ev_meaningless" in _checks(f)
        evf = next(x for x in f if x.field_key == "ev_ebitda")
        assert evf.severity == "blocked_field"

    def test_insurer_enterprise_value_blocked(self):
        f = audit_sector_sign(
            _fd(ticker="MET", industry="Insurance - Life", enterprise_value=1.2e11)
        )
        assert any(x.field_key == "enterprise_value" and x.severity == "blocked_field" for x in f)

    def test_investment_bank_capital_markets_blocked(self):
        f = audit_sector_sign(
            _fd(ticker="GS", industry="Financial - Capital Markets", ev_ebitda=6.0)
        )
        assert "financial_sector_ev_meaningless" in _checks(f)

    def test_payment_network_ev_kept(self):
        # Visa: "Financial - Credit Services" — asset-light, EV/EBITDA is meaningful.
        f = audit_sector_sign(
            _fd(ticker="V", industry="Financial - Credit Services", ev_ebitda=25.0)
        )
        assert "financial_sector_ev_meaningless" not in _checks(f)

    def test_asset_manager_ev_kept(self):
        f = audit_sector_sign(_fd(ticker="BLK", industry="Asset Management", ev_ebitda=15.0))
        assert "financial_sector_ev_meaningless" not in _checks(f)

    def test_non_financial_ev_kept(self):
        f = audit_sector_sign(_fd(ticker="AAPL", industry="Consumer Electronics", ev_ebitda=22.0))
        assert "financial_sector_ev_meaningless" not in _checks(f)

    def test_missing_industry_ev_kept(self):
        f = audit_sector_sign(_fd(industry=None, ev_ebitda=10.0))
        assert "financial_sector_ev_meaningless" not in _checks(f)

    def test_bank_without_ev_no_finding(self):
        # Nothing to suppress when EV was already withheld upstream.
        f = audit_sector_sign(_fd(ticker="JPM", industry="Banks - Diversified"))
        assert "financial_sector_ev_meaningless" not in _checks(f)


class TestNonPositiveEarnings:
    def test_loss_maker_pe_nm_review(self):
        f = audit_sector_sign(_fd(ticker="MU", net_income=-5.8e9))
        pe = next(x for x in f if x.field_key == "pe_ratio")
        assert pe.check == "non_positive_earnings_pe_nm"
        assert pe.severity == "review"

    def test_zero_earnings_pe_nm(self):
        f = audit_sector_sign(_fd(net_income=0.0))
        assert any(x.check == "non_positive_earnings_pe_nm" for x in f)

    def test_profitable_no_nm_finding(self):
        f = audit_sector_sign(_fd(net_income=10e9))
        assert "non_positive_earnings_pe_nm" not in _checks(f)

    def test_missing_earnings_no_nm_finding(self):
        # None = data missing, NOT economically NM — don't fire the loss-maker rule.
        f = audit_sector_sign(_fd(net_income=None))
        assert "non_positive_earnings_pe_nm" not in _checks(f)
