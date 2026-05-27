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
    count = await cache_mod.bulk_upsert_holdings([
        _row(holder_name="Bridgewater", holder_cik="A", shares=30_000_000, value_usd=5.5e9),
        _row(holder_name="Renaissance", holder_cik="B", shares=22_000_000, value_usd=4.0e9),
        _row(holder_name="Citadel",     holder_cik="C", shares=18_000_000, value_usd=3.3e9),
    ])
    assert count == 3
    rows = await cache_mod.lookup_holders_for_ticker("NVDA")
    assert len(rows) == 3
    # Sorted by value_usd DESC
    assert [r["holder_name"] for r in rows] == ["Bridgewater", "Renaissance", "Citadel"]
    assert rows[0]["shares"] == 30_000_000


@pytest.mark.asyncio
async def test_lookup_falls_back_to_most_recent_period(_isolated_cache) -> None:  # type: ignore[no-untyped-def]
    """When period_end is None, return rows from the latest period present."""
    await cache_mod.bulk_upsert_holdings([
        _row(holder_cik="A", period_end=date(2025, 12, 31), shares=10, value_usd=100.0),
        _row(holder_cik="A", period_end=date(2026, 3, 31),  shares=20, value_usd=200.0),
        _row(holder_cik="B", period_end=date(2026, 3, 31),  shares=30, value_usd=300.0),
    ])
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

    await cache_mod.bulk_upsert_holdings([
        _row(ticker="NVDA", holder_cik="A", shares=10, value_usd=100.0),
        _row(ticker="AAPL", holder_cik="A", shares=20, value_usd=200.0, cusip="037833100", name_of_issuer="APPLE INC"),
    ])
    status1 = await cache_mod.cache_status()
    assert status1["populated"] is True
    assert status1["row_count"] == 2
    assert status1["distinct_tickers"] == 2
    assert status1["latest_period_end"] is not None


@pytest.mark.asyncio
async def test_lookup_uses_issuer_name_when_ticker_unresolved(_isolated_cache) -> None:  # type: ignore[no-untyped-def]
    """13F rows are still queryable when refresh cannot license a CUSIP→ticker map."""
    await cache_mod.bulk_upsert_holdings([
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
    ])

    rows = await cache_mod.lookup_holders_for_ticker(
        "NVDA",
        issuer_name="NVIDIA Corporation",
    )

    assert len(rows) == 1
    assert rows[0]["holder_name"] == "Bridgewater"
    assert rows[0]["name_of_issuer"] == "NVIDIA CORP"
