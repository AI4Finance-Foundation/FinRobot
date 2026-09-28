"""Tests for the shared 13F refresh trigger's skip/run guards.

Focus: the auto path (``force=False``) must NOT re-pull a quarter that is
already in cache in full. 13F-HR are filed ~45 days after quarter end, so for
roughly half of every quarter the latest *available* quarter is already >60
days old — the previous "cache younger than 60 days" window therefore re-pulled
an already-complete quarter on every boot. The guard now compares the cached
period against the latest *completed* quarter instead.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from finrobot.engine.data import sec_holdings_sync

_VALID_IDENTITY = "Acme Research analyst@example.com"


@pytest.fixture(autouse=True)
def _reset_refresh_state():
    sec_holdings_sync.reset_state_for_test()
    yield
    sec_holdings_sync.reset_state_for_test()


def _app() -> FastAPI:
    app = FastAPI()
    app.state.background_tasks = []
    return app


def _patch_env(monkeypatch, *, latest: str | None, target: date, complete: bool = True) -> None:
    import scripts.refresh_sec_holdings as refresh_mod
    from finrobot.engine.data import sec_holdings_cache as cache_mod

    async def _status() -> dict:
        return {
            "populated": latest is not None,
            "row_count": 100 if latest else 0,
            "latest_period_end": latest,
            "distinct_tickers": 7 if latest else 0,
        }

    async def _is_complete(_period) -> bool:
        return complete

    monkeypatch.setattr(cache_mod, "cache_status", _status)
    monkeypatch.setattr(cache_mod, "is_period_complete", _is_complete)
    monkeypatch.setattr(refresh_mod, "_latest_completed_quarter_end", lambda: target)


@pytest.mark.asyncio
async def test_skips_when_cache_already_at_latest_available_quarter(monkeypatch) -> None:
    """Cache holds 2026-03-31 in full (completion marker present) and that IS the
    newest filed quarter → skip, even though it's >60 days old. No task spawned."""
    _patch_env(monkeypatch, latest="2026-03-31", target=date(2026, 3, 31), complete=True)
    app = _app()
    state = await sec_holdings_sync.start_refresh(
        app, SimpleNamespace(sec_user_agent=_VALID_IDENTITY), force=False
    )
    assert state["status"] == "done"
    assert app.state.background_tasks == []


@pytest.mark.asyncio
async def test_runs_when_latest_quarter_present_but_incomplete(monkeypatch) -> None:
    """Cache holds rows for 2026-03-31 but the refresh never finished (no marker —
    an interrupted / --max-filings-capped run that dropped early filers like
    BlackRock). Must re-run to backfill instead of freezing the partial cache."""
    spawned: list = []

    async def _fake_run(period: date, header_identity: str) -> None:
        spawned.append(period)

    monkeypatch.setattr(sec_holdings_sync, "_run", _fake_run)
    _patch_env(monkeypatch, latest="2026-03-31", target=date(2026, 3, 31), complete=False)
    app = _app()
    state = await sec_holdings_sync.start_refresh(
        app, SimpleNamespace(sec_user_agent=_VALID_IDENTITY), force=False
    )
    assert state["status"] == "running"
    assert state["period_end"] == "2026-03-31"
    for task in app.state.background_tasks:
        await task
    assert spawned == [date(2026, 3, 31)]


@pytest.mark.asyncio
async def test_runs_when_a_newer_quarter_is_available(monkeypatch) -> None:
    """Cache stuck at 2025-12-31 but 2026-03-31 is now filed → must refresh."""
    spawned: list = []

    async def _fake_run(period: date, header_identity: str) -> None:
        spawned.append(period)

    monkeypatch.setattr(sec_holdings_sync, "_run", _fake_run)
    _patch_env(monkeypatch, latest="2025-12-31", target=date(2026, 3, 31))
    app = _app()
    state = await sec_holdings_sync.start_refresh(
        app, SimpleNamespace(sec_user_agent=_VALID_IDENTITY), force=False
    )
    assert state["status"] == "running"
    assert state["period_end"] == "2026-03-31"
    # let the spawned task run so we don't leak it / warn at teardown
    for task in app.state.background_tasks:
        await task
    assert spawned == [date(2026, 3, 31)]


@pytest.mark.asyncio
async def test_empty_cache_always_runs(monkeypatch) -> None:
    """No cache yet → refresh regardless of dates."""

    async def _fake_run(period: date, header_identity: str) -> None:
        pass

    monkeypatch.setattr(sec_holdings_sync, "_run", _fake_run)
    _patch_env(monkeypatch, latest=None, target=date(2026, 3, 31))
    app = _app()
    state = await sec_holdings_sync.start_refresh(
        app, SimpleNamespace(sec_user_agent=_VALID_IDENTITY), force=False
    )
    assert state["status"] == "running"
    for task in app.state.background_tasks:
        await task
