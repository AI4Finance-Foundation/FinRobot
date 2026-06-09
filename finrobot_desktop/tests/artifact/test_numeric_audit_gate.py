"""The equity_research artifact builder runs the numeric-audit gate (design §7, A):
findings surface into warnings + structured.numeric_audit; a blocked_field
(category-error / dimensionally-corrupt number) forces the report REVIEW_ONLY and
withholds the rating + price target. A clean report renders byte-identically.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast

from finrobot.artifact.builders import (
    build_comps_artifact,
    build_dcf_artifact,
    build_equity_research_artifact,
    build_ic_memo_artifact,
    build_lbo_artifact,
)
from finrobot.engine.models.financial import (
    CompanyFinancials,
    DCFInputs,
    DCFResult,
    FinancialData,
    ICFinancials,
    IncomeStatement,
    LBOResult,
    LBOYear,
    MarketData,
    PeerComps,
    ValuationMetrics,
)
from finrobot.engine.pipelines.base import PipelineResult

UTC = timezone.utc


def _fd(
    *,
    ticker: str = "X",
    industry: str | None = None,
    net_income: float | None = 20e9,
    ev_ebitda: float | None = None,
    reporting_currency: str = "USD",
    quote_currency: str = "USD",
) -> FinancialData:
    return FinancialData(
        ticker=ticker,
        timestamp=datetime(2026, 6, 6, 10, 0, 0, tzinfo=UTC),
        income=IncomeStatement(revenue=100e9, net_income=net_income),
        market=MarketData(
            market_cap=500e9, shares_outstanding=5e9, current_price=100.0, industry=industry
        ),
        valuation=ValuationMetrics(ev_ebitda=ev_ebitda),
        reporting_currency=reporting_currency,
        quote_currency=quote_currency,
        data_source="fake",
    )


def _result(fd: FinancialData, *, recommendation: str = "BUY", price_target: float | None = 100.0):
    return PipelineResult(
        steps={"data_collection": "ok", "thesis": "Price target $100"},
        structured_data={
            "data_collection": fd,
            "thesis": {
                "recommendation": recommendation,
                "price_target": price_target,
                "tagline": "t",
            },
        },
    )


def _dcf_result() -> DCFResult:
    inputs = DCFInputs(
        revenue_base=100e9,
        revenue_growth_rates=[0.03, 0.03, 0.02, 0.02, 0.02],
        ebitda_margin=0.30,
        capex_pct_revenue=0.04,
        nwc_pct_revenue=0.01,
        tax_rate=0.21,
        risk_free_rate=0.04,
        beta=1.0,
        equity_risk_premium=0.055,
        cost_of_debt=0.05,
        debt_ratio=0.20,
        terminal_growth_rate=0.025,
        shares_outstanding=5e9,
        net_debt=10e9,
        da_pct_revenue=0.03,
    )
    return DCFResult(
        cost_of_equity=0.095,
        wacc=0.082,
        projection_years=5,
        projected_revenue=[103e9, 106e9, 108e9, 110e9, 112e9],
        projected_ebitda=[30e9] * 5,
        projected_fcf=[10e9] * 5,
        terminal_value=200e9,
        pv_terminal=150e9,
        pv_fcf_total=40e9,
        enterprise_value=190e9,
        equity_value=180e9,
        implied_price=120.0,
        inputs=inputs,
    )


def _build(result, ticker="X"):
    return build_equity_research_artifact(result, ticker, cast(Any, None))


def test_clean_report_publishable_unchanged():
    art = _build(_result(_fd(industry="Software", ev_ebitda=18.0)))
    audit = art.outputs.structured["numeric_audit"]
    assert audit["artifact_status"] == "publishable"
    assert audit["withhold_valuation"] is False
    assert audit["findings"] == []
    # Rating / target untouched.
    assert art.outputs.structured["thesis"]["recommendation"] == "BUY"
    assert art.outputs.structured["thesis"]["price_target"] == 100.0
    assert art.outputs.llm_narrative["recommendation"] == "BUY"


def test_bank_ev_blocks_field_and_withholds_valuation():
    art = _build(_result(_fd(ticker="JPM", industry="Banks - Diversified", ev_ebitda=8.0)), "JPM")
    audit = art.outputs.structured["numeric_audit"]
    assert audit["artifact_status"] == "review_only"
    assert audit["withhold_valuation"] is True
    assert any(f["check"] == "financial_sector_ev_meaningless" for f in audit["findings"])
    # Banner: the finding surfaces in warnings.
    assert any("financial_sector_ev_meaningless" in w for w in art.outputs.warnings)
    # Behavior A: rating forced REVIEW + target withheld, in both copies.
    assert art.outputs.structured["thesis"]["recommendation"] == "REVIEW"
    assert art.outputs.structured["thesis"]["price_target"] is None
    assert art.outputs.llm_narrative["recommendation"] == "REVIEW"
    assert "$100" not in art.outputs.summary_text
    assert "Valuation withheld" in art.outputs.summary_text


def test_loss_maker_review_only_keeps_target():
    # review (not blocked) → REVIEW_ONLY banner but the DCF target survives.
    art = _build(_result(_fd(industry="Software", net_income=-1e9)))
    audit = art.outputs.structured["numeric_audit"]
    assert audit["artifact_status"] == "review_only"
    assert audit["withhold_valuation"] is False
    assert art.outputs.structured["thesis"]["price_target"] == 100.0
    assert art.outputs.structured["thesis"]["recommendation"] == "BUY"


def test_no_financial_data_publishable():
    result = PipelineResult(steps={"data_collection": "ok"}, structured_data={})
    art = build_equity_research_artifact(result, "AAPL", cast(Any, None))
    assert art.outputs.structured["numeric_audit"]["artifact_status"] == "publishable"


def test_standalone_dcf_carries_numeric_audit_when_clean():
    result = PipelineResult(
        steps={"historical_data": "ok", "dcf_calc": "ok"},
        structured_data={
            "historical_data": _fd(industry="Software", ev_ebitda=18.0),
            "dcf_calc": _dcf_result(),
        },
    )
    art = build_dcf_artifact(result, "X", cast(Any, None))

    assert art.outputs.structured["numeric_audit"]["artifact_status"] == "publishable"
    assert art.outputs.structured["implied_price"] == 120.0


def test_missing_fmp_key_marks_valuation_artifact_review_only():
    result = PipelineResult(
        steps={"historical_data": "ok", "dcf_calc": "ok"},
        structured_data={
            "historical_data": _fd(industry="Software", ev_ebitda=18.0),
            "dcf_calc": _dcf_result(),
        },
    )
    deps = SimpleNamespace(settings=SimpleNamespace(fmp_api_key="", language="en"))
    art = build_dcf_artifact(result, "X", cast(Any, deps))

    audit = art.outputs.structured["numeric_audit"]
    assert audit["artifact_status"] == "review_only"
    assert audit["data_capability"]["artifact_status"] == "review_only"
    assert audit["findings"] == []
    assert any("DATA-CAPABILITY" in w for w in art.outputs.warnings)
    assert art.outputs.structured["implied_price"] == 120.0


def test_standalone_dcf_blocks_direct_target_when_audit_withholds():
    result = PipelineResult(
        steps={"historical_data": "ok", "dcf_calc": "DCF implies $120 per share"},
        structured_data={
            "historical_data": _fd(ticker="JPM", industry="Banks - Diversified", ev_ebitda=8.0),
            "dcf_calc": _dcf_result(),
        },
    )
    art = build_dcf_artifact(result, "JPM", cast(Any, None))

    assert art.outputs.structured["numeric_audit"]["artifact_status"] == "review_only"
    assert art.outputs.structured["numeric_audit"]["withhold_valuation"] is True
    assert art.outputs.structured["valuation_withheld"] is True
    assert art.outputs.structured["implied_price"] is None
    assert "$120" not in art.outputs.summary_text
    assert "Valuation withheld" in art.outputs.summary_text
    assert any("financial_sector_ev_meaningless" in w for w in art.outputs.warnings)


# ---------------------------------------------------------------------------
# Standalone LBO / Comps: the gate must never claim "withheld" while the numbers
# still ship. LBO returns (IRR/MOIC) are fully target-derived → withhold them on
# a blocked_field. Comps has no single target price to null (the peer medians are
# not invalidated by a target-only blocked_field) → flag-but-publish, and the
# summary must stay honest rather than announce a withhold that never happened.
# ---------------------------------------------------------------------------


def _lbo_result() -> LBOResult:
    schedule = [
        LBOYear(
            year=i,
            revenue=100,
            ebitda=30,
            da=4,
            ebit=26,
            interest_expense=8,
            ebt=18,
            taxes=4,
            net_income=14,
            capex=4,
            delta_nwc=1,
            fcf=15,
            mandatory_amort=2,
            cash_sweep_amount=10,
            total_debt_paydown=12,
            ending_debt=max(0, 150 - 12 * i),
        )
        for i in range(1, 6)
    ]
    return LBOResult(
        entry_ev=300,
        entry_debt=150,
        entry_equity=150,
        schedule=schedule,
        exit_ebitda=40,
        exit_ev=480,
        exit_equity=400,
        moic=2.67,
        irr=0.21,
    )


def _peer_comps() -> PeerComps:
    target = CompanyFinancials(
        ticker="X", revenue=100e9, ebitda=30e9, net_income=20e9, market_cap=500e9
    )
    peer = CompanyFinancials(
        ticker="P", revenue=80e9, ebitda=24e9, net_income=16e9, market_cap=400e9
    )
    return PeerComps(target=target, peers=[peer], median_pe=20.0, warnings=[])


def _lbo_pipeline_result(fd: FinancialData) -> PipelineResult:
    return PipelineResult(
        steps={"data_collection": "ok", "lbo_calculation": "LBO implies 0.21 IRR"},
        structured_data={"data_collection": fd, "lbo_calculation": _lbo_result()},
    )


def _comps_pipeline_result(fd: FinancialData) -> PipelineResult:
    return PipelineResult(
        steps={"target_data": "ok", "statistical_bench": "Comps median P/E 20x"},
        structured_data={"target_data": fd, "statistical_bench": _peer_comps()},
    )


def test_standalone_lbo_clean_publishes_returns():
    art = build_lbo_artifact(
        _lbo_pipeline_result(_fd(industry="Software", ev_ebitda=18.0)), "X", cast(Any, None)
    )
    assert art.outputs.structured["numeric_audit"]["withhold_valuation"] is False
    assert art.outputs.structured["irr"] == 0.21
    assert art.outputs.structured["moic"] == 2.67
    assert "valuation_withheld" not in art.outputs.structured
    assert "Valuation withheld" not in art.outputs.summary_text


def test_standalone_lbo_withholds_returns_when_audit_blocks():
    art = build_lbo_artifact(
        _lbo_pipeline_result(_fd(ticker="JPM", industry="Banks - Diversified", ev_ebitda=8.0)),
        "JPM",
        cast(Any, None),
    )
    assert art.outputs.structured["numeric_audit"]["withhold_valuation"] is True
    assert art.outputs.structured["valuation_withheld"] is True
    # The headline returns are nulled — a return built on a corrupt target EBITDA
    # must not be published — but the ev/equity breakdown stays visible.
    assert art.outputs.structured["irr"] is None
    assert art.outputs.structured["moic"] is None
    assert art.outputs.structured["entry_ev"] == 300
    assert "Valuation withheld" in art.outputs.summary_text
    assert any("financial_sector_ev_meaningless" in w for w in art.outputs.warnings)


def test_standalone_comps_flags_but_does_not_claim_withheld():
    # Regression: a blocked_field made withhold_valuation True, but comps passes no
    # withhold_keys, so nothing is nulled. The summary must NOT lie about a withhold,
    # and the peer medians (not invalidated by a target-only blocked_field) ship.
    art = build_comps_artifact(
        _comps_pipeline_result(_fd(ticker="JPM", industry="Banks - Diversified", ev_ebitda=8.0)),
        "JPM",
        cast(Any, None),
    )
    audit = art.outputs.structured["numeric_audit"]
    assert audit["withhold_valuation"] is True  # the audit still records the block
    assert audit["artifact_status"] == "review_only"
    assert "valuation_withheld" not in art.outputs.structured  # nothing was withheld
    assert art.outputs.structured["median_pe"] == 20.0  # medians still published
    assert "Valuation withheld" not in art.outputs.summary_text  # summary stays honest
    assert any("financial_sector_ev_meaningless" in w for w in art.outputs.warnings)


# ---------------------------------------------------------------------------
# IC Memo: was the one builder that never ran the gate, yet its FinancialData is
# nested in ICFinancials.financial_data. Step 3 routes it through the shared sink
# so its snapshot is audited + the block ships for the audit banner + contract C4.
# No single per-share headline → the block is attached but nothing auto-withholds.
# ---------------------------------------------------------------------------


def _ic_memo_result(fd: FinancialData) -> PipelineResult:
    ic = ICFinancials(financial_data=fd, dcf_result=_dcf_result(), lbo_result=_lbo_result())
    return PipelineResult(
        steps={"financial_analysis": "ok"},
        structured_data={"financial_analysis": ic},
    )


def test_ic_memo_carries_numeric_audit_when_clean():
    art = build_ic_memo_artifact(
        _ic_memo_result(_fd(industry="Software", ev_ebitda=18.0)), "X", cast(Any, None)
    )
    audit = art.outputs.structured["numeric_audit"]
    assert audit["artifact_status"] == "publishable"
    assert audit["findings"] == []
    # The memo's DCF / LBO results still ship.
    assert "dcf_result" in art.outputs.structured
    assert "lbo_result" in art.outputs.structured


def test_ic_memo_audits_nested_snapshot_and_records_block():
    # The gate now runs on ICFinancials.financial_data (nested). A bank EV is a
    # blocked_field — the block + finding surface (banner + contract C4 read them),
    # but ic_memo has no single headline target, so nothing auto-withholds.
    art = build_ic_memo_artifact(
        _ic_memo_result(_fd(ticker="JPM", industry="Banks - Diversified", ev_ebitda=8.0)),
        "JPM",
        cast(Any, None),
    )
    audit = art.outputs.structured["numeric_audit"]
    assert audit["artifact_status"] == "review_only"
    assert audit["withhold_valuation"] is True  # the audit records the block
    assert any(f["check"] == "financial_sector_ev_meaningless" for f in audit["findings"])
    assert any("financial_sector_ev_meaningless" in w for w in art.outputs.warnings)
    # No single per-share headline → nothing auto-withheld; the DCF / LBO ship.
    assert "valuation_withheld" not in art.outputs.structured
    assert "dcf_result" in art.outputs.structured
