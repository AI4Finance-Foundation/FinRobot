"""Unit tests for fetch_quotes_batch_cached — DataLayer mocked, no network.

门一 Step 3: quotes now resolve through ``DataLayer.fetch_quote`` (provider
chain FMP → yfinance) instead of direct yfinance. The batch layer's job is the
two-layer cache + the rate-limit → cooldown mapping; these tests pin that
behavior with a fake DataLayer.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

import pytest

from finrobot.engine.data import quote_batch
from finrobot.engine.data.interface import DataResult, ProviderError
from finrobot.engine.data.quote_cache import Quote
from finrobot.engine.data.types import DataType


class _FakeDataLayer:
    """Stand-in exposing only ``fetch_quote`` (what the batch layer calls)."""

    def __init__(
        self,
        prices: dict[str, float] | None = None,
        *,
        rate_limited: set[str] | None = None,
        failed: set[str] | None = None,
        currencies: dict[str, str] | None = None,
    ) -> None:
        self._prices = prices or {}
        self._rate_limited = rate_limited or set()
        self._failed = failed or set()
        # Per-ticker quote currency the provider stamps onto its QUOTE payload
        # (yfinance fast_info.currency / FMP /profile.currency). Absent → no field.
        self._currencies = currencies or {}
        self.calls: list[str] = []

    async def fetch_quote(self, ticker: str) -> DataResult:
        self.calls.append(ticker)
        if ticker in self._rate_limited:
            raise ProviderError(f"HTTP 429 Too Many Requests for {ticker}")
        if ticker in self._failed or ticker not in self._prices:
            raise ProviderError(f"no quote for {ticker} — delisted")
        data: dict[str, Any] = {"price": self._prices[ticker]}
        if ticker in self._currencies:
            data["quote_currency"] = self._currencies[ticker]
        return DataResult(
            data=data,
            provider="fake",
            ticker=ticker,
            data_type=DataType.QUOTE,
            timestamp=datetime.now(tz=timezone.utc),
        )


@pytest.fixture(autouse=True)
async def _fresh_singleton(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """Isolate the QuoteCache singleton + its SQLite file per test.

    QUOTES_DB is an import-time path constant, so point it at a per-test tmp
    file directly (monkeypatching HOME alone wouldn't relocate it).

    Tear down by *closing* the singleton (await), not merely dropping the
    reference: ``reset_quote_cache_singleton`` would orphan the live aiosqlite
    connection whose non-daemon worker thread is bound to this test's event
    loop. Once that loop closes, GC's ``Connection.__del__`` fires
    ``call_soon_threadsafe`` on a dead loop at a non-deterministic point,
    eventually corrupting the run (``pytest tests/`` died abruptly ~test 1150,
    BUG-050). ``close_quote_cache_singleton`` sends aiosqlite its STOP sentinel
    inside the still-live loop so the worker thread exits cleanly. It also nulls
    the reference, so the per-test QUOTES_DB monkeypatch is picked up on the
    next ``_get_singleton`` build."""
    import finrobot.paths as _paths

    monkeypatch.setattr(_paths, "QUOTES_DB", tmp_path / "quotes_cache.db")
    await quote_batch.close_quote_cache_singleton()
    yield
    await quote_batch.close_quote_cache_singleton()


@pytest.mark.asyncio
async def test_empty_input_returns_empty_dict() -> None:
    layer = _FakeDataLayer()
    assert await quote_batch.fetch_quotes_batch_cached([], layer) == {}
    assert await quote_batch.fetch_quotes_batch_cached(["", "  "], layer) == {}
    assert layer.calls == []


@pytest.mark.asyncio
async def test_happy_path_three_tickers() -> None:
    layer = _FakeDataLayer({"AAPL": 187.32, "MSFT": 412.10, "NVDA": 905.5})
    out = await quote_batch.fetch_quotes_batch_cached(["AAPL", "MSFT", "NVDA"], layer)
    assert out == {
        "AAPL": Quote(price=187.32),
        "MSFT": Quote(price=412.10),
        "NVDA": Quote(price=905.5),
    }


@pytest.mark.asyncio
async def test_quote_currency_carried_through_batch_and_l2() -> None:
    """The QUOTE provider's currency stamp travels WITH the price through the
    batch + cache (the strip mis-lit-lamp root fix): a foreign listing's TWD
    currency is on the Quote, and survives an L1 wipe (served from L2)."""
    layer = _FakeDataLayer(
        {"AAPL": 200.0, "2330.TW": 640.0},
        currencies={"AAPL": "USD", "2330.TW": "TWD"},
    )
    out = await quote_batch.fetch_quotes_batch_cached(["AAPL", "2330.TW"], layer)
    assert out == {
        "AAPL": Quote(price=200.0, currency="USD"),
        "2330.TW": Quote(price=640.0, currency="TWD"),
    }

    # Wipe L1 so the next read must come from the SQLite L2 — currency must persist.
    cache = quote_batch._get_singleton()
    async with cache._l1_lock:
        cache._l1.clear()
    again = await quote_batch.fetch_quotes_batch_cached(["2330.TW"], layer)
    assert again == {"2330.TW": Quote(price=640.0, currency="TWD")}  # from L2, currency intact


@pytest.mark.asyncio
async def test_quote_currency_absent_is_none_not_assumed_usd() -> None:
    """A provider that does not stamp a currency yields Quote.currency=None — the
    consumer must abstain, never assume USD (US/foreign indistinguishable here)."""
    layer = _FakeDataLayer({"AAPL": 200.0})  # no currencies configured
    out = await quote_batch.fetch_quotes_batch_cached(["AAPL"], layer)
    assert out == {"AAPL": Quote(price=200.0, currency=None)}


@pytest.mark.asyncio
async def test_missing_ticker_returns_none() -> None:
    layer = _FakeDataLayer({"AAPL": 187.32}, failed={"ZZZZ"})
    out = await quote_batch.fetch_quotes_batch_cached(["AAPL", "ZZZZ"], layer)
    assert out["AAPL"] == Quote(price=187.32)
    assert out["ZZZZ"] is None


@pytest.mark.asyncio
async def test_case_normalised_input() -> None:
    layer = _FakeDataLayer({"AAPL": 187.32})
    out = await quote_batch.fetch_quotes_batch_cached(["aapl"], layer)
    assert out == {"AAPL": Quote(price=187.32)}


@pytest.mark.asyncio
async def test_warm_hit_skips_fetch() -> None:
    """Second call within TTL returns from cache without re-hitting the layer."""
    layer = _FakeDataLayer({"AAPL": 200.0, "MSFT": 200.0})
    out1 = await quote_batch.fetch_quotes_batch_cached(["AAPL", "MSFT"], layer)
    assert out1 == {"AAPL": Quote(price=200.0), "MSFT": Quote(price=200.0)}
    assert sorted(layer.calls) == ["AAPL", "MSFT"]

    out2 = await quote_batch.fetch_quotes_batch_cached(["AAPL"], layer)
    assert out2 == {"AAPL": Quote(price=200.0)}
    assert sorted(layer.calls) == ["AAPL", "MSFT"]  # no extra fetch — L1 hit


@pytest.mark.asyncio
async def test_cold_fan_out_is_concurrent() -> None:
    """The cold path fans out per ticker concurrently (asyncio.gather), not serially.

    Each fetch_quote blocks on a 4-party barrier; a serial loop would leave one
    coroutine waiting alone and time out, a concurrent gather clears it at once.
    """
    barrier = asyncio.Barrier(4)

    class _BarrierLayer:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def fetch_quote(self, ticker: str) -> DataResult:
            self.calls.append(ticker)
            await asyncio.wait_for(barrier.wait(), timeout=2.0)
            return DataResult(
                data={"price": 100.0},
                provider="fake",
                ticker=ticker,
                data_type=DataType.QUOTE,
                timestamp=datetime.now(tz=timezone.utc),
            )

    out = await quote_batch.fetch_quotes_batch_cached(["A", "B", "C", "D"], _BarrierLayer())
    assert out == {
        "A": Quote(price=100.0),
        "B": Quote(price=100.0),
        "C": Quote(price=100.0),
        "D": Quote(price=100.0),
    }


@pytest.mark.asyncio
async def test_rate_limit_opens_cache_wide_cooldown() -> None:
    """A 429 from the provider chain maps to QuoteFetchRateLimited, which opens
    QuoteCache's cooldown — proving the rate-limit signal survived (it was NOT
    silently written as a None tombstone). During cooldown, even a fresh ticker
    is served stale-only (no fetch)."""
    layer = _FakeDataLayer({"OTHER": 50.0}, rate_limited={"LIMIT"})

    out = await quote_batch.fetch_quotes_batch_cached(["LIMIT"], layer)
    assert out == {"LIMIT": None}  # no stale row → None, but no crash
    calls_after_limit = len(layer.calls)

    # Cooldown is provider-wide: the fetcher is skipped for OTHER too.
    out2 = await quote_batch.fetch_quotes_batch_cached(["OTHER"], layer)
    assert out2 == {"OTHER": None}
    assert len(layer.calls) == calls_after_limit  # fetch_quote NOT called for OTHER


@pytest.mark.asyncio
async def test_all_providers_circuit_open_preserves_stale_price(tmp_path: Any) -> None:
    """Bug 12 repro: a warm price goes TTL-stale, then EVERY QUOTE-capable
    provider sits in an open circuit-breaker cooldown. fetch_quote raises a
    gated-exhaustion error that MUST carry rate-limit semantics — otherwise the
    fetcher returns None and get_batch overwrites the stale L1+L2 price with a
    fresh None tombstone (the 429 disaster, resurrected through the breaker).

    Uses a REAL DataLayer (not _FakeDataLayer) so the test pins the actual
    fetch_quote gated-exhaustion path end to end."""
    from finrobot.engine.data.cache import DataCache
    from finrobot.engine.data.interface import DataProvider
    from finrobot.engine.data.layer import DataLayer
    from finrobot.engine.data.provider_health import ProviderHealth

    # 1. Warm the cache with a real price.
    warm_layer = _FakeDataLayer({"AAPL": 200.0})
    assert await quote_batch.fetch_quotes_batch_cached(["AAPL"], warm_layer) == {
        "AAPL": Quote(price=200.0)
    }

    # 2. Age the row past the 60s TTL in both L1 and L2 so the next batch
    #    actually re-fetches instead of serving the fresh hit.
    cache = quote_batch._get_singleton()
    async with cache._l1_lock:
        price, fetched_at = cache._l1["AAPL"]
        cache._l1["AAPL"] = (price, fetched_at - 120.0)
    conn = await cache._conn_ready()
    await conn.execute("UPDATE quotes_cache_v2 SET fetched_at = fetched_at - 120")
    await conn.commit()

    # 3. Real DataLayer whose only QUOTE-capable provider is in open cooldown.
    class _QuoteProvider(DataProvider):
        fetch_called = 0

        @property
        def name(self) -> str:
            return "fmp"

        def capabilities(self) -> list[str]:
            return ["quote"]

        async def fetch(self, ticker: str, data_type: str, **kwargs: Any) -> DataResult:
            type(self).fetch_called += 1
            raise AssertionError("gated provider must never be attempted")

    health = ProviderHealth()
    health.record_failure("fmp", rate_limited=True)  # opens the breaker cooldown
    data_cache = DataCache(db_path=str(tmp_path / "data_cache.db"))
    try:
        gated_layer = DataLayer([_QuoteProvider()], data_cache, health=health)
        out = await quote_batch.fetch_quotes_batch_cached(["AAPL"], gated_layer)
    finally:
        await data_cache.close()

    # Stale price served, provider untouched.
    assert out == {"AAPL": Quote(price=200.0)}
    assert _QuoteProvider.fetch_called == 0

    # And the L2 row was NOT overwritten with a None tombstone.
    async with conn.execute("SELECT last_price FROM quotes_cache_v2 WHERE ticker = 'AAPL'") as cur:
        row = await cur.fetchone()
    assert row is not None and row[0] == 200.0


@pytest.mark.asyncio
async def test_generic_failure_does_not_open_cooldown() -> None:
    """A non-rate-limit failure tombstones None WITHOUT opening the cooldown —
    a different ticker still fetches normally."""
    layer = _FakeDataLayer({"OTHER": 50.0}, failed={"DEAD"})

    out = await quote_batch.fetch_quotes_batch_cached(["DEAD"], layer)
    assert out == {"DEAD": None}

    out2 = await quote_batch.fetch_quotes_batch_cached(["OTHER"], layer)
    assert out2 == {"OTHER": Quote(price=50.0)}  # no cooldown → OTHER fetched


# ─────────────────────────────────────────────────────────────────────────────
# fetch_quotes_cache_only — landing recent-research strip path. NEVER fetches.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_only_returns_none_for_cold_misses_without_fetching() -> None:
    """A cold cache returns None for every ticker and never touches providers."""
    out = await quote_batch.fetch_quotes_cache_only(["AAPL", "MSFT"])
    assert out == {"AAPL": None, "MSFT": None}


@pytest.mark.asyncio
async def test_cache_only_serves_warm_l1_rows() -> None:
    """A ticker warmed via the cold batch path is served from L1 cache-only,
    with no further provider call."""
    layer = _FakeDataLayer({"AAPL": 187.0})
    warmed = await quote_batch.fetch_quotes_batch_cached(["AAPL"], layer)
    assert warmed == {"AAPL": Quote(price=187.0)}
    calls_after_warm = len(layer.calls)

    out = await quote_batch.fetch_quotes_cache_only(["AAPL"])
    assert out == {"AAPL": Quote(price=187.0)}
    assert len(layer.calls) == calls_after_warm  # cache-only did NOT re-fetch


@pytest.mark.asyncio
async def test_cache_only_empty_input_returns_empty_dict() -> None:
    assert await quote_batch.fetch_quotes_cache_only([]) == {}
    assert await quote_batch.fetch_quotes_cache_only(["", "  "]) == {}


@pytest.mark.asyncio
async def test_cache_only_miss_does_not_block_later_real_fetch() -> None:
    """A cache-only read of a cold ticker must NOT plant a fresh None tombstone.

    Repro of W2 QuoteCache 探针毒化: ``fetch_quotes_cache_only`` borrowed
    ``get_batch``'s write-back path, so a cold miss wrote the no-fetch ``None``
    into L1+L2 as a *fresh* value. A subsequent real ``fetch_quotes_batch_cached``
    then served that None (L1 hit, within TTL) instead of fetching the real
    price — the landing recent-research strip's cache-only read silently
    poisoned the hit-rate banner's quote.
    """
    # Landing strip peeks a cold ticker → None (expected) but must not write back.
    cold = await quote_batch.fetch_quotes_cache_only(["AAPL"])
    assert cold == {"AAPL": None}

    # A real fetch within the (default 60s) TTL must still reach the provider.
    layer = _FakeDataLayer({"AAPL": 250.0})
    out = await quote_batch.fetch_quotes_batch_cached(["AAPL"], layer)
    assert out == {"AAPL": Quote(price=250.0)}, "cache-only read must not have tombstoned AAPL"
    assert layer.calls == ["AAPL"], "real fetch must reach provider, not serve poisoned None"
