"""QuoteCache — L1 in-memory TTL + L2 SQLite-backed quotes_cache table.

Why two layers?
  L1 keeps hot-path latency near zero (no IO when warm)
  L2 survives process restarts (e.g. Tauri shell reopen)
  Both share a configurable TTL; per-ticker None failures are also cached
  so we don't beat yfinance for a delisted symbol.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from finagent.engine.data.quote_cache import QuoteCache


@pytest.mark.asyncio
async def test_cold_miss_calls_fetcher(tmp_path: Path) -> None:
    cache = QuoteCache(db_path=tmp_path / "q.db", ttl_seconds=60)
    calls: list[str] = []

    async def fake_fetch(missing: list[str]) -> dict[str, float | None]:
        calls.extend(missing)
        return {t: 100.0 for t in missing}

    result = await cache.get_batch(["AAPL", "MSFT"], fetcher=fake_fetch)
    assert result == {"AAPL": 100.0, "MSFT": 100.0}
    assert sorted(calls) == ["AAPL", "MSFT"]
    await cache.close()


@pytest.mark.asyncio
async def test_l1_hit_skips_fetcher(tmp_path: Path) -> None:
    cache = QuoteCache(db_path=tmp_path / "q.db", ttl_seconds=60)
    calls: list[str] = []

    async def fake_fetch(missing: list[str]) -> dict[str, float | None]:
        calls.extend(missing)
        return {t: 100.0 for t in missing}

    await cache.get_batch(["AAPL"], fetcher=fake_fetch)
    calls.clear()
    result = await cache.get_batch(["AAPL"], fetcher=fake_fetch)
    assert result == {"AAPL": 100.0}
    assert calls == []  # L1 served it
    await cache.close()


@pytest.mark.asyncio
async def test_l2_hit_after_process_restart(tmp_path: Path) -> None:
    """Recreating QuoteCache wipes L1 but the SQLite L2 still serves."""
    db = tmp_path / "q.db"

    async def first_fetch(missing: list[str]) -> dict[str, float | None]:
        return {t: 100.0 for t in missing}

    cache1 = QuoteCache(db_path=db, ttl_seconds=60)
    await cache1.get_batch(["AAPL"], fetcher=first_fetch)
    await cache1.close()

    cache2 = QuoteCache(db_path=db, ttl_seconds=60)
    calls: list[str] = []

    async def should_not_be_called(missing: list[str]) -> dict[str, float | None]:
        calls.extend(missing)
        return {t: 999.0 for t in missing}

    result = await cache2.get_batch(["AAPL"], fetcher=should_not_be_called)
    assert result == {"AAPL": 100.0}
    assert calls == []
    await cache2.close()


@pytest.mark.asyncio
async def test_ttl_expiry_forces_refetch(tmp_path: Path) -> None:
    cache = QuoteCache(db_path=tmp_path / "q.db", ttl_seconds=0)
    calls: list[str] = []

    async def fake_fetch(missing: list[str]) -> dict[str, float | None]:
        calls.extend(missing)
        return {t: 100.0 for t in missing}

    await cache.get_batch(["AAPL"], fetcher=fake_fetch)
    await asyncio.sleep(0.01)
    await cache.get_batch(["AAPL"], fetcher=fake_fetch)
    assert calls == ["AAPL", "AAPL"]
    await cache.close()


@pytest.mark.asyncio
async def test_partial_batch_only_fetches_misses(tmp_path: Path) -> None:
    """If AAPL is warm but MSFT is not, only MSFT is passed to fetcher."""
    cache = QuoteCache(db_path=tmp_path / "q.db", ttl_seconds=60)

    async def first(missing: list[str]) -> dict[str, float | None]:
        return {t: 100.0 for t in missing}

    await cache.get_batch(["AAPL"], fetcher=first)
    fetched: list[str] = []

    async def second(missing: list[str]) -> dict[str, float | None]:
        fetched.extend(missing)
        return {t: 200.0 for t in missing}

    result = await cache.get_batch(["AAPL", "MSFT"], fetcher=second)
    assert result == {"AAPL": 100.0, "MSFT": 200.0}
    assert fetched == ["MSFT"]
    await cache.close()


@pytest.mark.asyncio
async def test_none_quote_is_cached(tmp_path: Path) -> None:
    """Failed fetches (None) must be cached so we don't beat yfinance on
    every refresh for a delisted symbol."""
    cache = QuoteCache(db_path=tmp_path / "q.db", ttl_seconds=60)
    calls: list[str] = []

    async def fake_fetch(missing: list[str]) -> dict[str, float | None]:
        calls.extend(missing)
        return dict.fromkeys(missing)

    await cache.get_batch(["DELISTED"], fetcher=fake_fetch)
    calls.clear()
    result = await cache.get_batch(["DELISTED"], fetcher=fake_fetch)
    assert result == {"DELISTED": None}
    assert calls == []
    await cache.close()


@pytest.mark.asyncio
async def test_empty_input_returns_empty(tmp_path: Path) -> None:
    cache = QuoteCache(db_path=tmp_path / "q.db", ttl_seconds=60)

    async def fail_if_called(missing: list[str]) -> dict[str, float | None]:
        raise AssertionError("fetcher should not be called for empty input")

    result = await cache.get_batch([], fetcher=fail_if_called)
    assert result == {}
    await cache.close()
