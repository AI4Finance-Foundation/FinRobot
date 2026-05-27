"""Regression for the cache-stampede lock leak.

`finrobot.engine.data.cache._INFLIGHT_LOCKS` switched from a plain dict to
a WeakValueDictionary so each lock garbage-collects as soon as no
`async with` block still references it. Without this, the module would
accumulate one lock per (data_type, ticker) for the lifetime of the
process — fine for a single desktop user but unbounded for team-share
deployments where every studied ticker leaves a permanent entry.

This test mounts a tiny cache, runs a fetch through `cached_fetch`,
drops the local reference, forces GC, and asserts the dictionary
shrunk back to 0 entries.
"""

from __future__ import annotations

import gc
from pathlib import Path

import pytest

from finrobot.engine.data.cache import DataCache, _INFLIGHT_LOCKS, cached_fetch
from finrobot.engine.data.types import DataType


@pytest.mark.asyncio
async def test_inflight_lock_gc_after_fetch(tmp_path: Path) -> None:
    """After cached_fetch returns and locals are dropped, GC should clear the entry."""
    db_path = tmp_path / "cache.db"
    cache = DataCache(str(db_path))

    async def fetcher() -> dict[str, object]:
        return {"value": 42}

    # Drain any pre-existing entries left by other tests so we have a clean baseline.
    _INFLIGHT_LOCKS.clear()
    gc.collect()
    assert len(_INFLIGHT_LOCKS) == 0

    result = await cached_fetch(cache, DataType.PRICE, "AAPL", fetcher)
    assert result == {"value": 42}

    # While `cached_fetch` was running it held a strong reference to the
    # lock. Now that the call returned, no strong reference remains; the
    # WeakValueDictionary entry should disappear after a GC pass.
    gc.collect()
    assert len(_INFLIGHT_LOCKS) == 0, (
        "_INFLIGHT_LOCKS leaked an entry — a strong reference is keeping the "
        "lock alive somewhere; check that no module-level code captures the "
        "lock returned by _get_inflight_lock."
    )

    await cache.close()


@pytest.mark.asyncio
async def test_inflight_lock_serializes_concurrent_cold_fetches(tmp_path: Path) -> None:
    """Two concurrent cache-misses for the same key must collapse to one fetch."""
    import asyncio

    db_path = tmp_path / "cache.db"
    cache = DataCache(str(db_path))
    fetch_count = 0

    async def slow_fetcher() -> dict[str, object]:
        nonlocal fetch_count
        fetch_count += 1
        await asyncio.sleep(0.05)
        return {"value": fetch_count}

    _INFLIGHT_LOCKS.clear()
    gc.collect()

    # Two parallel cold fetches → second one must wait for first + read from cache.
    a, b = await asyncio.gather(
        cached_fetch(cache, DataType.PRICE, "AAPL", slow_fetcher),
        cached_fetch(cache, DataType.PRICE, "AAPL", slow_fetcher),
    )
    assert fetch_count == 1
    assert a == {"value": 1}
    assert b == {"value": 1}

    gc.collect()
    assert len(_INFLIGHT_LOCKS) == 0

    await cache.close()
