"""Plan-B report reconcile: the equity_research builder scans the report step's
$-amounts against every numeric leaf it freezes into the artifact (structured
snapshot + raw FinancialData). Unmatched amounts are redacted from the scanned
narrative steps, while a warning in outputs.warnings + a structured
``report_drift`` block preserves the audit evidence."""

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
    assert drift["redacted"] == ["$999.99"]
    assert "$999.99" not in artifact.outputs.summary_text
    assert "[unverified amount redacted]" in artifact.outputs.summary_text

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


def test_data_collection_narrative_is_scanned_too() -> None:
    """data_collection is ALSO an LLM free-text narrative and format_summary()
    puts it FIRST in summary_text — it used to be the one narrative the drift
    scan skipped."""
    result = PipelineResult(
        steps={
            "data_collection": "The data shows a $777.77 fair value emerging.",
            "report": "All figures consistent: revenue USD 391.0B.",
        },
        structured_data={"data_collection": _financial_data()},
    )
    artifact = build_equity_research_artifact(result, "AAPL", cast(Any, None))

    drift = artifact.outputs.structured.get("report_drift")
    assert drift is not None and drift["unmatched_count"] == 1
    assert drift["unmatched"][0]["token"] == "$777.77"
    assert "$777.77" not in artifact.outputs.summary_text


def test_earnings_builder_scans_its_two_narrative_steps() -> None:
    """The earnings builder was the ONE builder outside the shared drift sink
    ('no artifact type is silently left unscanned'). Its two LLM narrative
    steps must be scanned against the artifact's frozen leaves."""
    from finrobot.artifact.builders import build_earnings_artifact

    result = PipelineResult(
        steps={
            "financial_context": "ok",
            "earnings_analysis": "EPS beat driven by a fabricated $123.45 figure.",
            "forward_outlook": "Outlook implies $678.90 next quarter.",
        },
        structured_data={"financial_context": _financial_data()},
    )
    artifact = build_earnings_artifact(result, "AAPL", cast(Any, None))

    drift = artifact.outputs.structured.get("report_drift")
    assert drift is not None
    tokens = {f["token"] for f in drift["unmatched"]}
    assert {"$123.45", "$678.90"} <= tokens
    assert "$123.45" not in artifact.outputs.summary_text
    assert "$678.90" not in artifact.outputs.summary_text
    assert any(w.startswith("[REPORT-DRIFT") for w in artifact.outputs.warnings)


def test_failed_validations_surface_in_artifact_warnings() -> None:
    """A degraded step (validation failed after retries) used to exist only in
    summary_text prose — the machine-readable warnings array said nothing, so
    UI/coverage consumers treated a half-degraded report like a clean one."""
    result = PipelineResult(
        steps={"data_collection": "ok", "report": "clean"},
        structured_data={"data_collection": _financial_data()},
        failed_validations=[{"step": "peer_analysis", "error": "no usable peers"}],
    )
    artifact = build_equity_research_artifact(result, "AAPL", cast(Any, None))

    assert any("peer_analysis" in w and "degraded" in w for w in artifact.outputs.warnings), (
        artifact.outputs.warnings
    )


def test_approximation_of_a_real_leaf_is_kept_not_redacted() -> None:
    # "roughly USD 400B" against the 391.035B revenue leaf (2.3% off): a legit
    # LLM rounding — stays in prose, flagged for review, never redacted.
    report = "# Report\n\nRevenue of roughly USD 400B anchors the thesis."
    artifact = build_equity_research_artifact(_result(report), "AAPL", cast(Any, None))

    assert "USD 400B" in artifact.outputs.summary_text
    assert "[unverified amount redacted]" not in artifact.outputs.summary_text
    drift = artifact.outputs.structured["report_drift"]
    assert drift["unmatched_count"] == 1
    assert drift["approximate_count"] == 1
    assert drift["redacted"] == []
    review = [w for w in artifact.outputs.warnings if w.startswith("[REPORT-DRIFT/review]")]
    assert len(review) == 1 and "USD 400B" in review[0]
    assert not [w for w in artifact.outputs.warnings if w.startswith("[REPORT-DRIFT/redacted]")]


def test_frozen_session_change_amount_is_not_redacted() -> None:
    """The data agent narrates a real derived figure — the day's price change
    amount (last_close − prev_close) it is shown in the PRICE prompt summary. It is
    NOT reconstructable from any other frozen field, so execute_financial_data_step
    freezes it as a dedicated ``price_session`` leaf; the drift scan must then match
    it and leave the narrative intact (MSFT 2026-07-07 orphan-redaction regression)."""
    report = "# Report\n\nLatest Session Change: -$3.75 (-0.96%) into today's close."
    result = PipelineResult(
        steps={"data_collection": "ok", "report": report},
        structured_data={
            "data_collection": _financial_data(),
            "price_session": {
                "latest_session_change": -3.75,
                "latest_session_change_pct": -0.9603,
            },
        },
    )
    artifact = build_equity_research_artifact(result, "AAPL", cast(Any, None))

    assert "-$3.75" in artifact.outputs.summary_text
    assert "[unverified amount redacted]" not in artifact.outputs.summary_text
    # The frozen amount is a leaf now → the only $-amount matches → no drift block.
    assert "report_drift" not in artifact.outputs.structured
    # ...and it is frozen into the artifact for traceability (analyst can drill in).
    assert artifact.outputs.structured["price_session"]["latest_session_change"] == -3.75


def test_session_change_amount_without_freeze_is_redacted_as_orphan() -> None:
    """Same narrative, but no ``price_session`` frozen (e.g. <2 price bars): the
    behavior is exactly the pre-fix path — the amount matches no leaf and is
    redacted. Pins that the fix is the FROZEN leaf, not a tolerance/regex loosening
    (and that ``price × pct/100`` was never the mechanism — the exact amount is)."""
    report = "# Report\n\nLatest Session Change: -$3.75 (-0.96%) into today's close."
    result = PipelineResult(
        steps={"data_collection": "ok", "report": report},
        structured_data={"data_collection": _financial_data()},
    )
    artifact = build_equity_research_artifact(result, "AAPL", cast(Any, None))

    drift = artifact.outputs.structured["report_drift"]
    assert drift["redacted"] == ["-$3.75"]
    assert "-$3.75" not in artifact.outputs.summary_text
    assert "[unverified amount redacted]" in artifact.outputs.summary_text


def test_mixed_approximation_survives_while_orphan_is_redacted() -> None:
    # $999.99 is near NOTHING the artifact computed → redacted; the 400B
    # approximation in the same narrative must survive the redaction pass.
    report = "# Report\n\nRoughly USD 400B in revenue supports a $999.99 target."
    artifact = build_equity_research_artifact(_result(report), "AAPL", cast(Any, None))

    assert "USD 400B" in artifact.outputs.summary_text
    assert "$999.99" not in artifact.outputs.summary_text
    assert "[unverified amount redacted]" in artifact.outputs.summary_text
    drift = artifact.outputs.structured["report_drift"]
    assert drift["redacted"] == ["$999.99"]
    assert drift["approximate_count"] == 1
    kinds = {w.split()[0] for w in artifact.outputs.warnings if w.startswith("[REPORT-DRIFT")}
    assert kinds == {"[REPORT-DRIFT/redacted]", "[REPORT-DRIFT/review]"}
