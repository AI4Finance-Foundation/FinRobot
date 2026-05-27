"""Unit tests for compute_hit_rate_overview — pure-function semantics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from finrobot.engine.aggregations.hit_rate_overview import (
    ArtifactSignalInput,
    compute_hit_rate_overview,
)

NOW = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)


def _input(
    *,
    verdict: str | None = "BUY",
    entry_price: float | None = 100.0,
    target_price: float | None = 130.0,
    current_price: float | None = 100.0,
    days_ago: int = 0,
    target_in_days: int | None = 365,
) -> ArtifactSignalInput:
    entry_date = NOW - timedelta(days=days_ago)
    target_date = entry_date + timedelta(days=target_in_days) if target_in_days else None
    return ArtifactSignalInput(
        entry_price=entry_price,
        target_price=target_price,
        current_price=current_price,
        entry_date=entry_date,
        target_date=target_date,
        verdict=verdict,
    )


def test_empty_input_returns_zero_buckets() -> None:
    res = compute_hit_rate_overview(artifacts=[], window="all", now=NOW)
    assert res.overall.n_total == 0
    assert res.overall.hit_rate is None
    assert set(res.by_verdict.keys()) == {"BUY", "HOLD", "SELL"}
    for b in res.by_verdict.values():
        assert b.n_total == 0


def test_all_hit_buy_recommendations() -> None:
    arts = [
        _input(verdict="BUY", entry_price=100, target_price=130, current_price=128),
        _input(verdict="BUY", entry_price=50, target_price=70, current_price=65),
    ]
    res = compute_hit_rate_overview(artifacts=arts, window="all", now=NOW)
    assert res.overall.n_total == 2
    assert res.overall.n_hit == 2
    assert res.overall.hit_rate == pytest.approx(1.0)
    assert res.by_verdict["BUY"].n_hit == 2
    assert res.by_verdict["HOLD"].n_total == 0
    assert res.by_verdict["SELL"].n_total == 0


def test_mixed_hit_and_failed_with_grace_period_respected() -> None:
    arts = [
        # Inside 7-day grace → watching, won't show up in n_closed.
        _input(
            verdict="BUY",
            entry_price=100,
            target_price=130,
            current_price=80,
            days_ago=3,
        ),
        # Outside grace + reversed 20% → failed.
        _input(
            verdict="BUY",
            entry_price=100,
            target_price=130,
            current_price=80,
            days_ago=14,
        ),
        # Hit band.
        _input(
            verdict="BUY",
            entry_price=100,
            target_price=130,
            current_price=128,
            days_ago=30,
        ),
    ]
    res = compute_hit_rate_overview(artifacts=arts, window="all", now=NOW)
    assert res.overall.n_total == 3
    assert res.overall.n_closed == 2
    assert res.overall.n_hit == 1
    assert res.overall.hit_rate == pytest.approx(0.5)


def test_window_30d_cuts_older_artifacts() -> None:
    arts = [
        _input(days_ago=10, current_price=130),  # in window, hit
        _input(days_ago=60, current_price=130),  # out of 30d window
    ]
    res = compute_hit_rate_overview(artifacts=arts, window="30d", now=NOW)
    assert res.overall.n_total == 1
    assert res.window == "30d"


def test_missing_prices_drop_silently() -> None:
    arts = [
        _input(entry_price=None),
        _input(target_price=None),
        _input(current_price=None),
        _input(entry_price=0),
        _input(),  # valid one
    ]
    res = compute_hit_rate_overview(artifacts=arts, window="all", now=NOW)
    assert res.overall.n_total == 1


def test_verdict_none_contributes_to_overall_only() -> None:
    arts = [
        _input(verdict=None, current_price=130),
        _input(verdict="HOLD", current_price=130),
    ]
    res = compute_hit_rate_overview(artifacts=arts, window="all", now=NOW)
    assert res.overall.n_total == 2
    assert res.by_verdict["HOLD"].n_total == 1
    assert res.by_verdict["BUY"].n_total == 0


def test_equal_entry_and_target_is_dropped_not_raised() -> None:
    """compute_signal raises on entry==target — overview must guard against it."""
    arts = [
        _input(entry_price=100, target_price=100),
        _input(),
    ]
    res = compute_hit_rate_overview(artifacts=arts, window="all", now=NOW)
    assert res.overall.n_total == 1
