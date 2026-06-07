"""The equity_research artifact builder runs the numeric-audit gate (design §7, A):
findings surface into warnings + structured.numeric_audit; a blocked_field
(category-error / dimensionally-corrupt number) forces the report REVIEW_ONLY and
withholds the rating + price target. A clean report renders byte-identically.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast

from finrobot.artifact.builders import build_dcf_artifact, build_equity_research_artifact
from finrobot.engine.models.financial import (
    DCFInputs,
    DCFResult,
    FinancialData,
    IncomeStatement,
    MarketData,
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
