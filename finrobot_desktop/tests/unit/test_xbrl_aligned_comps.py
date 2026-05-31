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
    ValuationMetrics,
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
        # enterprise_value present ⇔ debt/cash were reported (extract_financial_data
        # invariant). build_xbrl_aligned_company keys the target's debt/cash
        # passthrough off this, so the fixture must populate it like real data.
        valuation=ValuationMetrics(enterprise_value=100.0 + 30.0 - 5.0),
        data_source="test",
        timestamp=datetime.now(tz=timezone.utc),
    )


def test_build_xbrl_aligned_company_overrides_with_ttm_facts() -> None:
    company = build_xbrl_aligned_company(
        ticker="NVDA",
        financial_data=_financial_data(),
        xbrl_data={
            "ttm_revenue": {"concept": "us-gaap:Revenues", "value": 120.0},
            "ttm_net_income": {"concept": "us-gaap:NetIncomeLoss", "value": 18.0},
        },
    )

    assert company.revenue == 120.0
    assert company.net_income == 18.0
    assert company.ev_ebitda is not None


def test_build_xbrl_aligned_company_ignores_latest_annual_when_ttm_absent() -> None:
    """``latest_*`` is the 10-K annual snapshot — typically 1-2 quarters behind
    the FMP TTM baseline carried by ``financial_data``. The builder must NOT
    silently substitute it; falling through to FMP TTM keeps the caliber
    aligned with the rest of the report."""
    company = build_xbrl_aligned_company(
        ticker="NVDA",
        financial_data=_financial_data(),
        # Only annual snapshot, no TTM facts.
        xbrl_data={"latest_revenue": 999.0, "latest_net_income": 999.0},
    )

    # Falls back to FMP TTM (the FinancialData fixture), NOT the stale annuals.
    assert company.revenue == 100.0
    assert company.net_income == 10.0


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

    out = override_company_with_xbrl(
        base,
        {"ttm_revenue": {"concept": "us-gaap:Revenues", "value": 130.0}},
    )

    assert out.revenue == 130.0
    assert out.market_cap == 250.0
    assert out.net_income == 12.0


def test_override_company_with_xbrl_skips_when_only_latest_annual_available() -> None:
    """Reproduces the 2026-05-28 GM peer-row bug: the artifact rendered GM
    revenue $167.97B (stale annual stitched in via XBRL ``latest_revenue``)
    instead of the real TTM $184.62B carried by the FMP baseline. The
    override must skip when only ``latest_*`` is on the wire."""
    base = CompanyFinancials(
        ticker="GM",
        revenue=184_620_000_000.0,  # FMP TTM truth
        ebitda=17_497_000_000.0,
        net_income=2_540_000_000.0,
        market_cap=75_800_000_000.0,
        total_debt=130_000_000_000.0,
        total_cash=25_000_000_000.0,
        gross_margin=0.1,
        operating_margin=0.05,
    )

    out = override_company_with_xbrl(
        base,
        # Only annual snapshot in payload — exactly what the artifact stored.
        {"latest_revenue": 167_970_000_000.0, "latest_net_income": 2_697_000_000.0},
    )

    # FMP TTM values must survive untouched.
    assert out.revenue == 184_620_000_000.0
    assert out.net_income == 2_540_000_000.0


def test_override_company_with_xbrl_keeps_negative_ttm_net_income() -> None:
    """Reproduces the 2026-05-28 Ford peer-row bug: artifact rendered F's
    P/E as 10.6x because the XBRL override slammed FY2024 NI $5.879B over
    the real TTM NI -$6.105B. Once the override honours the negative TTM,
    ``calculate_multiples`` correctly nulls the P/E (P/E undefined for
    loss-making issuers)."""
    base = CompanyFinancials(
        ticker="F",
        revenue=189_860_000_000.0,
        ebitda=8_527_000_000.0,
        net_income=-6_105_000_000.0,  # FMP TTM truth
        market_cap=62_200_000_000.0,
        total_debt=160_000_000_000.0,
        total_cash=22_000_000_000.0,
        gross_margin=0.1,
        operating_margin=-0.01,
    )

    out = override_company_with_xbrl(
        base,
        {
            # XBRL TTM matches FMP — override is a no-op on value but proves
            # the new code path uses ``ttm_*``, not the stale ``latest_*``.
            "ttm_net_income": {
                "concept": "us-gaap:NetIncomeLoss",
                "value": -6_105_000_000.0,
            },
            # Stale annual present but MUST be ignored.
            "latest_net_income": 5_879_000_000.0,
        },
    )

    assert out.net_income == -6_105_000_000.0
    # The bug: pre-fix this read ~10.6x. Post-fix: None (negative NI gates
    # P/E in multiples.calculate_multiples).
    assert out.pe_ratio is None


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
    # Annual net income now lives under the disambiguated :annual key
    assert "us-gaap:NetIncomeLoss" not in snapshot, (
        "bare NetIncomeLoss key must not exist; use :annual/:ttm suffixes"
    )
    assert snapshot["us-gaap:NetIncomeLoss:annual"][0]["value"] == 97.0
