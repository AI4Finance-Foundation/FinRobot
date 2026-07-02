"""sec_holdings_cache — schema + lookup + upsert sanity tests.

Out of scope: refresh script's edgartools-side normalisation (covered by
scripts/refresh_sec_holdings.py its own integration test). Here we only
verify the SQLite layer behaves as the public API contract says.
"""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import pytest

from finrobot import paths as _paths
from finrobot.engine.data import sec_holdings_cache as cache_mod


@pytest.fixture
def _isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test gets its own SQLite file + a fresh singleton."""
    monkeypatch.setattr(_paths, "SEC_HOLDINGS_DB", tmp_path / "sec_holdings.db")
    cache_mod.reset_singleton_sync()
    yield
    asyncio.run(cache_mod.close_singleton())


def _row(**overrides):  # type: ignore[no-untyped-def]
    base = {
        "ticker": "NVDA",
        "cusip": "67066G104",
        "name_of_issuer": "NVIDIA CORP",
        "title_of_class": "COM",
        "holder_name": "Bridgewater Associates LP",
        "holder_cik": "1350694",
        "shares": 30_000_000,
        "value_usd": 5_500_000_000.0,
        "period_end": date(2026, 3, 31),
        "filing_date": date(2026, 5, 15),
        "accession_no": "0001350694-26-000001",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_lookup_empty_when_cache_unbuilt(_isolated_cache) -> None:  # type: ignore[no-untyped-def]
    """Caller MUST get an empty list (not an error) when no refresh has run."""
    rows = await cache_mod.lookup_holders_for_ticker("NVDA")
    assert rows == []


@pytest.mark.asyncio
async def test_bulk_upsert_then_lookup_roundtrip(_isolated_cache) -> None:  # type: ignore[no-untyped-def]
    count = await cache_mod.bulk_upsert_holdings(
        [
            _row(holder_name="Bridgewater", holder_cik="A", shares=30_000_000, value_usd=5.5e9),
            _row(holder_name="Renaissance", holder_cik="B", shares=22_000_000, value_usd=4.0e9),
            _row(holder_name="Citadel", holder_cik="C", shares=18_000_000, value_usd=3.3e9),
        ]
    )
    assert count == 3
    rows = await cache_mod.lookup_holders_for_ticker("NVDA")
    assert len(rows) == 3
    # Sorted by value_usd DESC
    assert [r["holder_name"] for r in rows] == ["Bridgewater", "Renaissance", "Citadel"]
    assert rows[0]["shares"] == 30_000_000


@pytest.mark.asyncio
async def test_lookup_falls_back_to_most_recent_period(_isolated_cache) -> None:  # type: ignore[no-untyped-def]
    """When period_end is None, return rows from the latest period present."""
    await cache_mod.bulk_upsert_holdings(
        [
            _row(holder_cik="A", period_end=date(2025, 12, 31), shares=10, value_usd=100.0),
            _row(holder_cik="A", period_end=date(2026, 3, 31), shares=20, value_usd=200.0),
            _row(holder_cik="B", period_end=date(2026, 3, 31), shares=30, value_usd=300.0),
        ]
    )
    rows = await cache_mod.lookup_holders_for_ticker("NVDA")  # latest = 2026-03-31
    assert len(rows) == 2
    assert all(r["period_end"] == "2026-03-31" for r in rows)


@pytest.mark.asyncio
async def test_upsert_updates_existing_row_not_inserts_dup(_isolated_cache) -> None:  # type: ignore[no-untyped-def]
    """Same (cusip, holder_cik, period_end, title_of_class) → UPSERT not INSERT."""
    await cache_mod.bulk_upsert_holdings([_row(shares=100, value_usd=1_000.0)])
    await cache_mod.bulk_upsert_holdings([_row(shares=200, value_usd=2_000.0)])
    rows = await cache_mod.lookup_holders_for_ticker("NVDA")
    assert len(rows) == 1
    assert rows[0]["shares"] == 200
    assert rows[0]["value_usd"] == 2_000.0


@pytest.mark.asyncio
async def test_limit_caps_result(_isolated_cache) -> None:  # type: ignore[no-untyped-def]
    rows = [_row(holder_cik=str(i), value_usd=float(i * 10)) for i in range(30)]
    await cache_mod.bulk_upsert_holdings(rows)
    out = await cache_mod.lookup_holders_for_ticker("NVDA", limit=10)
    assert len(out) == 10
    # Returned top-10 by value
    assert out[0]["value_usd"] == 290.0  # 29 * 10
    assert out[-1]["value_usd"] == 200.0  # 20 * 10


@pytest.mark.asyncio
async def test_cache_status_empty_then_populated(_isolated_cache) -> None:  # type: ignore[no-untyped-def]
    status0 = await cache_mod.cache_status()
    assert status0["populated"] is False
    assert status0["row_count"] == 0

    await cache_mod.bulk_upsert_holdings(
        [
            _row(ticker="NVDA", holder_cik="A", shares=10, value_usd=100.0),
            _row(
                ticker="AAPL",
                holder_cik="A",
                shares=20,
                value_usd=200.0,
                cusip="037833100",
                name_of_issuer="APPLE INC",
            ),
        ]
    )
    status1 = await cache_mod.cache_status()
    assert status1["populated"] is True
    assert status1["row_count"] == 2
    assert status1["distinct_tickers"] == 2
    assert status1["latest_period_end"] is not None


def test_expected_latest_period_end_deadline_boundaries() -> None:
    """13F-HR is due within 45 days after quarter end (SEC rule 13f-1(a)).

    A quarter only becomes "expected in cache" the day AFTER its deadline —
    flagging stale on the deadline day itself would false-positive while
    filings are still legally trickling in.
    """
    # Q1 2026 ends 2026-03-31 → deadline 2026-05-15.
    assert cache_mod.expected_latest_period_end(date(2026, 6, 10)) == date(2026, 3, 31)
    assert cache_mod.expected_latest_period_end(date(2026, 5, 16)) == date(2026, 3, 31)
    # On the deadline day the previous quarter is still the expectation.
    assert cache_mod.expected_latest_period_end(date(2026, 5, 15)) == date(2025, 12, 31)
    # Q4 2025 ends 2025-12-31 → deadline 2026-02-14 (year boundary).
    assert cache_mod.expected_latest_period_end(date(2026, 2, 15)) == date(2025, 12, 31)
    assert cache_mod.expected_latest_period_end(date(2026, 2, 14)) == date(2025, 9, 30)
    assert cache_mod.expected_latest_period_end(date(2026, 1, 5)) == date(2025, 9, 30)
    # Exactly on a quarter end: that quarter's deadline hasn't even started.
    assert cache_mod.expected_latest_period_end(date(2026, 3, 31)) == date(2025, 12, 31)


@pytest.mark.asyncio
async def test_cache_status_stale_flag(_isolated_cache) -> None:  # type: ignore[no-untyped-def]
    """Stale = populated AND latest cached quarter predates the expected one."""
    status_empty = await cache_mod.cache_status()
    assert status_empty["stale"] is False  # unpopulated has its own warning path
    assert status_empty["expected_period_end"] is not None

    # An ancient quarter is stale no matter what today is.
    await cache_mod.bulk_upsert_holdings([_row(holder_cik="A", period_end=date(1999, 12, 31))])
    status_old = await cache_mod.cache_status()
    assert status_old["stale"] is True

    # A quarter matching the current expectation is fresh.
    expected = cache_mod.expected_latest_period_end(date.today())
    await cache_mod.bulk_upsert_holdings([_row(holder_cik="B", period_end=expected)])
    status_fresh = await cache_mod.cache_status()
    assert status_fresh["stale"] is False
    assert status_fresh["expected_period_end"] == expected.isoformat()


@pytest.mark.asyncio
async def test_lookup_uses_issuer_name_when_ticker_unresolved(_isolated_cache) -> None:  # type: ignore[no-untyped-def]
    """13F rows are still queryable when refresh cannot license a CUSIP→ticker map."""
    await cache_mod.bulk_upsert_holdings(
        [
            _row(
                ticker=None,
                name_of_issuer="NVIDIA CORP",
                holder_name="Bridgewater",
                holder_cik="A",
                shares=30_000_000,
                value_usd=5.5e9,
            ),
            _row(
                ticker=None,
                cusip="037833100",
                name_of_issuer="APPLE INC",
                holder_name="Berkshire",
                holder_cik="B",
                shares=10_000_000,
                value_usd=1.8e9,
            ),
        ]
    )

    rows = await cache_mod.lookup_holders_for_ticker(
        "NVDA",
        issuer_name="NVIDIA Corporation",
    )

    assert len(rows) == 1
    assert rows[0]["holder_name"] == "Bridgewater"
    assert rows[0]["name_of_issuer"] == "NVIDIA CORP"


def test_ephemeral_connection_survives_sequential_asyncio_run_loops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BUG-082 sibling: EdgarProvider._fetch_13f_sync runs each 13F fetch in a
    BRAND-NEW asyncio.run loop (inside asyncio.to_thread). Sharing the global
    singleton across those loop islands is a time bomb (probed on aiosqlite
    0.22.1): any in-flight future whose loop dies first makes the worker's
    call_soon_threadsafe raise, which kills the worker thread and bricks the
    connection for EVERY later caller — including the server's main loop.
    The 13F path must therefore never touch the singleton: each island scopes
    its I/O to an ephemeral open-use-close connection. wait_for(5s) turns a
    regression into a fast failure instead of a hung CI."""
    monkeypatch.setattr(_paths, "SEC_HOLDINGS_DB", tmp_path / "sec_holdings.db")
    cache_mod.reset_singleton_sync()

    async def _island() -> tuple[list[dict], dict]:
        async def _go() -> tuple[list[dict], dict]:
            async with cache_mod.ephemeral_connection() as conn:
                holders = await cache_mod.lookup_holders_for_ticker("NVDA", conn=conn)
                status = await cache_mod.cache_status(conn=conn)
            return holders, status

        return await asyncio.wait_for(_go(), timeout=5)

    try:
        # Bind the singleton to loop #1 via the main-path write API; loop #1
        # dies when run() returns — the exact state the server is in when a
        # 13F island starts.
        async def _bind_singleton_then_seed() -> None:
            await asyncio.wait_for(cache_mod.bulk_upsert_holdings([_row()]), timeout=5)

        asyncio.run(_bind_singleton_then_seed())

        # Two sequential islands — the production cadence (one per 13F fetch).
        holders_1, status_1 = asyncio.run(_island())
        holders_2, status_2 = asyncio.run(_island())

        assert holders_1 == holders_2
        assert holders_1[0]["holder_name"] == "Bridgewater Associates LP"
        assert status_1["populated"] is True and status_2["populated"] is True
    finally:
        # Close the singleton for real: its worker thread is NON-daemon, so a
        # merely-dropped reference (reset_singleton_sync) blocks interpreter
        # exit forever on SimpleQueue.get() — pytest would hang after green.
        asyncio.run(asyncio.wait_for(cache_mod.close_singleton(), timeout=5))


@pytest.mark.asyncio
async def test_qoq_change_computed_across_two_quarters(_isolated_cache) -> None:  # type: ignore[no-untyped-def]
    """shares_change_pct is the QoQ delta vs the immediately-prior cached quarter,
    keyed on (holder_cik, title_of_class). A holder present in both quarters gets a
    real %; a NEW holder (absent last quarter) stays None (never +∞)."""
    await cache_mod.bulk_upsert_holdings(
        [
            _row(holder_cik="A", period_end=date(2025, 12, 31), shares=10, value_usd=100.0),
            _row(holder_cik="A", period_end=date(2026, 3, 31), shares=20, value_usd=200.0),
            _row(holder_cik="B", period_end=date(2026, 3, 31), shares=30, value_usd=300.0),
        ]
    )
    rows = await cache_mod.lookup_holders_for_ticker("NVDA")  # latest = 2026-03-31
    by_cik = {r["holder_cik"]: r for r in rows}
    # A: 10 → 20 = +100%
    assert by_cik["A"]["shares_change_pct"] == 100.0
    # B: new position this quarter → None, not a fabricated 0 or +∞
    assert by_cik["B"]["shares_change_pct"] is None


@pytest.mark.asyncio
async def test_qoq_change_none_with_single_quarter(_isolated_cache) -> None:  # type: ignore[no-untyped-def]
    """A fresh cache holds one quarter — QoQ has nothing to diff against, so the
    column stays None (renders '—'), never a fabricated 0. This is why the column
    was a permanent dead '—': the diff was never computed AND only one quarter is
    ever cached today; it lights up automatically once ≥2 quarters land."""
    await cache_mod.bulk_upsert_holdings(
        [_row(holder_cik="A", period_end=date(2026, 3, 31), shares=20, value_usd=200.0)]
    )
    rows = await cache_mod.lookup_holders_for_ticker("NVDA")
    assert rows[0]["shares_change_pct"] is None


@pytest.mark.asyncio
async def test_completion_marker_roundtrip(_isolated_cache) -> None:  # type: ignore[no-untyped-def]
    """A quarter is 'complete' only once its refresh finished and set the marker.
    Rows present without a marker = an interrupted/capped run → NOT complete, so the
    freshness guard re-fetches instead of freezing a partial cache (missing BlackRock
    / early Vanguard filers)."""
    await cache_mod.bulk_upsert_holdings([_row(period_end=date(2026, 3, 31))])
    # Rows exist, but no completion marker yet → treated as incomplete (partial run).
    assert await cache_mod.is_period_complete(date(2026, 3, 31)) is False
    await cache_mod.mark_period_complete(date(2026, 3, 31), filings_processed=6200)
    assert await cache_mod.is_period_complete(date(2026, 3, 31)) is True
    # A different, unmarked quarter stays incomplete.
    assert await cache_mod.is_period_complete("2025-12-31") is False
