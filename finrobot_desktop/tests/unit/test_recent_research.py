"""Unit tests for assemble_recent_tickers (drawer cards) + format_age_label."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from finrobot.engine.aggregations.recent_research import (
    MAX_RUNS_PER_TICKER,
    RecentResearchInput,
    assemble_recent_tickers,
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
    type_: str = "research",
) -> RecentResearchInput:
    return RecentResearchInput(
        artifact_id=artifact_id,
        ticker=ticker,
        cross_tickers=(),
        type=type_,
        headline=f"thesis {artifact_id}",
        verdict=verdict,
        entry_price=entry_price,
        target_price=target_price,
        target_date=NOW - timedelta(days=days_ago) + timedelta(days=365),
        current_price=current_price,
        created_at=NOW - timedelta(days=days_ago),
    )


def test_limit_zero_returns_empty() -> None:
    out = assemble_recent_tickers(inputs=[_input("a")], limit=0, now=NOW)
    assert out == []


def test_groups_same_ticker_into_one_card_with_runs() -> None:
    """Four AAPL runs collapse into one card with 4 rows newest-first."""
    out = assemble_recent_tickers(
        inputs=[
            _input("a1", days_ago=10, type_="research", verdict="BUY"),
            _input("a2", days_ago=5, type_="dcf", verdict=None),
            _input("a3", days_ago=2, type_="lbo", verdict=None),
            _input("a4", days_ago=0, type_="ic-memo", verdict="HOLD"),
        ],
        limit=5,
        now=NOW,
    )
    assert len(out) == 1
    card = out[0]
    assert card.ticker == "AAPL"
    assert card.run_count == 4
    # Rows are newest-first
    assert [r.artifact_id for r in card.runs] == ["a4", "a3", "a2", "a1"]
    assert [r.type for r in card.runs] == ["ic-memo", "lbo", "dcf", "research"]
    assert [r.verdict for r in card.runs] == ["HOLD", None, None, "BUY"]


def test_runs_capped_at_max_per_ticker_but_run_count_is_true_total() -> None:
    """Ticker with 8 runs surfaces 5 rows + run_count=8 for overflow UI."""
    inputs = [_input(f"a{i}", days_ago=i, type_="research") for i in range(8)]
    out = assemble_recent_tickers(inputs=inputs, limit=5, now=NOW)
    card = out[0]
    assert card.run_count == 8
    assert len(card.runs) == MAX_RUNS_PER_TICKER == 5
    # Newest 5 surface — that's days_ago 0..4
    assert [r.artifact_id for r in card.runs] == ["a0", "a1", "a2", "a3", "a4"]


def test_top_n_distinct_tickers_by_latest_at() -> None:
    """Among 3 tickers, top-2 = the two most recently touched."""
    inputs = [
        _input("aapl1", ticker="AAPL", days_ago=20),
        _input("aapl2", ticker="AAPL", days_ago=15),  # AAPL latest = 15d ago
        _input("msft1", ticker="MSFT", days_ago=1),  # MSFT latest = 1d ago
        _input("nvda1", ticker="NVDA", days_ago=5),  # NVDA latest = 5d ago
    ]
    out = assemble_recent_tickers(inputs=inputs, limit=2, now=NOW)
    assert [v.ticker for v in out] == ["MSFT", "NVDA"]


def test_drops_inputs_without_ticker() -> None:
    out = assemble_recent_tickers(
        inputs=[_input("orphan", ticker=None), _input("a", ticker="AAPL")],
        limit=5,
        now=NOW,
    )
    assert [v.ticker for v in out] == ["AAPL"]


def test_latest_signal_from_latest_run_only() -> None:
    """Header lamp reflects the latest run's price-vs-target relationship."""
    out = assemble_recent_tickers(
        inputs=[
            _input("old", days_ago=30, current_price=95.0),  # would be watching
            _input(
                "new",
                days_ago=1,
                entry_price=100,
                target_price=120,
                current_price=125,  # hit
            ),
        ],
        limit=1,
        now=NOW,
    )
    assert out[0].latest_signal == "hit"


def test_latest_signal_none_when_latest_run_lacks_prices() -> None:
    out = assemble_recent_tickers(
        inputs=[_input("a", current_price=None)],
        limit=1,
        now=NOW,
    )
    assert out[0].latest_signal is None


def test_each_row_carries_its_own_verdict() -> None:
    out = assemble_recent_tickers(
        inputs=[
            _input("buy_old", days_ago=10, verdict="BUY"),
            _input("hold_mid", days_ago=5, verdict="HOLD"),
            _input("sell_new", days_ago=1, verdict="SELL"),
        ],
        limit=1,
        now=NOW,
    )
    verdicts = [r.verdict for r in out[0].runs]
    assert verdicts == ["SELL", "HOLD", "BUY"]


def test_format_age_label_under_minute() -> None:
    assert format_age_label(NOW - timedelta(seconds=30), NOW) == "just now"


def test_format_age_label_minute_hour_day() -> None:
    assert format_age_label(NOW - timedelta(minutes=15), NOW) == "15m ago"
    assert format_age_label(NOW - timedelta(hours=4), NOW) == "4h ago"
    assert format_age_label(NOW - timedelta(days=3), NOW) == "3d ago"


def test_format_age_label_switches_to_date_past_30_days() -> None:
    assert format_age_label(NOW - timedelta(days=45), NOW) == (NOW - timedelta(days=45)).strftime(
        "%Y-%m-%d"
    )


def test_format_age_label_handles_naive_datetime() -> None:
    naive = (NOW - timedelta(hours=2)).replace(tzinfo=None)
    assert format_age_label(naive, NOW) == "2h ago"


def test_row_age_labels_format_correctly() -> None:
    out = assemble_recent_tickers(
        inputs=[
            _input("a", days_ago=0),
            _input("b", days_ago=3),
        ],
        limit=1,
        now=NOW,
    )
    # days_ago=0 means created_at == NOW which is exactly 0 seconds delta → "just now"
    assert out[0].runs[0].age_label == "just now"
    assert out[0].runs[1].age_label == "3d ago"


@pytest.mark.parametrize("ticker", ["AAPL", "META", "NVDA"])
def test_card_includes_ticker_verbatim(ticker: str) -> None:
    out = assemble_recent_tickers(
        inputs=[_input("a", ticker=ticker)],
        limit=1,
        now=NOW,
    )
    assert out[0].ticker == ticker
