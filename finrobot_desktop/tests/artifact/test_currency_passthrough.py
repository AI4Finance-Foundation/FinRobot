"""BUG-030: the equity_research builder must surface BOTH currency tags into the
generic structured payload so the report chapters can label every amount in its
true currency instead of a hardcoded '$'.

Two currencies, because they DISAGREE for foreign-listed ADRs:
  - quote_currency    → per-share & market-cap fields
  - reporting_currency → income-statement / balance-sheet absolutes

The tags ride INSIDE outputs.structured (a generic JSON dict) — no Artifact
model schema change. They are sourced from the FinancialData snapshot
(raw_data), defaulting to USD when absent so US reports stay byte-identical.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

from finrobot.artifact.builders import build_equity_research_artifact
from finrobot.engine.models.financial import (
    BalanceSheet,
    FinancialData,
    IncomeStatement,
    MarketData,
    ValuationMetrics,
)
from finrobot.engine.pipelines.base import PipelineResult

UTC = timezone.utc


def _financial_data(
    *, reporting_currency: str = "USD", quote_currency: str = "USD"
) -> FinancialData:
    return FinancialData(
        ticker="TSM",
        timestamp=datetime(2026, 5, 13, 10, 0, 0, tzinfo=UTC),
        income=IncomeStatement(revenue=2_160_000_000_000, ebitda=1_400_000_000_000),
        balance=BalanceSheet(total_debt=900_000_000_000, total_cash=1_500_000_000_000),
        market=MarketData(
            market_cap=900_000_000_000,
            shares_outstanding=5_000_000_000,
            current_price=180.0,
        ),
        valuation=ValuationMetrics(),
        reporting_currency=reporting_currency,
        quote_currency=quote_currency,
        data_source="fake",
    )


def _result(fd: FinancialData) -> PipelineResult:
    return PipelineResult(
        steps={"data_collection": "ok"},
        structured_data={"data_collection": fd},
    )


def test_equity_research_surfaces_both_currency_tags() -> None:
    # TSM ADR: quote=USD (marketCap/price), reporting=TWD (revenue/ebitda/debt).
    fd = _financial_data(reporting_currency="TWD", quote_currency="USD")
    artifact = build_equity_research_artifact(_result(fd), "TSM", cast(Any, None))

    currency = artifact.outputs.structured["currency"]
    assert currency == {"quote_currency": "USD", "reporting_currency": "TWD"}


def test_currency_defaults_to_usd_for_legacy_untagged_data() -> None:
    # A US issuer (both USD) must render byte-identically to before — the block
    # is present and both tags are USD.
    fd = _financial_data(reporting_currency="USD", quote_currency="USD")
    artifact = build_equity_research_artifact(_result(fd), "AAPL", cast(Any, None))

    assert artifact.outputs.structured["currency"] == {
        "quote_currency": "USD",
        "reporting_currency": "USD",
    }


def test_currency_block_present_when_no_financial_data() -> None:
    # No FinancialData snapshot at all → raw_data is empty; the block still
    # exists and defaults to USD (never absent, never crashes downstream).
    result = PipelineResult(steps={"data_collection": "ok"}, structured_data={})
    artifact = build_equity_research_artifact(result, "AAPL", cast(Any, None))

    assert artifact.outputs.structured["currency"] == {
        "quote_currency": "USD",
        "reporting_currency": "USD",
    }
