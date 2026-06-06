"""The equity_research artifact builder runs the numeric-audit gate (design §7, A):
findings surface into warnings + structured.numeric_audit; a blocked_field
(category-error / dimensionally-corrupt number) forces the report REVIEW_ONLY and
withholds the rating + price target. A clean report renders byte-identically.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

from finrobot.artifact.builders import build_equity_research_artifact
from finrobot.engine.models.financial import (
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
        steps={"data_collection": "ok", "thesis": "ok"},
        structured_data={
            "data_collection": fd,
            "thesis": {
                "recommendation": recommendation,
                "price_target": price_target,
                "tagline": "t",
            },
        },
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
