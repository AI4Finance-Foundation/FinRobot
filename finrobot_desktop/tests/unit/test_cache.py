from datetime import datetime, timedelta, timezone

import pytest

from finrobot.engine.data.cache import CANONICAL_CONTRACT_VERSION, DataCache, canonical_key
from finrobot.engine.data.interface import DataResult


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
        assert cached is not None  # still returns data
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


class TestWalMode:
    async def test_wal_mode_enabled_on_first_connection(self, tmp_path):
        """WAL mode must be set so concurrent set() calls don't SQLITE_BUSY."""
        cache = DataCache(db_path=str(tmp_path / "wal_test.db"))
        await cache._ensure_connection()
        import aiosqlite

        async with aiosqlite.connect(cache._db_path) as conn:
            async with conn.execute("PRAGMA journal_mode") as cursor:
                row = await cursor.fetchone()
        await cache.close()
        assert row is not None
        assert row[0] == "wal"


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


class TestEvictExpired:
    """BUG-049: TTL only marks rows stale on read — evict_expired physically
    deletes long-stale rows so data_cache.db stops growing unbounded."""

    async def _backdate(self, cache, data_type: str, ticker: str, days: float) -> None:
        import aiosqlite

        old = (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()
        from finrobot.engine.data.cache import raw_slot_key

        async with aiosqlite.connect(cache._db_path) as conn:
            await conn.execute(
                "UPDATE cache SET cached_at = ? WHERE data_type = ? AND ticker = ?",
                (old, raw_slot_key(data_type), ticker),
            )
            await conn.commit()

    async def test_evicts_rows_past_absolute_age_cutoff(self, cache):
        await cache.set("financials", "OLD", _result("OLD"))
        await cache.set("financials", "NEW", _result("NEW"))
        await self._backdate(cache, "financials", "OLD", days=45)  # > 30d cutoff

        deleted = await cache.evict_expired()  # default 30 days
        assert deleted == 1
        assert await cache.get("financials", "OLD") is None  # physically gone
        assert await cache.get("financials", "NEW") is not None  # kept

    async def test_keeps_rows_within_cutoff_even_if_ttl_stale(self, cache):
        """A row past its 15-min PRICE TTL but younger than the eviction cutoff
        must NOT be deleted — reads still serve it (marked stale) until refetch."""
        await cache.set("price", "AAPL", _result("AAPL", "price"))
        await self._backdate(cache, "price", "AAPL", days=1)  # TTL-stale, age-fresh

        deleted = await cache.evict_expired()
        assert deleted == 0
        assert await cache.get("price", "AAPL") is not None

    async def test_custom_cutoff_enforced(self, cache):
        await cache.set("financials", "AAPL", _result("AAPL"))
        await self._backdate(cache, "financials", "AAPL", days=10)

        # 30-day default keeps it; a 7-day cutoff reaps it.
        assert await cache.evict_expired() == 0
        assert await cache.evict_expired(max_age_days=7) == 1
        assert await cache.get("financials", "AAPL") is None

    async def test_evict_on_empty_table_is_noop(self, cache):
        assert await cache.evict_expired() == 0


class TestCanonicalSlot:
    """ADR-0006: canonical (normalized) payloads live in a separate, versioned
    cache slot so they never collide with the raw provider payload for the
    same (data_type, ticker)."""

    def test_canonical_key_embeds_base_type_and_version(self):
        key = canonical_key("financials")
        assert key == f"financials:canonical:v{CANONICAL_CONTRACT_VERSION}"
        # Alias normalization still applies (FILINGS → FILINGS_10K).
        assert canonical_key("filings").startswith("filings_10k:canonical:v")

    async def test_canonical_roundtrip(self, cache):
        await cache.set_canonical("financials", "AAPL", '{"revenue": 385000000000}')
        got = await cache.get_canonical("financials", "AAPL")
        assert got is not None
        assert got.payload_json == '{"revenue": 385000000000}'
        assert got.is_stale is False

    async def test_raw_and_canonical_do_not_collide(self, cache):
        # Same (data_type, ticker) in both slots — must be independent rows.
        await cache.set("financials", "AAPL", _result("AAPL"))
        await cache.set_canonical("financials", "AAPL", '{"canonical": true}')
        raw = await cache.get("financials", "AAPL")
        canon = await cache.get_canonical("financials", "AAPL")
        assert raw is not None and raw.data.data["revenue"] == 385_000_000_000
        assert canon is not None and canon.payload_json == '{"canonical": true}'

    async def test_version_bump_misses_old_canonical_entry(self, cache):
        # Simulate a pre-bump entry by writing directly at an older-version key;
        # get_canonical (current version) must not see it.
        old_key = "financials:canonical:v0"
        await cache._set_slot(old_key, "AAPL", '{"stale": true}')
        assert await cache.get_canonical("financials", "AAPL") is None

    async def test_canonical_staleness_uses_base_type_ttl(self, cache):
        # PRICE TTL is 900s; a 1-hour-old canonical PRICE entry is stale.
        await cache.set_canonical("price", "AAPL", "{}")
        fresh = await cache.get_canonical("price", "AAPL")
        assert fresh is not None and fresh.is_stale is False
        stale = await cache.get_canonical("price", "AAPL", max_age_hours=0)
        assert stale is not None and stale.is_stale is True


class TestRawSlotVersion:
    """Versioned raw slots auto-invalidate stale-format payloads on upgrade."""

    def test_shape_changed_raw_slots_are_versioned_others_bare(self):
        from finrobot.engine.data.cache import raw_slot_key
        from finrobot.engine.data.types import DataType

        assert raw_slot_key(DataType.PROXY_STATEMENT) == "proxy_statement:v2"
        assert raw_slot_key(DataType.PEER_CANDIDATES) == "peer_candidates:v2"
        assert raw_slot_key(DataType.INSIDER_TRADES) == "insider_trades"
        assert raw_slot_key("financials") == "financials"

    async def test_old_unversioned_proxy_entry_is_not_served(self, cache):
        """A payload written under the bare 'proxy_statement' key (pre-v2) must
        read as a MISS now, forcing a refetch with the corrected text slice."""
        # Simulate a pre-upgrade entry by writing directly to the bare slot.
        await cache._set_slot(
            "proxy_statement", "NVDA", _result("NVDA", "proxy_statement").model_dump_json()
        )
        # The public get() now looks under 'proxy_statement:v2' → miss.
        assert await cache.get("proxy_statement", "NVDA") is None
        # A fresh set()/get() round-trips through the versioned slot.
        await cache.set("proxy_statement", "NVDA", _result("NVDA", "proxy_statement"))
        hit = await cache.get("proxy_statement", "NVDA")
        assert hit is not None and hit.data.ticker == "NVDA"
