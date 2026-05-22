"""Unit tests for assemble_recent_research + format_age_label."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from finagent.engine.aggregations.recent_research import (
    RecentResearchInput,
    assemble_recent_research,
    format_age_label,
)

NOW = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)


def _input(
    artifact_id: str,
    *,
    days_ago: int = 0,
    entry_price: float | None = 100.0,
    target_price: float | None = 120.0,
    current_price: float | None = 110.0,
    verdict: str | None = "BUY",
    ticker: str | None = "AAPL",
) -> RecentResearchInput:
    return RecentResearchInput(
        artifact_id=artifact_id,
        ticker=ticker,
        cross_tickers=(),
        type="equity_research",
        headline="thesis A",
        verdict=verdict,
        entry_price=entry_price,
        target_price=target_price,
        target_date=NOW - timedelta(days=days_ago) + timedelta(days=365),
        current_price=current_price,
        created_at=NOW - timedelta(days=days_ago),
    )


def test_limit_zero_returns_empty() -> None:
    out = assemble_recent_research(inputs=[_input("a")], limit=0, now=NOW)
    assert out == []


def test_sort_desc_and_top_n() -> None:
    inputs = [
        _input("old", days_ago=10),
        _input("new", days_ago=1),
        _input("medium", days_ago=5),
    ]
    out = assemble_recent_research(inputs=inputs, limit=2, now=NOW)
    assert [r.artifact_id for r in out] == ["new", "medium"]


def test_signal_filled_when_prices_present() -> None:
    out = assemble_recent_research(
        inputs=[_input("a", entry_price=100, target_price=120, current_price=115, days_ago=20)],
        limit=1,
        now=NOW,
    )
    assert out[0].signal in ("hit", "watching", "failed")
    assert out[0].delta_to_target_pct == pytest.approx(0.75)


def test_signal_none_when_prices_missing() -> None:
    out = assemble_recent_research(
        inputs=[_input("a", current_price=None)],
        limit=1,
        now=NOW,
    )
    assert out[0].signal is None
    assert out[0].delta_to_target_pct is None


def test_delta_clamps_outliers() -> None:
    """A target hit by 10x (e.g. cents-per-share special) shouldn't break charts."""
    out = assemble_recent_research(
        inputs=[_input("a", entry_price=1.0, target_price=2.0, current_price=100.0)],
        limit=1,
        now=NOW,
    )
    assert out[0].delta_to_target_pct == 2.0  # clamped upper bound


def test_equal_entry_and_target_yields_none_delta() -> None:
    out = assemble_recent_research(
        inputs=[_input("a", entry_price=100, target_price=100)],
        limit=1,
        now=NOW,
    )
    assert out[0].delta_to_target_pct is None


def test_format_age_label_under_minute() -> None:
    assert format_age_label(NOW - timedelta(seconds=30), NOW) == "just now"


def test_format_age_label_minute_hour_day() -> None:
    assert format_age_label(NOW - timedelta(minutes=15), NOW) == "15m ago"
    assert format_age_label(NOW - timedelta(hours=4), NOW) == "4h ago"
    assert format_age_label(NOW - timedelta(days=3), NOW) == "3d ago"


def test_format_age_label_switches_to_date_past_30_days() -> None:
    assert format_age_label(NOW - timedelta(days=45), NOW) == (NOW - timedelta(days=45)).strftime("%Y-%m-%d")


def test_format_age_label_handles_naive_datetime() -> None:
    naive = (NOW - timedelta(hours=2)).replace(tzinfo=None)
    assert format_age_label(naive, NOW) == "2h ago"
