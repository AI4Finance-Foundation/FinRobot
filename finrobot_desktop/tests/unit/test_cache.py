from datetime import datetime, timedelta, timezone

import pytest

from finagent.engine.data.cache import CachedResult, DataCache
from finagent.engine.data.interface import DataResult


def _result(ticker: str = "AAPL", data_type: str = "financials") -> DataResult:
    return DataResult(
        data={"revenue": 385_000_000_000},
        provider="yfinance",
        ticker=ticker,
        data_type=data_type,
        timestamp=datetime.now(tz=timezone.utc),
    )


@pytest.fixture
async def cache(tmp_path):
    return DataCache(db_path=str(tmp_path / "test_cache.db"))


class TestSetAndGet:
    async def test_set_then_get_returns_same_data(self, cache):
        r = _result()
        await cache.set("financials", "AAPL", r)
        cached = await cache.get("financials", "AAPL")
        assert cached is not None
        assert cached.data.ticker == "AAPL"
        assert cached.data.data["revenue"] == 385_000_000_000

    async def test_get_nonexistent_returns_none(self, cache):
        result = await cache.get("financials", "TSLA")
        assert result is None

    async def test_overwrite_on_set(self, cache):
        r1 = _result()
        r2 = DataResult(
            data={"revenue": 999},
            provider="yfinance",
            ticker="AAPL",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )
        await cache.set("financials", "AAPL", r1)
        await cache.set("financials", "AAPL", r2)
        cached = await cache.get("financials", "AAPL")
        assert cached.data.data["revenue"] == 999


class TestStaleness:
    async def test_fresh_data_is_not_stale(self, cache):
        await cache.set("financials", "AAPL", _result())
        cached = await cache.get("financials", "AAPL", max_age_hours=24)
        assert cached.is_stale is False

    async def test_stale_data_returns_cached_result_with_is_stale_true(self, cache, monkeypatch):
        """Simulate old cached_at by writing directly."""
        r = _result()
        await cache.set("financials", "AAPL", r)

        # Manually backdate the cached_at
        import aiosqlite
        old_time = (datetime.now(tz=timezone.utc) - timedelta(hours=25)).isoformat()
        async with aiosqlite.connect(cache._db_path) as conn:
            await conn.execute(
                "UPDATE cache SET cached_at = ? WHERE data_type = ? AND ticker = ?",
                (old_time, "financials", "AAPL"),
            )
            await conn.commit()

        cached = await cache.get("financials", "AAPL", max_age_hours=24)
        assert cached is not None          # still returns data
        assert cached.is_stale is True

    async def test_stale_data_still_returns_data(self, cache):
        """Stale data is better than no data."""
        r = _result()
        await cache.set("financials", "AAPL", r)

        import aiosqlite
        old_time = (datetime.now(tz=timezone.utc) - timedelta(hours=48)).isoformat()
        async with aiosqlite.connect(cache._db_path) as conn:
            await conn.execute(
                "UPDATE cache SET cached_at = ? WHERE data_type = ? AND ticker = ?",
                (old_time, "financials", "AAPL"),
            )
            await conn.commit()

        cached = await cache.get("financials", "AAPL", max_age_hours=24)
        assert cached.data.data["revenue"] == 385_000_000_000


class TestClear:
    async def test_clear_specific_ticker_only_clears_that_ticker(self, cache):
        await cache.set("financials", "AAPL", _result("AAPL"))
        await cache.set("financials", "TSLA", _result("TSLA"))
        await cache.clear(ticker="AAPL")
        assert await cache.get("financials", "AAPL") is None
        assert await cache.get("financials", "TSLA") is not None

    async def test_clear_all_clears_everything(self, cache):
        await cache.set("financials", "AAPL", _result("AAPL"))
        await cache.set("price", "TSLA", _result("TSLA", "price"))
        await cache.clear()
        assert await cache.get("financials", "AAPL") is None
        assert await cache.get("price", "TSLA") is None
