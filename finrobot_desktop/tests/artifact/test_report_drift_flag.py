"""Plan-B report reconcile: the equity_research builder scans the report step's
$-amounts against every numeric leaf it freezes into the artifact (structured
snapshot + raw FinancialData). Unmatched amounts are FLAGGED — a warning in
outputs.warnings + a structured ``report_drift`` block — and never rewritten
(rewriting without a complete registry would corrupt legitimate numbers; the
warning costs one triage glance)."""

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


def _financial_data() -> FinancialData:
    return FinancialData(
        ticker="AAPL",
        timestamp=datetime(2026, 5, 13, 10, 0, 0, tzinfo=UTC),
        income=IncomeStatement(revenue=391_035_000_000, ebitda=134_661_000_000),
        balance=BalanceSheet(total_debt=106_629_000_000, total_cash=65_171_000_000),
        market=MarketData(
            market_cap=3_010_000_000_000,
            shares_outstanding=15_204_137_000,
            current_price=198.11,
        ),
        valuation=ValuationMetrics(),
        data_source="fake",
    )


def _result(report_text: str) -> PipelineResult:
    return PipelineResult(
        steps={"data_collection": "ok", "report": report_text},
        structured_data={"data_collection": _financial_data()},
    )


def test_fabricated_report_amount_is_flagged_into_warnings_and_provenance() -> None:
    # $391.0B matches income.revenue; $999.99 matches nothing the artifact holds.
    report = "# Report\n\n## Valuation\nRevenue USD 391.0B supports a $999.99 target."
    artifact = build_equity_research_artifact(_result(report), "AAPL", cast(Any, None))

    drift = artifact.outputs.structured["report_drift"]
    assert drift["unmatched_count"] == 1
    assert drift["unmatched"][0]["token"] == "$999.99"

    drift_warnings = [w for w in artifact.outputs.warnings if w.startswith("[REPORT-DRIFT")]
    assert len(drift_warnings) == 1
    assert "$999.99" in drift_warnings[0]


def test_clean_report_carries_no_drift_flag() -> None:
    # Every amount traces to a frozen leaf (revenue + current price) → no block,
    # no warning — publishable artifacts stay byte-identical to before.
    report = "# Report\n\n## Valuation\nRevenue USD 391.0B; the stock trades at $198.11."
    artifact = build_equity_research_artifact(_result(report), "AAPL", cast(Any, None))

    assert "report_drift" not in artifact.outputs.structured
    assert not any(w.startswith("[REPORT-DRIFT") for w in artifact.outputs.warnings)


def test_missing_report_step_means_no_scan() -> None:
    # Pipelines that fail before the report step still build a (degraded)
    # artifact — nothing to scan, nothing to flag.
    result = PipelineResult(
        steps={"data_collection": "ok"},
        structured_data={"data_collection": _financial_data()},
    )
    artifact = build_equity_research_artifact(result, "AAPL", cast(Any, None))
    assert "report_drift" not in artifact.outputs.structured
