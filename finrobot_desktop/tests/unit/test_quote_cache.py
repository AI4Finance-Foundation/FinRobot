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

from finrobot.engine.data.quote_cache import Quote, QuoteCache, QuoteFetchRateLimited


@pytest.mark.asyncio
async def test_cold_miss_calls_fetcher(tmp_path: Path) -> None:
    cache = QuoteCache(db_path=tmp_path / "q.db", ttl_seconds=60)
    calls: list[str] = []

    async def fake_fetch(missing: list[str]) -> dict[str, Quote | None]:
        calls.extend(missing)
        return {t: Quote(price=100.0) for t in missing}

    result = await cache.get_batch(["AAPL", "MSFT"], fetcher=fake_fetch)
    assert result == {"AAPL": Quote(price=100.0), "MSFT": Quote(price=100.0)}
    assert sorted(calls) == ["AAPL", "MSFT"]
    await cache.close()


@pytest.mark.asyncio
async def test_l1_hit_skips_fetcher(tmp_path: Path) -> None:
    cache = QuoteCache(db_path=tmp_path / "q.db", ttl_seconds=60)
    calls: list[str] = []

    async def fake_fetch(missing: list[str]) -> dict[str, Quote | None]:
        calls.extend(missing)
        return {t: Quote(price=100.0) for t in missing}

    await cache.get_batch(["AAPL"], fetcher=fake_fetch)
    calls.clear()
    result = await cache.get_batch(["AAPL"], fetcher=fake_fetch)
    assert result == {"AAPL": Quote(price=100.0)}
    assert calls == []  # L1 served it
    await cache.close()


@pytest.mark.asyncio
async def test_legacy_v1_rows_ignored_after_schema_bump(tmp_path: Path) -> None:
    """Schema v2 added a ``currency`` column → the value shape changed, so the
    cache reads only ``quotes_cache_v2``. A pre-existing v1 ``quotes_cache``
    (price-only) row must NOT deserialize-crash and must NOT be served as a USD
    quote: the new code never reads v1, so the ticker re-fetches cleanly into v2,
    and the legacy table is dropped on connect."""
    import sqlite3

    db = tmp_path / "q.db"
    # Seed a legacy v1 table the way the old code wrote it (no currency column).
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE quotes_cache (ticker TEXT PRIMARY KEY, last_price REAL, fetched_at REAL NOT NULL)"
    )
    conn.execute(
        "INSERT INTO quotes_cache (ticker, last_price, fetched_at) VALUES (?, ?, ?)",
        ("2330.TW", 640.0, 9_999_999_999.0),  # far-future fetched_at → would read "fresh"
    )
    conn.commit()
    conn.close()

    cache = QuoteCache(db_path=db, ttl_seconds=60)
    calls: list[str] = []

    async def fetch(missing: list[str]) -> dict[str, Quote | None]:
        calls.extend(missing)
        return {t: Quote(price=20.0, currency="USD") for t in missing}

    # The v1 row is invisible to v2 reads → a real fetch runs (no stale 640.0 leak).
    result = await cache.get_batch(["2330.TW"], fetcher=fetch)
    assert result == {"2330.TW": Quote(price=20.0, currency="USD")}
    assert calls == ["2330.TW"], "v1 row must not have masked the v2 fetch"

    # Legacy table was dropped on connect.
    conn2 = sqlite3.connect(db)
    tables = {r[0] for r in conn2.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn2.close()
    assert "quotes_cache" not in tables
    assert "quotes_cache_v2" in tables
    await cache.close()


@pytest.mark.asyncio
async def test_l2_hit_after_process_restart(tmp_path: Path) -> None:
    """Recreating QuoteCache wipes L1 but the SQLite L2 still serves."""
    db = tmp_path / "q.db"

    async def first_fetch(missing: list[str]) -> dict[str, Quote | None]:
        return {t: Quote(price=100.0) for t in missing}

    cache1 = QuoteCache(db_path=db, ttl_seconds=60)
    await cache1.get_batch(["AAPL"], fetcher=first_fetch)
    await cache1.close()

    cache2 = QuoteCache(db_path=db, ttl_seconds=60)
    calls: list[str] = []

    async def should_not_be_called(missing: list[str]) -> dict[str, Quote | None]:
        calls.extend(missing)
        return {t: Quote(price=999.0) for t in missing}

    result = await cache2.get_batch(["AAPL"], fetcher=should_not_be_called)
    assert result == {"AAPL": Quote(price=100.0)}
    assert calls == []
    await cache2.close()


@pytest.mark.asyncio
async def test_ttl_expiry_forces_refetch(tmp_path: Path) -> None:
    cache = QuoteCache(db_path=tmp_path / "q.db", ttl_seconds=0)
    calls: list[str] = []

    async def fake_fetch(missing: list[str]) -> dict[str, Quote | None]:
        calls.extend(missing)
        return {t: Quote(price=100.0) for t in missing}

    await cache.get_batch(["AAPL"], fetcher=fake_fetch)
    await asyncio.sleep(0.01)
    await cache.get_batch(["AAPL"], fetcher=fake_fetch)
    assert calls == ["AAPL", "AAPL"]
    await cache.close()


@pytest.mark.asyncio
async def test_partial_batch_only_fetches_misses(tmp_path: Path) -> None:
    """If AAPL is warm but MSFT is not, only MSFT is passed to fetcher."""
    cache = QuoteCache(db_path=tmp_path / "q.db", ttl_seconds=60)

    async def first(missing: list[str]) -> dict[str, Quote | None]:
        return {t: Quote(price=100.0) for t in missing}

    await cache.get_batch(["AAPL"], fetcher=first)
    fetched: list[str] = []

    async def second(missing: list[str]) -> dict[str, Quote | None]:
        fetched.extend(missing)
        return {t: Quote(price=200.0) for t in missing}

    result = await cache.get_batch(["AAPL", "MSFT"], fetcher=second)
    assert result == {"AAPL": Quote(price=100.0), "MSFT": Quote(price=200.0)}
    assert fetched == ["MSFT"]
    await cache.close()


@pytest.mark.asyncio
async def test_none_quote_is_cached(tmp_path: Path) -> None:
    """Failed fetches (None) must be cached so we don't beat yfinance on
    every refresh for a delisted symbol."""
    cache = QuoteCache(db_path=tmp_path / "q.db", ttl_seconds=60)
    calls: list[str] = []

    async def fake_fetch(missing: list[str]) -> dict[str, Quote | None]:
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

    async def fail_if_called(missing: list[str]) -> dict[str, Quote | None]:
        raise AssertionError("fetcher should not be called for empty input")

    result = await cache.get_batch([], fetcher=fail_if_called)
    assert result == {}
    await cache.close()


@pytest.mark.asyncio
async def test_rate_limit_preserves_stale_l2_value(tmp_path: Path) -> None:
    """Upstream 429 must NOT overwrite a previously cached quote with None.

    Repro of the live yfinance rate-limit bug: warm cache → TTL expires
    → next fetch hits 429 → previously the cache wrote None across L1/L2
    for the full TTL, taking the landing dashboard cold even after Yahoo
    recovered. Now QuoteFetchRateLimited returns the stale row instead.
    """
    # cooldown=0 isolates the stale-preservation invariant from the cooldown
    # feature (exercised separately below).
    cache = QuoteCache(db_path=tmp_path / "q.db", ttl_seconds=0, rate_limit_cooldown_seconds=0)

    async def first(missing: list[str]) -> dict[str, Quote | None]:
        return {t: Quote(price=150.0) for t in missing}

    # Warm L2 with a value.
    await cache.get_batch(["AAPL"], fetcher=first)
    await asyncio.sleep(0.01)  # TTL expired

    async def rate_limited(missing: list[str]) -> dict[str, Quote | None]:
        raise QuoteFetchRateLimited("Yahoo 429")

    result = await cache.get_batch(["AAPL"], fetcher=rate_limited)
    assert result == {"AAPL": Quote(price=150.0)}, "must return stale L2 value, not None"

    # Verify L1 still holds nothing fresh-but-None — next call after upstream
    # recovers should fetch, not serve a tombstone.
    fresh_calls: list[str] = []

    async def fresh(missing: list[str]) -> dict[str, Quote | None]:
        fresh_calls.extend(missing)
        return {t: Quote(price=200.0) for t in missing}

    result2 = await cache.get_batch(["AAPL"], fetcher=fresh)
    assert result2 == {"AAPL": Quote(price=200.0)}, "post-recovery fetch must overwrite"
    assert fresh_calls == ["AAPL"], "rate-limit must not have written None to L1"
    await cache.close()


@pytest.mark.asyncio
async def test_rate_limit_without_stale_returns_none(tmp_path: Path) -> None:
    """First-ever fetch hits 429 → result has None but no tombstone written.

    The dashboard already renders ``None`` as a "no quote yet" state; the
    invariant here is that the next request after upstream recovery still
    invokes the fetcher (cache must not have learned a False answer).
    """
    # cooldown=0 isolates the no-tombstone invariant from the cooldown feature.
    cache = QuoteCache(db_path=tmp_path / "q.db", ttl_seconds=60, rate_limit_cooldown_seconds=0)

    async def rate_limited(missing: list[str]) -> dict[str, Quote | None]:
        raise QuoteFetchRateLimited("Yahoo 429")

    result = await cache.get_batch(["NEW"], fetcher=rate_limited)
    assert result == {"NEW": None}

    fresh_calls: list[str] = []

    async def fresh(missing: list[str]) -> dict[str, Quote | None]:
        fresh_calls.extend(missing)
        return {t: Quote(price=50.0) for t in missing}

    result2 = await cache.get_batch(["NEW"], fetcher=fresh)
    assert result2 == {"NEW": Quote(price=50.0)}
    assert fresh_calls == ["NEW"], "no tombstone — fetcher must be invoked"
    await cache.close()


@pytest.mark.asyncio
async def test_rate_limit_partial_batch_preserves_only_stale(tmp_path: Path) -> None:
    """Mixed batch: 1 ticker has stale L2, 1 doesn't → preserve stale + None for cold."""
    cache = QuoteCache(db_path=tmp_path / "q.db", ttl_seconds=0)

    async def first(missing: list[str]) -> dict[str, Quote | None]:
        return {t: Quote(price=150.0) for t in missing}

    await cache.get_batch(["AAPL"], fetcher=first)
    await asyncio.sleep(0.01)

    async def rate_limited(missing: list[str]) -> dict[str, Quote | None]:
        raise QuoteFetchRateLimited("Yahoo 429")

    result = await cache.get_batch(["AAPL", "COLD"], fetcher=rate_limited)
    assert result == {"AAPL": Quote(price=150.0), "COLD": None}
    await cache.close()


@pytest.mark.asyncio
async def test_l2_read_error_self_heals_and_falls_back_to_fetcher(
    tmp_path: Path,
) -> None:
    """Regression: a wedged aiosqlite conn must NOT take the route down.

    Before this fix the landing page would 500 the moment QuoteCache's
    long-lived sqlite handle stopped working — the live ~30h dev session
    hit exactly this. ``get_batch`` now drops the bad conn so the request
    is served from the origin fetcher and the singleton recovers in-flight.
    """
    import sqlite3

    cache = QuoteCache(db_path=tmp_path / "q.db", ttl_seconds=60)
    # Force the *next* L2 read to explode the way a dead aiosqlite conn does.
    await cache._conn_ready()
    broken_conn = cache._conn
    assert broken_conn is not None

    def boom(*_a: object, **_kw: object) -> object:
        raise sqlite3.OperationalError("database is locked")

    broken_conn.execute = boom  # type: ignore[method-assign]

    async def fetcher(missing: list[str]) -> dict[str, Quote | None]:
        return {t: Quote(price=99.0) for t in missing}

    result = await cache.get_batch(["AAPL"], fetcher=fetcher)
    assert result == {"AAPL": Quote(price=99.0)}  # served by fetcher, not 500

    # Wedged conn was dropped + replaced (in-flight L2 write rebuilds it).
    assert cache._conn is not broken_conn

    # Next call works — fresh conn isn't carrying the booby trap.
    result2 = await cache.get_batch(["MSFT"], fetcher=fetcher)
    assert result2 == {"MSFT": Quote(price=99.0)}
    await cache.close()


@pytest.mark.asyncio
async def test_peek_batch_serves_fresh_only_and_never_writes(tmp_path: Path) -> None:
    """peek_batch returns fresh L1/L2 rows but cold/stale come back None, and a
    peek of a cold ticker must NOT tomb-stone it — a later real get_batch still
    fetches it."""
    cache = QuoteCache(db_path=tmp_path / "q.db", ttl_seconds=60)

    async def warm(missing: list[str]) -> dict[str, Quote | None]:
        return {t: Quote(price=187.0) for t in missing}

    await cache.get_batch(["AAPL"], fetcher=warm)  # AAPL now fresh in L1+L2

    # Fresh ticker served; cold ticker → None.
    peeked = await cache.peek_batch(["AAPL", "COLD"])
    assert peeked == {"AAPL": Quote(price=187.0), "COLD": None}

    # The cold peek must not have written a fresh None tombstone for COLD.
    calls: list[str] = []

    async def fetch_cold(missing: list[str]) -> dict[str, Quote | None]:
        calls.extend(missing)
        return {t: Quote(price=42.0) for t in missing}

    out = await cache.get_batch(["COLD"], fetcher=fetch_cold)
    assert out == {"COLD": Quote(price=42.0)}, "peek must not have tombstoned COLD"
    assert calls == ["COLD"], "real fetch must run — peek planted no fresh None"
    await cache.close()


@pytest.mark.asyncio
async def test_peek_batch_does_not_destroy_stale_revalidate_row(tmp_path: Path) -> None:
    """A peek of a *stale* ticker must preserve its last-known price for
    stale-while-revalidate. Repro of the cited 250.0→None: the no-op-fetcher
    cache-only path overwrote the stale L2 row with None, so a later
    rate-limited get_batch served None instead of the last good 250.0."""
    cache = QuoteCache(db_path=tmp_path / "q.db", ttl_seconds=0, rate_limit_cooldown_seconds=0)

    async def warm(missing: list[str]) -> dict[str, Quote | None]:
        return {t: Quote(price=250.0) for t in missing}

    await cache.get_batch(["AAPL"], fetcher=warm)
    await asyncio.sleep(0.01)  # TTL=0 → AAPL is now stale-but-recoverable

    # Cache-only peek of the stale ticker → None to caller, but row must survive.
    assert await cache.peek_batch(["AAPL"]) == {"AAPL": None}

    async def rate_limited(missing: list[str]) -> dict[str, Quote | None]:
        raise QuoteFetchRateLimited("Yahoo 429")

    recovered = await cache.get_batch(["AAPL"], fetcher=rate_limited)
    assert recovered == {"AAPL": Quote(price=250.0)}, "peek must not have destroyed the stale price"
    await cache.close()


@pytest.mark.asyncio
async def test_rate_limit_opens_cooldown_skips_fetcher(tmp_path: Path) -> None:
    """After a 429, a batch within the cooldown window must NOT call the
    fetcher again — it serves stale. This is the heat fix: a Yahoo 429 storm
    must not turn every dashboard refresh into another doomed round-trip."""
    cache = QuoteCache(db_path=tmp_path / "q.db", ttl_seconds=0, rate_limit_cooldown_seconds=30)

    async def first(missing: list[str]) -> dict[str, Quote | None]:
        return {t: Quote(price=150.0) for t in missing}

    await cache.get_batch(["AAPL"], fetcher=first)
    await asyncio.sleep(0.01)  # TTL expired

    async def rate_limited(missing: list[str]) -> dict[str, Quote | None]:
        raise QuoteFetchRateLimited("Yahoo 429")

    await cache.get_batch(["AAPL"], fetcher=rate_limited)  # opens cooldown

    calls: list[str] = []

    async def should_not_be_called(missing: list[str]) -> dict[str, Quote | None]:
        calls.extend(missing)
        return {t: Quote(price=999.0) for t in missing}

    result = await cache.get_batch(["AAPL"], fetcher=should_not_be_called)
    assert result == {"AAPL": Quote(price=150.0)}, "cooldown must serve stale, not refetch"
    assert calls == [], "cooldown must skip the fetcher entirely"
    await cache.close()


@pytest.mark.asyncio
async def test_cooldown_expires_allows_refetch(tmp_path: Path) -> None:
    """Once the cooldown window elapses, the next batch re-hits the fetcher."""
    cache = QuoteCache(db_path=tmp_path / "q.db", ttl_seconds=0, rate_limit_cooldown_seconds=0.05)

    async def first(missing: list[str]) -> dict[str, Quote | None]:
        return {t: Quote(price=150.0) for t in missing}

    await cache.get_batch(["AAPL"], fetcher=first)
    await asyncio.sleep(0.01)

    async def rate_limited(missing: list[str]) -> dict[str, Quote | None]:
        raise QuoteFetchRateLimited("Yahoo 429")

    await cache.get_batch(["AAPL"], fetcher=rate_limited)  # opens 50ms cooldown
    await asyncio.sleep(0.06)  # cooldown elapsed

    calls: list[str] = []

    async def fresh(missing: list[str]) -> dict[str, Quote | None]:
        calls.extend(missing)
        return {t: Quote(price=222.0) for t in missing}

    result = await cache.get_batch(["AAPL"], fetcher=fresh)
    assert result == {"AAPL": Quote(price=222.0)}
    assert calls == ["AAPL"], "cooldown expired → fetcher must run again"
    await cache.close()


@pytest.mark.asyncio
async def test_cooldown_blocks_new_cold_ticker(tmp_path: Path) -> None:
    """Cooldown is per-provider (the upstream is throttled), not per-ticker:
    a brand-new ticker requested during the window returns None without a
    fetch — we don't ask a throttled source for anything."""
    cache = QuoteCache(db_path=tmp_path / "q.db", ttl_seconds=60, rate_limit_cooldown_seconds=30)

    async def rate_limited(missing: list[str]) -> dict[str, Quote | None]:
        raise QuoteFetchRateLimited("Yahoo 429")

    await cache.get_batch(["AAPL"], fetcher=rate_limited)  # opens cooldown

    calls: list[str] = []

    async def should_not_be_called(missing: list[str]) -> dict[str, Quote | None]:
        calls.extend(missing)
        return {t: Quote(price=999.0) for t in missing}

    result = await cache.get_batch(["TSLA"], fetcher=should_not_be_called)
    assert result == {"TSLA": None}
    assert calls == [], "throttled upstream → don't fetch even a new ticker"
    await cache.close()
