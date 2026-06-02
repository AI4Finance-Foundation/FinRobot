"""RunStore.reconcile_orphaned_runs + latest_runs_by_ticker (Coverage Phase 2/M4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from finrobot.run_store import RunStore


@pytest.fixture
async def store(tmp_path: Path):
    s = RunStore(db_path=tmp_path / "runs.db")
    yield s
    await s.close()


async def test_reconcile_fails_orphaned_running_and_created(store: RunStore) -> None:
    created = await store.create_run("dcf", "AAPL")
    running = await store.create_run("dcf", "MSFT")
    await store.update_run(running.run_id, status="running")
    done = await store.create_run("dcf", "NVDA")
    await store.update_run(done.run_id, status="completed")

    n = await store.reconcile_orphaned_runs()
    assert n == 2  # created + running, not the completed one

    assert (await store.get_run(created.run_id)).status == "failed"  # type: ignore[union-attr]
    assert (await store.get_run(running.run_id)).status == "failed"  # type: ignore[union-attr]
    assert (await store.get_run(done.run_id)).status == "completed"  # type: ignore[union-attr]
    # idempotent — nothing left to reconcile
    assert await store.reconcile_orphaned_runs() == 0


async def test_latest_runs_by_ticker_returns_newest_per_ticker(store: RunStore) -> None:
    old = await store.create_run("dcf", "AAPL")
    await store.update_run(old.run_id, status="completed")
    new = await store.create_run("dcf", "AAPL")
    await store.update_run(new.run_id, status="failed", error="boom")
    await store.create_run("dcf", "MSFT")

    latest = await store.latest_runs_by_ticker(["AAPL", "MSFT", "TSLA"])
    assert latest["AAPL"].run_id == new.run_id  # newest wins
    assert latest["AAPL"].status == "failed"
    assert latest["AAPL"].error == "boom"
    assert latest["MSFT"].status == "created"
    assert "TSLA" not in latest  # never run


async def test_latest_runs_by_ticker_empty(store: RunStore) -> None:
    assert await store.latest_runs_by_ticker([]) == {}
