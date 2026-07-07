from datetime import datetime, timedelta, timezone

import pytest

from finrobot.engine.data.cache import (
    CANONICAL_CONTRACT_VERSION,
    DataCache,
    canonical_key,
    raw_slot_key,
)
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

        from finrobot.engine.data.cache import raw_slot_key

        old_time = (datetime.now(tz=timezone.utc) - timedelta(hours=25)).isoformat()
        async with aiosqlite.connect(cache._db_path) as conn:
            await conn.execute(
                "UPDATE cache SET cached_at = ? WHERE data_type = ? AND ticker = ?",
                (old_time, raw_slot_key("financials"), "AAPL"),
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


class TestCorruptRowSelfHeal:
    """Bug 13: a corrupt cache row used to raise (ValidationError / ValueError)
    out of get() BEFORE the DataLayer's provider loop, so the (data_type,
    ticker) slot stayed permanently broken — nothing ever overwrote it and the
    only recovery was the 30-day evict. Corrupt rows must read as a miss AND be
    physically deleted (self-heal)."""

    @staticmethod
    async def _row_count(cache: DataCache, slot_key: str, ticker: str) -> int:
        import aiosqlite

        async with aiosqlite.connect(cache._db_path) as conn:
            async with conn.execute(
                "SELECT COUNT(*) FROM cache WHERE data_type = ? AND ticker = ?",
                (slot_key, ticker),
            ) as cur:
                row = await cur.fetchone()
        return int(row[0])

    async def test_broken_json_payload_is_miss_and_deleted(self, cache):
        await cache._set_slot(raw_slot_key("financials"), "AAPL", "{truncated json")
        assert await cache.get("financials", "AAPL") is None
        assert await self._row_count(cache, raw_slot_key("financials"), "AAPL") == 0

    async def test_schema_incompatible_payload_is_miss_and_deleted(self, cache):
        """Valid JSON that no longer matches the DataResult schema (drift
        without a raw-slot version bump) is the same disease as broken JSON."""
        await cache._set_slot(raw_slot_key("financials"), "AAPL", '{"foo": 1}')
        assert await cache.get("financials", "AAPL") is None
        assert await self._row_count(cache, raw_slot_key("financials"), "AAPL") == 0

    async def test_unparseable_cached_at_is_miss_and_deleted(self, cache):
        import aiosqlite

        await cache.set("financials", "AAPL", _result())
        async with aiosqlite.connect(cache._db_path) as conn:
            await conn.execute(
                "UPDATE cache SET cached_at = 'not-a-timestamp' WHERE ticker = ?",
                ("AAPL",),
            )
            await conn.commit()
        assert await cache.get("financials", "AAPL") is None
        assert await self._row_count(cache, raw_slot_key("financials"), "AAPL") == 0

    async def test_corrupt_canonical_cached_at_is_miss_and_deleted(self, cache):
        """get_canonical shares _get_slot — the timestamp self-heal covers it too."""
        import aiosqlite

        await cache.set_canonical("financials", "AAPL", '{"any": "payload"}')
        async with aiosqlite.connect(cache._db_path) as conn:
            await conn.execute(
                "UPDATE cache SET cached_at = 'garbage' WHERE ticker = ?",
                ("AAPL",),
            )
            await conn.commit()
        assert await cache.get_canonical("financials", "AAPL") is None
        assert await self._row_count(cache, canonical_key("financials"), "AAPL") == 0

    async def test_slot_recovers_after_corruption(self, cache):
        """The whole point of self-heal: the slot works again immediately —
        a fresh set() lands in a clean row and the next get() serves it."""
        await cache._set_slot(raw_slot_key("financials"), "AAPL", "{corrupt")
        assert await cache.get("financials", "AAPL") is None
        await cache.set("financials", "AAPL", _result())
        cached = await cache.get("financials", "AAPL")
        assert cached is not None
        assert cached.data.data["revenue"] == 385_000_000_000

    async def test_corruption_is_slot_scoped(self, cache):
        """Deleting the corrupt row must not touch sibling rows (other ticker /
        other data_type)."""
        await cache.set("financials", "MSFT", _result(ticker="MSFT"))
        await cache.set("news", "AAPL", _result(data_type="news"))
        await cache._set_slot(raw_slot_key("financials"), "AAPL", "{corrupt")

        assert await cache.get("financials", "AAPL") is None
        assert (await cache.get("financials", "MSFT")) is not None
        assert (await cache.get("news", "AAPL")) is not None


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


class TestCanonicalProviderQualifiedSlot:
    """A provider swap must not overwrite/serve a different-caliber FINANCIALS
    snapshot under one key: ``canonical_key`` folds in the winning provider so
    each provider's snapshot occupies its own slot."""

    def test_provider_qualifies_the_key(self):
        bare = canonical_key("financials")
        fmp = canonical_key("financials", "fmp")
        yf = canonical_key("financials", "yfinance")
        assert fmp == f"{bare}:provider=fmp"
        assert fmp != yf != bare
        # None → unchanged bare slot (back-compat for non-provider callers).
        assert canonical_key("financials", None) == bare

    async def test_two_providers_land_in_distinct_slots(self, cache):
        await cache.set_canonical("financials", "AAPL", '{"period_basis":"ttm"}', provider="fmp")
        await cache.set_canonical(
            "financials", "AAPL", '{"period_basis":"annual"}', provider="yfinance"
        )
        fmp = await cache.get_canonical("financials", "AAPL", provider="fmp")
        yf = await cache.get_canonical("financials", "AAPL", provider="yfinance")
        assert fmp is not None and fmp.payload_json == '{"period_basis":"ttm"}'
        assert yf is not None and yf.payload_json == '{"period_basis":"annual"}'

    async def test_same_provider_reread_hits(self, cache):
        await cache.set_canonical("financials", "AAPL", '{"v":1}', provider="fmp")
        hit = await cache.get_canonical("financials", "AAPL", provider="fmp")
        assert hit is not None and hit.payload_json == '{"v":1}'

    async def test_get_latest_picks_freshest_across_providers(self, cache):
        import aiosqlite

        await cache.set_canonical("financials", "AAPL", '{"who":"fmp"}', provider="fmp")
        await cache.set_canonical("financials", "AAPL", '{"who":"yfinance"}', provider="yfinance")
        # Backdate the fmp slot so yfinance is the freshest.
        old = (datetime.now(tz=timezone.utc) - timedelta(hours=2)).isoformat()
        async with aiosqlite.connect(cache._db_path) as conn:
            await conn.execute(
                "UPDATE cache SET cached_at = ? WHERE data_type = ?",
                (old, canonical_key("financials", "fmp")),
            )
            await conn.commit()
        found = await cache.get_canonical_latest("financials", "AAPL")
        assert found is not None
        cached, provider = found
        assert provider == "yfinance"
        assert cached.payload_json == '{"who":"yfinance"}'

    async def test_get_latest_returns_none_on_true_miss(self, cache):
        assert await cache.get_canonical_latest("financials", "ZZZZ") is None

    async def test_old_unqualified_v_slot_misses_after_version_bump(self, cache):
        """A pre-fix entry written at an OLDER bare version key must not be served
        by either the provider-qualified read or the latest-scan."""
        await cache._set_slot("financials:canonical:v5", "AAPL", '{"stale":true}')
        assert await cache.get_canonical("financials", "AAPL", provider="fmp") is None
        assert await cache.get_canonical_latest("financials", "AAPL") is None


class TestRawSlotVersion:
    """Versioned raw slots auto-invalidate stale-format payloads on upgrade."""

    def test_shape_changed_raw_slots_are_versioned_others_bare(self):
        from finrobot.engine.data.cache import raw_slot_key
        from finrobot.engine.data.types import DataType

        assert raw_slot_key(DataType.PROXY_STATEMENT) == "proxy_statement:v2"
        # PEER_CANDIDATES bumped to v3 (2026-07-07): the payload now carries a top-level
        # ``active`` (isActivelyTrading) map so the peer screen can drop a delisted /
        # renamed listing (VMW, old SQ); pre-bump rows lack it and must miss + refetch.
        # (v2, 2026-06-05, added candidate profiles for the value-chain role gate.)
        assert raw_slot_key(DataType.PEER_CANDIDATES) == "peer_candidates:v3"
        # FINANCIALS bumped to v4 (2026-07-06): TTM aggregation window is now
        # cadence-aware (semi-annual reporters sum 2 half-year rows, not 4 = two
        # fiscal years); pre-bump rows carry doubled TTM and must miss + refetch.
        # (v3, 2026-06-22, added DDM seed inputs; v2, 2026-06-14, added
        # book_value_per_share.)
        assert raw_slot_key(DataType.FINANCIALS) == "financials:v4"
        # INSIDER_TRADES has no shape change → bare slot (the "others bare" case).
        assert raw_slot_key(DataType.INSIDER_TRADES) == "insider_trades"

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


class TestWriteErrorsAreNonFatal:
    """A cache WRITE is an optimization, not the deliverable — a disk-full /
    SQLITE_FULL error on it must never propagate and turn a successful provider
    fetch (or a read's corrupt-row self-heal) into a 500."""

    async def test_set_and_delete_swallow_sqlite_errors(self, cache, monkeypatch):
        import sqlite3

        conn = await cache._ensure_connection()  # build conn + table BEFORE patching

        async def boom(*args, **kwargs):
            raise sqlite3.OperationalError("database or disk is full")

        monkeypatch.setattr(conn, "execute", boom)

        # None of these write paths may raise — the fetch's real data is already
        # in hand, the cache write is best-effort.
        await cache.set("financials", "AAPL", _result())  # _set_slot
        await cache.set_canonical("financials", "AAPL", '{"ticker": "AAPL"}')  # _set_slot
        await cache._delete_slot(raw_slot_key("financials"), "AAPL")  # read self-heal write

    async def test_evict_expired_returns_zero_on_write_error(self, cache, monkeypatch):
        import sqlite3

        conn = await cache._ensure_connection()

        async def boom(*args, **kwargs):
            raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr(conn, "execute", boom)
        # Background housekeeping must not crash; it reports 0 deleted and retries.
        assert await cache.evict_expired() == 0
