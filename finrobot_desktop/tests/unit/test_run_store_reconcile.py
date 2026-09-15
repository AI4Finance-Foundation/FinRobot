"""RunStore.reconcile_orphaned_runs + latest_runs_by_ticker (Coverage Phase 2/M4)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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

    # Each orphan got a run.failed TERMINAL EVENT, not just a status flip — a
    # desktop reattaching the run's SSE stream after the restart needs the
    # event or its card hangs on the last pre-restart step forever.
    for orphan in (created, running):
        events = await store.get_events_after(orphan.run_id, 0)
        failed = [e for e in events if e.event.get("event") == "run.failed"]
        assert len(failed) == 1
        assert failed[0].event.get("error") == "interrupted by server restart"
    # The already-terminal run got no spurious terminal event.
    assert await store.get_events_after(done.run_id, 0) == []


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


async def _set_completed_at(store: RunStore, run_id: str, when: datetime) -> None:
    conn = await store._ensure_connection()
    await conn.execute(
        "UPDATE runs SET completed_at = ? WHERE run_id = ?",
        (when.isoformat(), run_id),
    )
    await conn.commit()


def _started(run_id: str, ticker: str) -> dict:
    return {
        "event": "run.started",
        "run_id": run_id,
        "pipeline_type": "dcf",
        "ticker": ticker,
        "total_steps": 3,
    }


async def test_prune_run_events_drops_old_terminal_events_keeps_runs(store: RunStore) -> None:
    """BUG-050: prune deletes the event log of long-finished runs but keeps the
    runs rows themselves, and never touches live/recent runs."""
    now = datetime.now(tz=timezone.utc)

    old = await store.create_run("dcf", "AAPL")
    await store.append_event(old.run_id, _started(old.run_id, "AAPL"))  # type: ignore[arg-type]
    await store.append_event(old.run_id, _started(old.run_id, "AAPL"))  # type: ignore[arg-type]
    await store.update_run(old.run_id, status="completed")
    await _set_completed_at(store, old.run_id, now - timedelta(days=30))

    recent = await store.create_run("dcf", "MSFT")
    await store.append_event(recent.run_id, _started(recent.run_id, "MSFT"))  # type: ignore[arg-type]
    await store.update_run(recent.run_id, status="completed")
    await _set_completed_at(store, recent.run_id, now - timedelta(days=1))

    live = await store.create_run("dcf", "NVDA")
    await store.append_event(live.run_id, _started(live.run_id, "NVDA"))  # type: ignore[arg-type]

    deleted = await store.prune_run_events(retention_days=7)
    assert deleted == 2  # both of the old run's events

    # Old run's events gone, but the run row survives as history.
    assert await store.get_events_after(old.run_id) == []
    assert (await store.get_run(old.run_id)) is not None
    # Recent terminal run + still-running run keep their events.
    assert len(await store.get_events_after(recent.run_id)) == 1
    assert len(await store.get_events_after(live.run_id)) == 1

    # Idempotent — a second prune finds nothing new.
    assert await store.prune_run_events(retention_days=7) == 0


async def test_remove_artifact_links_drops_only_the_deleted_artifact(store: RunStore) -> None:
    """DELETE /api/artifacts/{id} must not leave dangling run_artifacts rows —
    and must not touch links to OTHER artifacts of the same run."""
    record = await store.create_run("dcf", "AAPL")
    await store.add_artifact(
        record.run_id, artifact_type="dcf", format="json", file_path="/api/artifacts/art_dead"
    )
    await store.add_artifact(
        record.run_id, artifact_type="comps", format="json", file_path="/api/artifacts/art_alive"
    )

    assert await store.remove_artifact_links("art_dead") == 1
    remaining = await store.list_artifacts(record.run_id)
    assert [a.file_path for a in remaining] == ["/api/artifacts/art_alive"]
    # Idempotent — nothing left to remove for that id.
    assert await store.remove_artifact_links("art_dead") == 0


async def test_prune_run_events_skips_failed_with_recent_completed_at(store: RunStore) -> None:
    """A failed run is terminal too, but only pruned once it's past retention."""
    now = datetime.now(tz=timezone.utc)
    failed = await store.create_run("dcf", "TSLA")
    await store.append_event(failed.run_id, _started(failed.run_id, "TSLA"))  # type: ignore[arg-type]
    await store.update_run(failed.run_id, status="failed", error="boom")
    await _set_completed_at(store, failed.run_id, now - timedelta(days=2))

    assert await store.prune_run_events(retention_days=7) == 0
    assert len(await store.get_events_after(failed.run_id)) == 1
