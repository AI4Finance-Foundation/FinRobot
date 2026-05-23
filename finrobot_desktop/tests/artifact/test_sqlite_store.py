"""Contract tests for SqliteArtifactStore.

Mirrors tests/artifact/test_store.py — SqliteArtifactStore is a drop-in
replacement for the legacy filesystem ArtifactStore. Every method should
behave identically; this file encodes the contract.

Schema notes (covered by these tests):
- Per-row secondary index on (ticker, created_at DESC) — list ordering deterministic
- ArtifactSummary.verdict is extracted at save time and stored as a column,
  so dashboard aggregations don't need to reload the full payload.
- archive_stale uses last_viewed_at falling back to created_at.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from finagent.artifact.sqlite_store import SqliteArtifactStore
from tests.artifact.conftest import _make_artifact

UTC = timezone.utc


@pytest_asyncio.fixture
async def store(tmp_path: Path) -> AsyncIterator[SqliteArtifactStore]:
    """SqliteArtifactStore bound to a per-test tmp db, closed on teardown.

    Without the explicit ``close()`` aiosqlite leaves its connection
    worker thread alive after the test's event loop tears down — pytest
    then logs a noisy ``RuntimeError: Event loop is closed`` warning per
    test. Yield-style teardown closes the connection cleanly.
    """
    s = SqliteArtifactStore(db_path=tmp_path / "artifacts.db")
    try:
        yield s
    finally:
        await s.close()


@pytest.mark.asyncio
async def test_save_then_get_roundtrip(store: SqliteArtifactStore) -> None:
    art = _make_artifact()
    await store.save(art)

    loaded = await store.get(art.id)
    assert loaded is not None
    assert loaded.id == art.id
    assert loaded.ticker == "AAPL"
    assert loaded.type == "dcf"
    assert loaded.outputs.structured["implied_price"] == pytest.approx(185.0)
    assert loaded.assumptions.parameters["wacc"] == pytest.approx(0.082)


@pytest.mark.asyncio
async def test_get_missing_returns_none(store: SqliteArtifactStore) -> None:
    assert await store.get("nope_does_not_exist") is None


@pytest.mark.asyncio
async def test_list_by_ticker_sorted_desc(store: SqliteArtifactStore) -> None:
    now = datetime.now(tz=UTC)
    a1 = _make_artifact(id="art_a1", created_at=now - timedelta(hours=2))
    a2 = _make_artifact(id="art_a2", created_at=now - timedelta(hours=1))
    a3 = _make_artifact(id="art_a3", created_at=now)
    await store.save(a1)
    await store.save(a2)
    await store.save(a3)

    summaries = await store.list_by_ticker(ticker="AAPL", limit=10)
    assert [s.id for s in summaries] == ["art_a3", "art_a2", "art_a1"]


@pytest.mark.asyncio
async def test_list_all_tickers(store: SqliteArtifactStore) -> None:
    await store.save(_make_artifact(id="art_a", ticker="AAPL"))
    await store.save(_make_artifact(id="art_m", ticker="MSFT"))
    summaries = await store.list_by_ticker(ticker=None, limit=10)
    tickers = {s.ticker for s in summaries}
    assert tickers == {"AAPL", "MSFT"}


@pytest.mark.asyncio
async def test_list_filters_archived(store: SqliteArtifactStore) -> None:
    a = _make_artifact(id="art_archived")
    a.meta.archived = True
    await store.save(a)
    await store.save(_make_artifact(id="art_live"))
    visible = await store.list_by_ticker(ticker="AAPL")
    assert {s.id for s in visible} == {"art_live"}
    with_archived = await store.list_by_ticker(ticker="AAPL", include_archived=True)
    assert {s.id for s in with_archived} == {"art_archived", "art_live"}


@pytest.mark.asyncio
async def test_list_filters_by_type(store: SqliteArtifactStore) -> None:
    await store.save(_make_artifact(id="art_d", type="dcf"))
    await store.save(_make_artifact(id="art_l", type="lbo"))
    only_dcf = await store.list_by_ticker(ticker="AAPL", type="dcf")
    assert {s.id for s in only_dcf} == {"art_d"}


@pytest.mark.asyncio
async def test_delete_then_get_is_none(store: SqliteArtifactStore) -> None:
    art = _make_artifact()
    await store.save(art)
    assert await store.delete(art.id) is True
    assert await store.get(art.id) is None
    assert await store.delete(art.id) is False  # second delete = miss


@pytest.mark.asyncio
async def test_cross_ticker_artifact(store: SqliteArtifactStore) -> None:
    """ticker=None artifacts live in the same table, identified by NULL."""
    art = _make_artifact(id="art_cross", ticker=None)
    art.cross_tickers = ["AAPL", "MSFT"]
    await store.save(art)
    loaded = await store.get("art_cross")
    assert loaded is not None
    assert loaded.ticker is None
    assert loaded.cross_tickers == ["AAPL", "MSFT"]
    # list_by_ticker(None) returns it
    summaries = await store.list_by_ticker(ticker=None)
    assert any(s.id == "art_cross" for s in summaries)


@pytest.mark.asyncio
async def test_summary_has_verdict_from_artifact(store: SqliteArtifactStore) -> None:
    """ArtifactSummary.verdict must be populated at save time so dashboard
    aggregations don't N+1 the full artifact for the verdict field."""
    art = _make_artifact()
    art.outputs.structured["thesis"] = {
        "recommendation": "BUY",
        "price_target": 250.0,
    }
    await store.save(art)
    summaries = await store.list_by_ticker(ticker="AAPL")
    assert summaries[0].verdict == "BUY"
    assert summaries[0].target_price == pytest.approx(250.0)


@pytest.mark.asyncio
async def test_mark_viewed_unarchives(store: SqliteArtifactStore) -> None:
    art = _make_artifact()
    art.meta.archived = True
    await store.save(art)
    # Sanity: archived hidden
    assert await store.list_by_ticker(ticker="AAPL") == []
    await store.mark_viewed(art.id)
    summaries = await store.list_by_ticker(ticker="AAPL")
    assert any(s.id == art.id for s in summaries)


@pytest.mark.asyncio
async def test_archive_stale_marks_old(store: SqliteArtifactStore) -> None:
    now = datetime.now(tz=UTC)
    old = _make_artifact(id="art_old", created_at=now - timedelta(hours=48))
    fresh = _make_artifact(id="art_fresh", created_at=now)
    await store.save(old)
    await store.save(fresh)
    archived = await store.archive_stale(hours=24)
    assert archived == 1
    visible_ids = {s.id for s in await store.list_by_ticker(ticker="AAPL")}
    assert "art_fresh" in visible_ids
    assert "art_old" not in visible_ids  # now archived


@pytest.mark.asyncio
async def test_rebuild_summaries_is_noop(store: SqliteArtifactStore) -> None:
    """rebuild_summaries should be a no-op now that summaries are columns —
    there is no separate index.json that can drift."""
    await store.save(_make_artifact())
    rewritten = await store.rebuild_summaries()
    assert rewritten == 0


@pytest.mark.asyncio
async def test_save_is_upsert_on_id_conflict(store: SqliteArtifactStore) -> None:
    """Re-saving the same id replaces the row (one-version-per-id contract)."""
    art = _make_artifact()
    await store.save(art)
    art.outputs.structured["implied_price"] = 999.0
    await store.save(art)
    loaded = await store.get(art.id)
    assert loaded is not None
    assert loaded.outputs.structured["implied_price"] == pytest.approx(999.0)
    # Still only one row
    summaries = await store.list_by_ticker(ticker="AAPL")
    assert len(summaries) == 1
