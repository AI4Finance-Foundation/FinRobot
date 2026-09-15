"""The equity_research builder must FREEZE the pipeline's multi-year
HistoricalMetrics into outputs.structured.historical_metrics, so the report's
financial-trend charts render from the snapshot instead of a live ['historical']
refetch.

Why this matters (report-internal consistency, not storage): the narrative's
growth / multi-year-trend claims are COMPUTED from these series. If the chart
re-fetched live at export time, a new fiscal year landing or a restatement would
drift the chart endpoints out of sync with the frozen prose — the report would
contradict itself. So the series must be pinned to the same snapshot as the
narrative.

The series ride INSIDE outputs.structured (a generic JSON dict) — no Artifact
model schema change; simply absent on legacy artifacts (the frontend deriver
maps a missing key to null, no crash).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

from finrobot.artifact.builders import build_equity_research_artifact
from finrobot.engine.models.financial import (
    BalanceSheet,
    FinancialData,
    HistoricalMetrics,
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
        income=IncomeStatement(revenue=391_000_000_000, ebitda=131_000_000_000),
        balance=BalanceSheet(total_debt=100_000_000_000, total_cash=60_000_000_000),
        market=MarketData(
            market_cap=3_000_000_000_000,
            shares_outstanding=15_000_000_000,
            current_price=200.0,
        ),
        valuation=ValuationMetrics(),
        data_source="fake",
    )


def _historical() -> HistoricalMetrics:
    # Three fiscal years; only the series the chart adapters actually read need
    # real values, but every required field is populated so the model validates.
    return HistoricalMetrics(
        years=[2022, 2023, 2024],
        revenue=[394_000_000_000, 383_000_000_000, 391_000_000_000],
        revenue_growth_yoy=[None, -0.028, 0.021],
        cogs=[None, None, None],
        gross_profit=[None, None, None],
        gross_margin=[0.43, 0.44, 0.46],
        sga=[0.0, 0.0, 0.0],
        sga_ratio=[None, None, None],
        ebitda=[130_000_000_000, 125_000_000_000, 131_000_000_000],
        ebitda_margin=[0.33, 0.33, 0.34],
        operating_income=[119_000_000_000, 114_000_000_000, 123_000_000_000],
        operating_margin=[0.30, 0.30, 0.31],
        net_income=[99_000_000_000, 97_000_000_000, 93_000_000_000],
        eps=[6.11, 6.13, 6.08],
        pe_ratio=[None, None, None],
        cagr_revenue=-0.004,
        ticker="AAPL",
        operating_cash_flow=[122_000_000_000, 110_000_000_000, 118_000_000_000],
        investing_cash_flow=[-22_000_000_000, -10_000_000_000, -2_000_000_000],
        financing_cash_flow=[-110_000_000_000, -108_000_000_000, -94_000_000_000],
    )


def test_equity_research_freezes_historical_metrics() -> None:
    result = PipelineResult(
        steps={"data_collection": "ok"},
        structured_data={
            "data_collection": _financial_data(),
            "historical_metrics": _historical(),
        },
    )
    artifact = build_equity_research_artifact(result, "AAPL", cast(Any, None))

    hm = artifact.outputs.structured["historical_metrics"]
    assert hm["years"] == [2022, 2023, 2024]
    assert hm["revenue"][-1] == 391_000_000_000
    assert hm["eps"] == [6.11, 6.13, 6.08]
    # Every series the four chart adapters consume must be present in the frozen
    # snapshot (revenue/EBITDA, margins, cash-flow, EPS).
    for key in (
        "gross_margin",
        "ebitda_margin",
        "operating_margin",
        "operating_cash_flow",
        "investing_cash_flow",
        "financing_cash_flow",
    ):
        assert key in hm, f"frozen historical_metrics missing chart series {key!r}"


def test_historical_metrics_absent_when_pipeline_lacks_it() -> None:
    # A degraded / legacy run with no historical step → the key is simply absent.
    # The frontend deriver maps a missing key to null (no chart, no crash); the
    # builder must NOT fabricate an empty block.
    result = PipelineResult(
        steps={"data_collection": "ok"},
        structured_data={"data_collection": _financial_data()},
    )
    artifact = build_equity_research_artifact(result, "AAPL", cast(Any, None))

    assert "historical_metrics" not in artifact.outputs.structured
