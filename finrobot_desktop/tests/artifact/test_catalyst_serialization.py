"""The catalyst internal net-sentiment WEIGHT (probability: 0.7 news / 1.0 8-K)
must never reach a serialized surface. An external review found ~50 ``"probability":
0.7`` objects embedded in the exported report HTML (desktop bundle.ts stringifies
the whole artifact). ``CatalystEvent.probability`` is now ``exclude=True``, so it is
crunched in-memory (ranking / net_sentiment) but dropped from every model_dump."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

from finrobot.artifact.builders import build_equity_research_artifact
from finrobot.engine.models.financial import (
    BalanceSheet,
    CatalystAnalysis,
    CatalystEvent,
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


def _catalyst_analysis() -> CatalystAnalysis:
    news = CatalystEvent(
        category="market",
        headline="Apple raises Services prices",
        sentiment="positive",
        impact_score=4,
        probability=0.7,  # news weight
        reasoning="x",
    )
    eightk = CatalystEvent(
        category="management",
        headline="SEC 8-K: Item 5.02",
        sentiment="neutral",
        impact_score=3,
        probability=1.0,  # primary-source 8-K weight
        reasoning="x",
    )
    return CatalystAnalysis(
        events=[news, eightk],
        overall_sentiment="bullish",
        key_catalysts=[news.headline],
        net_sentiment=1.4,
        category_breakdown={"market": 1, "management": 1},
        top_positive=[news],
        top_negative=[],
    )


def test_catalyst_probability_never_serialized_into_the_artifact() -> None:
    result = PipelineResult(
        steps={"data_collection": "ok", "report": "Revenue USD 391.0B; stock at $198.11."},
        structured_data={
            "data_collection": _financial_data(),
            "catalyst_analysis": _catalyst_analysis(),
        },
    )
    artifact = build_equity_research_artifact(result, "AAPL", cast(Any, None))

    catalyst = artifact.outputs.structured["catalyst_analysis"]
    # probability lives on CatalystEvent in three sub-lists — none may carry it.
    for bucket in ("events", "top_positive", "top_negative"):
        for event in catalyst.get(bucket, []):
            assert "probability" not in event, f"probability leaked in {bucket}: {event}"

    # Belt-and-braces: the WHOLE serialized artifact (what bundle.ts embeds) is free
    # of the leak, caught even if a future field nests a CatalystEvent elsewhere.
    assert '"probability"' not in artifact.model_dump_json()


def test_ranking_math_survives_the_exclusion() -> None:
    # The weight still drives the math via attribute access — a primary-source 8-K
    # (impact 3 × 1.0) must out-rank an equal-magnitude news item that only ties on
    # raw impact, proving exclude=True did not neuter the in-memory computation.
    from finrobot.engine.compute.operators.catalyst import compute_expected_impact

    news = CatalystEvent(
        category="market",
        headline="n",
        sentiment="positive",
        impact_score=4,
        probability=0.7,
        reasoning="x",
    )  # |EI| = 4 × 0.7 = 2.8
    eightk = CatalystEvent(
        category="management",
        headline="8k",
        sentiment="positive",
        impact_score=3,
        probability=1.0,
        reasoning="x",
    )  # |EI| = 3 × 1.0 = 3.0 — higher despite lower impact_score
    ranked = compute_expected_impact([news, eightk])
    assert ranked[0].headline == "8k"
