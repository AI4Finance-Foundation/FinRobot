from __future__ import annotations

from datetime import datetime, timezone

import pytest

from finrobot.engine.compute.operators.xbrl_aligned_comps import (
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


async def test_build_xbrl_aligned_company_adopts_xbrl_when_it_agrees_with_fmp() -> None:
    """XBRL TTM within tolerance of the FMP base is adopted as the more
    authoritative SEC figure (ADR-0008). FMP base here is 100 / 10."""
    company = await build_xbrl_aligned_company(
        ticker="NVDA",
        financial_data=_financial_data(),
        xbrl_data={
            # +10% and +9% vs FMP — inside _TTM_DIVERGENCE_TOLERANCE (35%).
            "ttm_revenue": {"concept": "us-gaap:Revenues", "value": 110.0},
            "ttm_net_income": {"concept": "us-gaap:NetIncomeLoss", "value": 10.9},
        },
    )

    assert company.revenue == 110.0
    assert company.net_income == 10.9
    assert company.ttm_divergence_note is None
    assert company.ev_ebitda is not None


async def test_build_xbrl_aligned_company_keeps_fmp_when_xbrl_diverges() -> None:
    """The NVDA bug in miniature: a degenerate XBRL TTM ($10.918B) that
    diverges materially from the FMP TTM base ($253.5B) must NOT override —
    keep FMP and flag [待核] (ADR-0008). This is the compute-layer guard that
    backstops the provider concept-selection fix."""
    fd = _financial_data()
    fd.income.revenue = 253_491_000_000.0  # FMP TTM truth
    fd.income.net_income = 159_613_000_000.0

    company = await build_xbrl_aligned_company(
        ticker="NVDA",
        financial_data=fd,
        xbrl_data={
            # Degenerate frozen-concept value — what edgartools' first-match getter
            # returned before the provider fix.
            "ttm_revenue": {
                "concept": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                "value": 10_918_000_000.0,
            },
        },
    )

    assert company.revenue == 253_491_000_000.0  # kept FMP, not the $10.918B
    assert company.ttm_divergence_note is not None
    assert "[待核]" in company.ttm_divergence_note
    assert "revenue" in company.ttm_divergence_note


async def test_build_xbrl_aligned_company_ignores_latest_annual_when_ttm_absent() -> None:
    """``latest_*`` is the 10-K annual snapshot — typically 1-2 quarters behind
    the FMP TTM baseline carried by ``financial_data``. The builder must NOT
    silently substitute it; falling through to FMP TTM keeps the caliber
    aligned with the rest of the report."""
    company = await build_xbrl_aligned_company(
        ticker="NVDA",
        financial_data=_financial_data(),
        # Only annual snapshot, no TTM facts.
        xbrl_data={"latest_revenue": 999.0, "latest_net_income": 999.0},
    )

    # Falls back to FMP TTM (the FinancialData fixture), NOT the stale annuals.
    assert company.revenue == 100.0
    assert company.net_income == 10.0


async def test_build_xbrl_aligned_company_normalizes_foreign_target(monkeypatch) -> None:
    """A foreign-listed target (TSM shape: TWD financials, USD market_cap) must
    be FX-normalized to USD BEFORE multiples — symmetric with the peer path
    (BUG-018). Pre-fix the target built USD/USD by default and core_pe collapsed
    like the un-normalized 0.158x EV/EBITDA bug; the target rendered a mixed-
    currency NOPAT price target up to ~32x off (TWD/USD)."""

    async def _fake_fx(ccy: str, *, fmp_api_key: str | None = None) -> float:
        assert ccy == "TWD"
        return 1.0 / 32.0

    monkeypatch.setattr("finrobot.engine.data.providers.fx.fetch_fx_rate_to_usd", _fake_fx)

    fd = _financial_data()
    fd.reporting_currency = "TWD"
    fd.quote_currency = "USD"
    fd.income.revenue = 3_200.0  # TWD
    fd.income.net_income = 320.0  # TWD
    fd.income.income_tax_expense = 64.0  # TWD
    fd.market.market_cap = 100.0  # already USD
    # Foreign target: drop the cached USD/TWD-mixed EV so debt/cash recompute.
    fd.balance.total_debt = 320.0  # TWD
    fd.balance.total_cash = 160.0  # TWD

    company = await build_xbrl_aligned_company(
        ticker="TSM",
        financial_data=fd,
        xbrl_data=None,
    )

    # IS/BS items converted to USD (÷32); market_cap (USD) untouched.
    assert company.revenue == pytest.approx(100.0)  # 3200 TWD × 1/32
    assert company.net_income == pytest.approx(10.0)  # 320 TWD × 1/32
    assert company.income_tax_expense == pytest.approx(2.0)  # 64 TWD × 1/32
    assert company.market_cap == 100.0
    assert company.reporting_currency == "USD"
    assert company.quote_currency == "USD"


async def test_build_xbrl_aligned_company_usd_target_no_fx_call(monkeypatch) -> None:
    """A US target (USD/USD, the common case) must hit the no-op FX fast path —
    no FX lookup, values unchanged."""

    async def _boom(ccy: str, *, fmp_api_key: str | None = None) -> float:
        raise AssertionError("US target must not trigger an FX lookup")

    monkeypatch.setattr("finrobot.engine.data.providers.fx.fetch_fx_rate_to_usd", _boom)

    company = await build_xbrl_aligned_company(
        ticker="NVDA",
        financial_data=_financial_data(),
        xbrl_data=None,
    )
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


def test_override_company_with_xbrl_flags_divergent_peer() -> None:
    """A peer whose XBRL TTM diverges materially from its FMP base keeps FMP and
    carries a [待核] note (ADR-0008) — a degenerate XBRL can't poison a peer row."""
    base = CompanyFinancials(
        ticker="NVDA",
        revenue=253_491_000_000.0,  # FMP TTM truth
        ebitda=100_000_000_000.0,
        net_income=159_613_000_000.0,
        market_cap=3_000_000_000_000.0,
        total_debt=10_000_000_000.0,
        total_cash=40_000_000_000.0,
        gross_margin=0.7,
        operating_margin=0.6,
    )

    out = override_company_with_xbrl(
        base,
        {
            "ttm_revenue": {
                "concept": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                "value": 10_918_000_000.0,  # frozen-concept degenerate value
            },
        },
    )

    assert out.revenue == 253_491_000_000.0  # kept FMP
    assert out.ttm_divergence_note is not None
    assert "[待核]" in out.ttm_divergence_note


def test_override_keeps_fmp_when_foreign_currency_xbrl_suppressed() -> None:
    """BUG-037: for a 20-F foreign private issuer the provider drops the native-
    currency XBRL TTM to None (no FX in the provider). The override must then keep
    the FX-normalized FMP USD base untouched — no divergence note, no native-
    currency value sneaking in under the 35% gate (near-parity GBP/EUR/CHF would
    otherwise slip through). The XBRL keys are present-but-None, exactly the shape
    ``edgar_provider._fetch_xbrl`` emits after suppressing a foreign-currency fact.
    """
    base = CompanyFinancials(
        ticker="SHEL",
        revenue=290_000_000_000.0,  # FMP TTM, already FX-normalized to USD
        ebitda=60_000_000_000.0,
        net_income=19_000_000_000.0,
        market_cap=210_000_000_000.0,
        total_debt=80_000_000_000.0,
        total_cash=40_000_000_000.0,
        gross_margin=0.2,
        operating_margin=0.1,
    )

    out = override_company_with_xbrl(
        base,
        {"ttm_revenue": None, "ttm_net_income": None},
    )

    # FMP USD base survives verbatim; no spurious [待核] note.
    assert out.revenue == 290_000_000_000.0
    assert out.net_income == 19_000_000_000.0
    assert out.ttm_divergence_note is None


def test_xbrl_concept_snapshot_groups_ttm_and_latest_facts() -> None:
    snapshot = xbrl_concept_snapshot(
        {
            "ttm_revenue": {
                "concept": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                "value": 451.0,
            },
            # BUG-009: latest_* is the provider's recovered-concept dict.
            "latest_net_income": {
                "concept": "us-gaap:NetIncomeLoss",
                "value": 97.0,
                "period_end": "2025-09-27",
                "units": "USD",
            },
        }
    )

    assert "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax" in snapshot
    # Annual net income now lives under the disambiguated :annual key
    assert "us-gaap:NetIncomeLoss" not in snapshot, (
        "bare NetIncomeLoss key must not exist; use :annual/:ttm suffixes"
    )
    assert snapshot["us-gaap:NetIncomeLoss:annual"][0]["value"] == 97.0


def test_xbrl_concept_snapshot_uses_real_matched_concept_not_hardcoded() -> None:
    """BUG-009: a post-ASC-606 issuer's latest revenue is keyed under the REAL
    matched concept (``RevenueFromContractWithCustomerExcludingAssessedTax``),
    never the old hardcoded ``us-gaap:Revenues`` — injecting the wrong SEC
    concept to the LLM was provenance falsification."""
    snapshot = xbrl_concept_snapshot(
        {
            "latest_revenue": {
                "concept": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                "value": 416_161_000_000.0,
                "period_end": "2025-09-27",
                "units": "USD",
            },
            "latest_total_assets": {
                "concept": "us-gaap:Assets",
                "value": 364_980_000_000.0,
                "period_end": "2026-03-29",
                "units": "USD",
            },
        }
    )

    rev_key = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    assert rev_key in snapshot
    assert "us-gaap:Revenues" not in snapshot, "must not re-tag revenue as the hardcoded concept"
    rev_entry = snapshot[rev_key][0]
    assert rev_entry["value"] == 416_161_000_000.0
    assert rev_entry["period_end"] == "2025-09-27"
    assert rev_entry["units"] == "USD"
    # Balance-sheet concept passes through as-is.
    assert snapshot["us-gaap:Assets"][0]["value"] == 364_980_000_000.0


def test_xbrl_concept_snapshot_rejects_legacy_bare_float() -> None:
    """A bare float (legacy/malformed payload) is dropped rather than re-tagged
    with a guessed concept — no fabricated provenance."""
    snapshot = xbrl_concept_snapshot({"latest_revenue": 999.0, "latest_net_income": 50.0})
    assert snapshot == {}
