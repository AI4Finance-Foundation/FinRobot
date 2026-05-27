from __future__ import annotations

from datetime import datetime, timezone

from finrobot.engine.compute.xbrl_aligned_comps import (
    build_xbrl_aligned_company,
    override_company_with_xbrl,
    xbrl_concept_snapshot,
)
from finrobot.engine.models.financial import (
    BalanceSheet,
    CompanyFinancials,
    FinancialData,
    IncomeStatement,
    MarketData,
)


def _financial_data() -> FinancialData:
    return FinancialData(
        ticker="NVDA",
        income=IncomeStatement(
            revenue=100.0,
            ebitda=20.0,
            net_income=10.0,
            gross_margin=0.6,
            operating_margin=0.3,
        ),
        balance=BalanceSheet(total_debt=30.0, total_cash=5.0),
        market=MarketData(current_price=10.0, shares_outstanding=10.0, market_cap=100.0),
        data_source="test",
        timestamp=datetime.now(tz=timezone.utc),
    )


def test_build_xbrl_aligned_company_overrides_core_line_items() -> None:
    company = build_xbrl_aligned_company(
        ticker="NVDA",
        financial_data=_financial_data(),
        xbrl_data={"latest_revenue": 120.0, "latest_net_income": 18.0},
    )

    assert company.revenue == 120.0
    assert company.net_income == 18.0
    assert company.ev_ebitda is not None


def test_override_company_with_xbrl_preserves_market_fields() -> None:
    base = CompanyFinancials(
        ticker="MSFT",
        revenue=100.0,
        ebitda=25.0,
        net_income=12.0,
        market_cap=250.0,
        total_debt=20.0,
        total_cash=10.0,
        gross_margin=0.7,
        operating_margin=0.4,
    )

    out = override_company_with_xbrl(base, {"latest_revenue": 130.0})

    assert out.revenue == 130.0
    assert out.market_cap == 250.0
    assert out.net_income == 12.0


def test_xbrl_concept_snapshot_groups_ttm_and_latest_facts() -> None:
    snapshot = xbrl_concept_snapshot(
        {
            "ttm_revenue": {
                "concept": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                "value": 451.0,
            },
            "latest_net_income": 97.0,
        }
    )

    assert "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax" in snapshot
    assert snapshot["us-gaap:NetIncomeLoss"][0]["value"] == 97.0
