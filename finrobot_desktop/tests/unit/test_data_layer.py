import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from finrobot.engine.data.cache import DataCache, raw_slot_key
from finrobot.engine.data.interface import DataProvider, DataResult, ProviderError
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.data.provider_health import ProviderHealth
from finrobot.engine.data.normalize import NormalizedFinancials, NormalizedPrice
from finrobot.engine.data.normalize.contracts import (
    DEGRADED_CIRCUIT_OPEN_PREFIX,
    DEGRADED_FX_NORMALIZED,
    DEGRADED_FX_UNAVAILABLE,
    DEGRADED_PROVIDER_DIVERGENCE_PREFIX,
    degraded_circuit_open,
    degraded_price_divergence,
    degraded_provider_divergence,
)
from finrobot.engine.data.types import DataType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    ticker: str = "AAPL", data_type: str = "financials", provider: str = "mock"
) -> DataResult:
    return DataResult(
        data={"revenue": 1_000},
        provider=provider,
        ticker=ticker,
        data_type=data_type,
        timestamp=datetime.now(tz=timezone.utc),
    )


class MockProvider(DataProvider):
    def __init__(
        self,
        name_: str,
        caps: list[str],
        result: DataResult | None = None,
        raises: Exception | None = None,
    ):
        self._name = name_
        self._caps = caps
        self._result = result
        self._raises = raises
        self.fetch_called = 0

    @property
    def name(self) -> str:
        return self._name

    def capabilities(self) -> list[str]:
        return self._caps

    async def fetch(self, ticker: str, data_type: str, **kwargs) -> DataResult:
        self.fetch_called += 1
        if self._raises:
            raise self._raises
        return self._result or _make_result(ticker=ticker, data_type=data_type, provider=self._name)


@pytest.fixture
async def cache(tmp_path):
    """Per-test DataCache; close() at teardown so the aiosqlite worker
    thread doesn't race the event loop teardown and emit warnings."""
    c = DataCache(db_path=str(tmp_path / "layer_test.db"))
    try:
        yield c
    finally:
        await c.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFetchFromProvider:
    async def test_empty_cache_calls_provider(self, cache):
        provider = MockProvider("mock", ["financials"])
        layer = DataLayer([provider], cache)
        result = await layer.fetch("financials", "AAPL")
        assert provider.fetch_called == 1
        assert result.provider == "mock"

    async def test_fresh_cache_returns_cache_without_calling_provider(self, cache):
        provider = MockProvider("mock", ["financials"])
        layer = DataLayer([provider], cache)
        # Prime the cache
        await layer.fetch("financials", "AAPL")
        provider.fetch_called = 0
        # Second fetch → should hit cache
        result = await layer.fetch("financials", "AAPL")
        assert provider.fetch_called == 0
        assert result.ticker == "AAPL"

    async def test_stale_cache_calls_provider_and_updates_cache(self, cache, tmp_path):
        import aiosqlite
        from datetime import timedelta

        provider = MockProvider("mock", ["financials"])
        layer = DataLayer([provider], cache)
        await layer.fetch("financials", "AAPL")

        # Backdate cache entry
        old_time = (datetime.now(tz=timezone.utc) - timedelta(hours=25)).isoformat()
        async with aiosqlite.connect(str(tmp_path / "layer_test.db")) as conn:
            await conn.execute(
                "UPDATE cache SET cached_at = ? WHERE data_type = ? AND ticker = ?",
                (old_time, "financials", "AAPL"),
            )
            await conn.commit()

        provider.fetch_called = 0
        await layer.fetch("financials", "AAPL")
        assert provider.fetch_called == 1


class TestProviderFailure:
    async def test_provider_fails_returns_stale_cache_with_warning(self, cache, tmp_path):
        import aiosqlite
        from datetime import timedelta

        good_provider = MockProvider("good", ["financials"])
        layer = DataLayer([good_provider], cache)
        await layer.fetch("financials", "AAPL")

        # Backdate so it's stale
        old_time = (datetime.now(tz=timezone.utc) - timedelta(hours=25)).isoformat()
        async with aiosqlite.connect(str(tmp_path / "layer_test.db")) as conn:
            await conn.execute(
                "UPDATE cache SET cached_at = ? WHERE data_type = ? AND ticker = ?",
                (old_time, "financials", "AAPL"),
            )
            await conn.commit()

        # Now provider fails
        failing_provider = MockProvider(
            "fail", ["financials"], raises=ProviderError("network error")
        )
        layer2 = DataLayer([failing_provider], cache)
        result = await layer2.fetch("financials", "AAPL")
        assert result is not None
        # BUG-046: the data layer emits neutral English (localization belongs in
        # the UI/display layer keyed on meta.language). The wording must contain
        # the "source"/"stale"/"cache" tokens base.py's disclaimer filter matches
        # on, so the stale warning actually reaches the report's Data Sources
        # disclaimer (the Chinese string never did → prior silent miss).
        stale = next(w for w in result.warnings if "cached data" in w)
        assert "All data sources failed" in stale
        assert "cache" in stale.lower() or "stale" in stale.lower()

    async def test_provider_fails_no_cache_returns_error_result(self, cache):
        """No crash — returns a DataResult the LLM can relay to the user."""
        failing = MockProvider("fail", ["financials"], raises=ProviderError("down"))
        layer = DataLayer([failing], cache)
        result = await layer.fetch("financials", "AAPL")
        assert result is not None
        assert result.provider == "none"
        assert len(result.warnings) > 0
        # BUG-046: neutral English at the data layer (was 中文-ified, which leaked
        # into English `--lang en` reports).
        assert any(
            "Data unavailable" in w and "all data sources failed" in w for w in result.warnings
        )


def _range_result(provider: str, ticker: str = "AAPL") -> DataResult:
    return DataResult(
        data={
            "ticker": ticker,
            "interval": "1d",
            "bars": [
                {
                    "date": "2020-01-02",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "volume": 1_000_000.0,
                },
                {
                    "date": "2020-01-03",
                    "open": 102.0,
                    "high": 103.0,
                    "low": 101.0,
                    "close": 102.5,
                    "volume": 1_100_000.0,
                },
            ],
            "adjusted": True,
            "source_provider": provider,
        },
        provider=provider,
        ticker=ticker,
        data_type="price_range",
        timestamp=datetime.now(tz=timezone.utc),
    )


class TestFetchPriceRange:
    async def test_returns_typed_bars(self, cache):
        provider = MockProvider("fmp", ["price_range"], result=_range_result("fmp"))
        layer = DataLayer([provider], cache)
        bars = await layer.fetch_price_range("AAPL", "2020-01-01", "2020-01-04")
        assert provider.fetch_called == 1
        assert [str(b.date) for b in bars] == ["2020-01-02", "2020-01-03"]
        assert bars[1].close == 102.5

    async def test_distinct_ranges_do_not_collide(self, cache):
        provider = MockProvider("fmp", ["price_range"], result=_range_result("fmp"))
        layer = DataLayer([provider], cache)
        await layer.fetch_price_range("AAPL", "2020-01-01", "2020-01-04")
        # A different window must NOT hit the first window's cache slot.
        await layer.fetch_price_range("AAPL", "2021-01-01", "2021-06-01")
        assert provider.fetch_called == 2
        # Re-requesting the first window hits cache (no new provider call).
        await layer.fetch_price_range("AAPL", "2020-01-01", "2020-01-04")
        assert provider.fetch_called == 2

    async def test_falls_back_to_second_provider(self, cache):
        p1 = MockProvider("fmp", ["price_range"], raises=ProviderError("fmp down"))
        p2 = MockProvider("yfinance", ["price_range"], result=_range_result("yfinance"))
        layer = DataLayer([p1, p2], cache)
        bars = await layer.fetch_price_range("AAPL", "2020-01-01", "2020-01-04")
        assert p1.fetch_called == 1 and p2.fetch_called == 1
        assert len(bars) == 2

    async def test_raises_when_all_providers_fail(self, cache):
        p1 = MockProvider("fmp", ["price_range"], raises=ProviderError("fmp down"))
        layer = DataLayer([p1], cache)
        with pytest.raises(ProviderError, match="fmp down"):
            await layer.fetch_price_range("AAPL", "2020-01-01", "2020-01-04")


class TestMultipleProviders:
    async def test_selects_correct_provider_for_data_type(self, cache):
        p_financials = MockProvider("fin_provider", ["financials"])
        p_news = MockProvider("news_provider", ["news"])
        layer = DataLayer([p_financials, p_news], cache)

        await layer.fetch("financials", "AAPL")
        assert p_financials.fetch_called == 1
        assert p_news.fetch_called == 0

        await layer.fetch("news", "AAPL")
        assert p_news.fetch_called == 1

    async def test_falls_back_to_second_provider_when_first_fails(self, cache):
        p1 = MockProvider("p1", ["financials"], raises=ProviderError("p1 down"))
        p2 = MockProvider("p2", ["financials"])
        layer = DataLayer([p1, p2], cache)
        result = await layer.fetch("financials", "AAPL")
        assert result.provider == "p2"
        assert p1.fetch_called == 1
        assert p2.fetch_called == 1


class TestChainFallback:
    """P2a: chain fallback iterates all providers, not just primary + 1 fallback."""

    async def test_three_provider_chain_first_succeeds(self, cache):
        """D4 cross-validation: for ``financials`` data the layer calls up to
        2 secondary providers so cross_validate() can flag discrepancies from
        multiple sources."""
        p1 = MockProvider("fmp", ["financials"], result=_make_result(provider="fmp"))
        p2 = MockProvider("finnhub", ["financials"])
        p3 = MockProvider("yfinance", ["financials"])
        layer = DataLayer([p1, p2, p3], cache)
        result = await layer.fetch("financials", "AAPL")
        assert result.provider == "fmp"  # primary wins
        assert p1.fetch_called == 1
        assert p2.fetch_called == 1  # cross-validation secondary #1
        assert p3.fetch_called == 1  # D4: cross-validation secondary #2

    async def test_three_provider_chain_first_fails_second_succeeds(self, cache):
        """P3 cross-validation: after p1 fails and p2 succeeds, p3 is ALSO
        called so cross_validate() has two numbers to compare."""
        p1 = MockProvider("fmp", ["financials"], raises=ProviderError("fmp down"))
        p2 = MockProvider("finnhub", ["financials"], result=_make_result(provider="finnhub"))
        p3 = MockProvider("yfinance", ["financials"])
        layer = DataLayer([p1, p2, p3], cache)
        result = await layer.fetch("financials", "AAPL")
        assert result.provider == "finnhub"
        assert p1.fetch_called == 1
        assert p2.fetch_called == 1
        assert p3.fetch_called == 1  # P3: called for cross-validation

    async def test_three_provider_chain_first_two_fail_third_succeeds(self, cache):
        p1 = MockProvider("fmp", ["financials"], raises=ProviderError("fmp down"))
        p2 = MockProvider("finnhub", ["financials"], raises=ProviderError("finnhub down"))
        p3 = MockProvider("yfinance", ["financials"], result=_make_result(provider="yfinance"))
        layer = DataLayer([p1, p2, p3], cache)
        result = await layer.fetch("financials", "AAPL")
        assert result.provider == "yfinance"
        assert p1.fetch_called == 1
        assert p2.fetch_called == 1
        assert p3.fetch_called == 1

    async def test_all_three_fail_returns_error(self, cache):
        p1 = MockProvider("fmp", ["financials"], raises=ProviderError("fmp down"))
        p2 = MockProvider("finnhub", ["financials"], raises=ProviderError("finnhub down"))
        p3 = MockProvider("yfinance", ["financials"], raises=ProviderError("yfinance down"))
        layer = DataLayer([p1, p2, p3], cache)
        result = await layer.fetch("financials", "AAPL")
        assert result.provider == "none"
        # BUG-046: neutral English at the data layer.
        assert any(
            "Data unavailable" in w and "all data sources failed" in w for w in result.warnings
        )

    async def test_price_fallback_skips_yfinance_when_rate_limited(self, cache):
        """yfinance 429 → FMP picks up PRICE without falling to stale cache.

        This is the regression test for the 2026-05-25 production bug where a
        NVDA pipeline run logged 'Provider yfinance failed ... Too Many
        Requests' and then '正在显示 20 小时前的缓存数据' because no other
        provider claimed DataType.PRICE in its capabilities.
        """
        # yfinance listed first (typical case: it's free + always-on, FMP only
        # registered when api_key is set, so the production order has yfinance
        # near the top of the chain). For PRICE the layer breaks out on the
        # first success, so we just need FMP to be reachable.
        p_yf = MockProvider(
            "yfinance",
            ["price"],
            raises=ProviderError("Too Many Requests. Rate limited."),
        )
        fmp_result = DataResult(
            data={"current_price": 175.0},
            provider="fmp",
            ticker="NVDA",
            data_type="price",
            timestamp=datetime.now(tz=timezone.utc),
        )
        p_fmp = MockProvider("fmp", ["price"], result=fmp_result)
        layer = DataLayer([p_yf, p_fmp], cache)
        result = await layer.fetch("price", "NVDA")
        assert result.provider == "fmp"
        assert result.data["current_price"] == 175.0
        # No "All data sources failed" stale-cache fallback should fire here —
        # proves the chain actually traversed both providers instead of erroring.
        assert not any("All data sources failed" in w for w in result.warnings)


class TestCrossValidationIntegration:
    """P3 Track 3: DataLayer.fetch calls cross_validate for FINANCIALS."""

    async def test_cross_validation_warning_appended_on_discrepancy(self, cache):
        """Two providers disagree on revenue → warning appended to primary."""
        payload_p1 = {"revenue": 100_000_000}
        payload_p2 = {"revenue": 150_000_000}  # 33% discrepancy
        r1 = DataResult(
            data=payload_p1,
            provider="fmp",
            ticker="AAPL",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )
        r2 = DataResult(
            data=payload_p2,
            provider="finnhub",
            ticker="AAPL",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )
        p1 = MockProvider("fmp", ["financials"], result=r1)
        p2 = MockProvider("finnhub", ["financials"], result=r2)
        layer = DataLayer([p1, p2], cache)
        result = await layer.fetch("financials", "AAPL")
        assert result.provider == "fmp"
        assert any("revenue" in w and "discrepancy" in w for w in result.warnings)

    async def test_cross_validation_no_warning_when_agreeing(self, cache):
        """Two providers agree → no discrepancy warning on primary."""
        payload = {"revenue": 100_000_000, "ebitda": 20_000_000}
        r1 = DataResult(
            data=payload,
            provider="fmp",
            ticker="AAPL",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )
        r2 = DataResult(
            data=payload,
            provider="finnhub",
            ticker="AAPL",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )
        p1 = MockProvider("fmp", ["financials"], result=r1)
        p2 = MockProvider("finnhub", ["financials"], result=r2)
        layer = DataLayer([p1, p2], cache)
        result = await layer.fetch("financials", "AAPL")
        assert result.provider == "fmp"
        assert not any("discrepancy" in w for w in result.warnings)

    async def test_non_financials_does_not_cross_validate(self, cache):
        """For data_type != financials, second provider is NOT called."""
        p1 = MockProvider("p1", ["price"])
        p2 = MockProvider("p2", ["price"])
        layer = DataLayer([p1, p2], cache)
        await layer.fetch("price", "AAPL")
        assert p1.fetch_called == 1
        assert p2.fetch_called == 0  # short-circuit for non-financials

    async def test_secondary_provider_warnings_preserved(self, cache):
        """P3 audit I4: warnings from the secondary provider must survive
        the cross-validation merge. Dropping them would hide useful
        operational info such as 'data delayed 15 minutes'."""
        primary = DataResult(
            data={"revenue": 100_000_000},
            provider="fmp",
            ticker="AAPL",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
            warnings=["primary warning A"],
        )
        secondary = DataResult(
            data={"revenue": 100_000_000},  # agreement → no discrepancy
            provider="finnhub",
            ticker="AAPL",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
            warnings=["finnhub: data delayed 15 min"],
        )
        p1 = MockProvider("fmp", ["financials"], result=primary)
        p2 = MockProvider("finnhub", ["financials"], result=secondary)
        layer = DataLayer([p1, p2], cache)
        result = await layer.fetch("financials", "AAPL")
        assert result.provider == "fmp"
        assert "primary warning A" in result.warnings
        assert "finnhub: data delayed 15 min" in result.warnings

    async def test_cross_validation_merge_dedupes_warnings(self, cache):
        """If primary and secondary share an identical warning string, the
        merged result should contain it only once (de-dup preserves order)."""
        shared = "data delayed 15 min"
        primary = DataResult(
            data={"revenue": 100_000_000},
            provider="fmp",
            ticker="AAPL",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
            warnings=[shared],
        )
        secondary = DataResult(
            data={"revenue": 100_000_000},
            provider="finnhub",
            ticker="AAPL",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
            warnings=[shared],
        )
        p1 = MockProvider("fmp", ["financials"], result=primary)
        p2 = MockProvider("finnhub", ["financials"], result=secondary)
        layer = DataLayer([p1, p2], cache)
        result = await layer.fetch("financials", "AAPL")
        assert result.warnings.count(shared) == 1

    async def test_cross_validation_uses_all_three_providers(self, cache):
        """D4: third provider's discrepancy must appear in warnings."""
        base = {"revenue": 100_000, "ebitda": 50_000}
        r_base = DataResult(
            data=base,
            provider="placeholder",
            ticker="TEST",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )
        r_discrepant = DataResult(
            data={"revenue": 200_000, "ebitda": 50_000},
            provider="p3",
            ticker="TEST",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )
        p1 = MockProvider("p1", ["financials"], result=r_base.model_copy(update={"provider": "p1"}))
        p2 = MockProvider("p2", ["financials"], result=r_base.model_copy(update={"provider": "p2"}))
        p3 = MockProvider("p3", ["financials"], result=r_discrepant)
        layer = DataLayer([p1, p2, p3], cache)
        result = await layer.fetch("financials", "TEST")
        assert p3.fetch_called == 1, "Third provider was not called"
        assert any(
            "p3" in w for w in result.warnings
        ), f"Third provider discrepancy not in warnings: {result.warnings}"

    async def test_empty_secondary_skipped_tries_next_provider(self, cache):
        """D5: empty secondary data → warning added, next provider tried."""
        base = {"revenue": 100_000, "ebitda": 50_000}
        r1 = DataResult(
            data=base,
            provider="p1",
            ticker="TEST",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )
        r2_empty = DataResult(
            data={},
            provider="p2",
            ticker="TEST",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )
        r3 = DataResult(
            data={"revenue": 200_000, "ebitda": 50_000},
            provider="p3",
            ticker="TEST",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )
        p1 = MockProvider("p1", ["financials"], result=r1)
        p2 = MockProvider("p2", ["financials"], result=r2_empty)
        p3 = MockProvider("p3", ["financials"], result=r3)
        layer = DataLayer([p1, p2, p3], cache)
        result = await layer.fetch("financials", "TEST")
        assert any("empty data" in w.lower() for w in result.warnings)
        assert p3.fetch_called > 0

    async def test_cross_validation_caps_at_three_providers(self, cache):
        """D4: at most 3 providers attempted for financials, even if more configured."""
        base_data = {"revenue": 100_000}
        providers = []
        for i in range(5):
            r = DataResult(
                data=base_data,
                provider=f"p{i}",
                ticker="TEST",
                data_type="financials",
                timestamp=datetime.now(tz=timezone.utc),
            )
            providers.append(MockProvider(f"p{i}", ["financials"], result=r))
        layer = DataLayer(providers, cache)
        await layer.fetch("financials", "TEST")
        fetched = [p for p in providers if p.fetch_called > 0]
        assert len(fetched) <= 3, f"Expected max 3 providers, got {len(fetched)}"


class TestCircuitOpenProvenance:
    """Circuit-breaker skips must be visible in DataResult and Provenance.degraded."""

    def _tripped_health(self, provider_name: str) -> ProviderHealth:
        health = ProviderHealth()
        for _ in range(health.failure_threshold + 1):
            health.record_failure(provider_name, rate_limited=True)
        return health

    async def test_circuit_open_stamped_on_data_result(self, cache):
        """Skipped provider name appears in DataResult.circuit_open_providers."""
        health = self._tripped_health("fmp")
        fmp = MockProvider("fmp", ["financials"])
        yf = MockProvider("yfinance", ["financials"])
        layer = DataLayer([fmp, yf], cache, health=health)

        result = await layer.fetch("financials", "AAPL")
        assert result.provider == "yfinance"
        assert fmp.fetch_called == 0
        assert "fmp" in result.circuit_open_providers

    async def test_circuit_open_does_not_appear_when_provider_healthy(self, cache):
        """No circuit_open marker when all providers are available."""
        fmp = MockProvider("fmp", ["financials"])
        layer = DataLayer([fmp], cache)
        result = await layer.fetch("financials", "AAPL")
        assert result.circuit_open_providers == []

    async def test_circuit_open_propagates_to_provenance_degraded(self, cache):
        """fetch_canonical must translate circuit_open_providers → provenance.degraded."""
        health = self._tripped_health("fmp")
        fmp = MockProvider("fmp", ["financials"])
        yf_result = DataResult(
            data={"revenue": 1_000_000, "period_basis": "ttm"},
            provider="yfinance",
            ticker="AAPL",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )
        yf = MockProvider("yfinance", ["financials"], result=yf_result)
        layer = DataLayer([fmp, yf], cache, health=health)

        normalized = await layer.fetch_canonical(DataType.FINANCIALS, "AAPL")
        expected_marker = degraded_circuit_open("fmp")
        assert (
            expected_marker in normalized.provenance.degraded
        ), f"Expected '{expected_marker}' in degraded={normalized.provenance.degraded}"
        assert expected_marker.startswith(DEGRADED_CIRCUIT_OPEN_PREFIX)


class TestReadCanonicalCached:
    """Cache-only canonical read — the stale-while-revalidate first paint.

    Must never call the provider chain, and must return last-known snapshots
    even past their freshness TTL (flagged stale) so the Coverage desk paints
    instantly instead of waiting on the cold provider fan-out.
    """

    async def test_miss_returns_none(self, cache):
        provider = MockProvider("mock", ["financials"])
        layer = DataLayer([provider], cache)
        assert await layer.read_canonical_cached(DataType.FINANCIALS, "AAPL") is None
        assert provider.fetch_called == 0  # never touches the provider

    async def test_fresh_snapshot_returns_not_stale_without_provider(self, cache):
        provider = MockProvider("mock", ["financials"])
        layer = DataLayer([provider], cache)
        await layer.fetch_canonical(DataType.FINANCIALS, "AAPL")  # prime the cache
        provider.fetch_called = 0

        hit = await layer.read_canonical_cached(DataType.FINANCIALS, "AAPL")
        assert hit is not None
        norm, is_stale = hit
        assert isinstance(norm, NormalizedFinancials)
        assert is_stale is False
        assert provider.fetch_called == 0  # cache read, no network

    async def test_stale_snapshot_still_returned_flagged_no_provider(self, cache, tmp_path):
        import aiosqlite
        from datetime import timedelta

        from finrobot.engine.data.cache import canonical_key

        provider = MockProvider("mock", ["financials"])
        layer = DataLayer([provider], cache)
        await layer.fetch_canonical(DataType.FINANCIALS, "AAPL")

        # Backdate the canonical slot past the 24h FINANCIALS TTL.
        old_time = (datetime.now(tz=timezone.utc) - timedelta(hours=25)).isoformat()
        async with aiosqlite.connect(str(tmp_path / "layer_test.db")) as conn:
            await conn.execute(
                "UPDATE cache SET cached_at = ? WHERE data_type = ? AND ticker = ?",
                (old_time, canonical_key(DataType.FINANCIALS), "AAPL"),
            )
            await conn.commit()

        provider.fetch_called = 0
        hit = await layer.read_canonical_cached(DataType.FINANCIALS, "AAPL")
        assert hit is not None
        norm, is_stale = hit
        assert isinstance(norm, NormalizedFinancials)
        assert is_stale is True  # past TTL → flagged, but value still served
        assert provider.fetch_called == 0  # NEVER revalidates here (that's refresh)

    async def test_rejects_non_canonical_type(self, cache):
        layer = DataLayer([MockProvider("mock", ["news"])], cache)
        with pytest.raises(ValueError, match="PRICE / FINANCIALS"):
            await layer.read_canonical_cached(DataType.NEWS, "AAPL")


class TestCanonicalStaleNoLaundering:
    """A stale-fallback fetch must NOT reset the canonical freshness clock.

    Repro of the in-market 2026-06-08 bug: a stale canonical entry + all providers
    failing made ``_fetch_canonical_uncached`` re-cache the STALE raw row as a FRESH
    canonical entry (cached_at bumped → is_stale flips back to False), laundering a
    95-min-old price into a "live"-reading quote with no warning. The honest behavior
    is to keep serving the last-known value while leaving it flagged stale, so the
    stale-while-revalidate machinery keeps retrying until a provider recovers.
    """

    @staticmethod
    async def _backdate_all(db_path: str, ticker: str, hours: float) -> None:
        import aiosqlite
        from datetime import timedelta

        old = (datetime.now(tz=timezone.utc) - timedelta(hours=hours)).isoformat()
        async with aiosqlite.connect(db_path) as conn:
            # WHERE ticker only → backdates BOTH the raw slot and the canonical slot.
            await conn.execute("UPDATE cache SET cached_at = ? WHERE ticker = ?", (old, ticker))
            await conn.commit()

    async def test_financials_stale_fallback_not_laundered(self, cache, tmp_path):
        db = str(tmp_path / "layer_test.db")
        good = MockProvider("good", ["financials"])
        await DataLayer([good], cache).fetch_canonical(DataType.FINANCIALS, "AAPL")

        await self._backdate_all(db, "AAPL", hours=25)  # raw + canonical now stale

        layer = DataLayer(
            [MockProvider("fail", ["financials"], raises=ProviderError("down"))], cache
        )
        result = await layer.fetch_canonical(DataType.FINANCIALS, "AAPL")
        assert result is not None  # stale value still served to THIS caller

        # The canonical slot must remain flagged stale — NOT relaundered to fresh.
        hit = await layer.read_canonical_cached(DataType.FINANCIALS, "AAPL")
        assert hit is not None
        _, is_stale = hit
        assert is_stale is True, "stale fallback was laundered into a fresh canonical entry"

    async def test_price_stale_fallback_not_laundered(self, cache, tmp_path):
        db = str(tmp_path / "layer_test.db")
        price_payload = DataResult(
            data={
                "current_price": 311.52,
                "exchange": "NASDAQ",
                "quote_timestamp": int(datetime.now(tz=timezone.utc).timestamp()),
                "price_history": [
                    {
                        "date": "2026-06-08",
                        "open": 308.0,
                        "high": 315.0,
                        "low": 308.0,
                        "close": 313.8,
                        "volume": 1e7,
                    }
                ],
            },
            provider="good",
            ticker="AAPL",
            data_type=DataType.PRICE,
            timestamp=datetime.now(tz=timezone.utc),
        )
        good = MockProvider("good", [DataType.PRICE], result=price_payload)
        await DataLayer([good], cache).fetch_canonical(DataType.PRICE, "AAPL")

        await self._backdate_all(db, "AAPL", hours=25)

        layer = DataLayer(
            [MockProvider("fail", [DataType.PRICE], raises=ProviderError("down"))], cache
        )
        result = await layer.fetch_canonical(DataType.PRICE, "AAPL")
        assert result is not None

        hit = await layer.read_canonical_cached(DataType.PRICE, "AAPL")
        assert hit is not None
        _, is_stale = hit
        assert is_stale is True, "stale PRICE fallback was laundered into a fresh canonical entry"


class TestClose:
    """P3 Track 2: DataLayer.close() public method (T9)."""

    async def test_close_is_safe_to_call(self, cache):
        layer = DataLayer([MockProvider("mock", ["financials"])], cache)
        await layer.close()  # first close: actually closes the cache
        # Second close must not raise — DataCache.close is already idempotent,
        # and DataLayer.close just delegates to it.
        await layer.close()


# ---------------------------------------------------------------------------
# fetch_historical helpers
# ---------------------------------------------------------------------------


def _make_data_result(ticker: str = "AAPL", year: int = 2024) -> DataResult:
    return DataResult(
        data={"revenue": 100e9 + year, "year": year},
        provider="mock",
        ticker=ticker,
        data_type="financials",
        timestamp=datetime.now(tz=timezone.utc),
    )


def _make_multi_year_data_result(ticker: str = "AAPL", years: int = 5) -> DataResult:
    """Provider packs multi-year data inside a single DataResult."""
    yearly = [{"revenue": 100e9 + y, "year": 2020 + y} for y in range(years)]
    return DataResult(
        data={"yearly_data": yearly},
        provider="mock",
        ticker=ticker,
        data_type="financials",
        timestamp=datetime.now(tz=timezone.utc),
    )


class TestFetchHistorical:
    @pytest.mark.asyncio
    async def test_fetch_historical_returns_list_of_data_results(self):
        mock_provider = MagicMock(spec=DataProvider)
        mock_provider.name = "mock"
        mock_provider.capabilities.return_value = ["financials"]
        mock_provider.fetch = AsyncMock(return_value=_make_multi_year_data_result("AAPL", 5))

        mock_cache = MagicMock(spec=DataCache)
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()

        layer = DataLayer(providers=[mock_provider], cache=mock_cache)
        results = await layer.fetch_historical("financials", "AAPL", years=5)

        assert isinstance(results, list)
        assert len(results) == 5
        for i, r in enumerate(results):
            assert r.data["year"] == 2020 + i
            assert r.data["revenue"] == 100e9 + i
            assert r.provider == "mock"
            assert r.ticker == "AAPL"
            assert r.data_type == "financials"
        mock_provider.fetch.assert_called_once_with("AAPL", "financials", years=5)

    @pytest.mark.asyncio
    async def test_fetch_historical_falls_back_to_next_provider(self):
        failing_provider = MagicMock(spec=DataProvider)
        failing_provider.name = "failing"
        failing_provider.capabilities.return_value = ["financials"]
        failing_provider.fetch = AsyncMock(side_effect=ProviderError("down"))

        good_provider = MagicMock(spec=DataProvider)
        good_provider.name = "good"
        good_provider.capabilities.return_value = ["financials"]
        good_provider.fetch = AsyncMock(return_value=_make_multi_year_data_result("AAPL", 3))

        mock_cache = MagicMock(spec=DataCache)
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()

        layer = DataLayer(providers=[failing_provider, good_provider], cache=mock_cache)
        results = await layer.fetch_historical("financials", "AAPL", years=3)

        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_fetch_historical_skips_unsupported_providers(self):
        price_only = MagicMock(spec=DataProvider)
        price_only.name = "price_only"
        price_only.capabilities.return_value = ["price"]

        full = MagicMock(spec=DataProvider)
        full.name = "full"
        full.capabilities.return_value = ["financials"]
        full.fetch = AsyncMock(return_value=_make_multi_year_data_result("AAPL", 1))

        mock_cache = MagicMock(spec=DataCache)
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()

        layer = DataLayer(providers=[price_only, full], cache=mock_cache)
        results = await layer.fetch_historical("financials", "AAPL", years=1)

        assert len(results) == 1
        price_only.fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_historical_single_year_fallback(self):
        mock_provider = MagicMock(spec=DataProvider)
        mock_provider.name = "mock"
        mock_provider.capabilities.return_value = ["financials"]
        mock_provider.fetch = AsyncMock(return_value=_make_data_result())

        mock_cache = MagicMock(spec=DataCache)
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()

        layer = DataLayer(providers=[mock_provider], cache=mock_cache)
        results = await layer.fetch_historical("financials", "AAPL", years=5)

        assert isinstance(results, list)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_fetch_historical_all_fail_returns_empty(self):
        failing = MagicMock(spec=DataProvider)
        failing.name = "failing"
        failing.capabilities.return_value = ["financials"]
        failing.fetch = AsyncMock(side_effect=ProviderError("down"))

        mock_cache = MagicMock(spec=DataCache)
        mock_cache.get = AsyncMock(return_value=None)

        layer = DataLayer(providers=[failing], cache=mock_cache)
        results = await layer.fetch_historical("financials", "AAPL", years=5)

        assert results == []

    @pytest.mark.asyncio
    async def test_fetch_historical_all_fail_returns_stale_cache(self, cache, tmp_path):
        import aiosqlite
        from datetime import timedelta

        historical = DataResult(
            data={
                "yearly_data": [
                    {"revenue": 100.0, "fiscal_year": "2025-12-31"},
                    {"revenue": 110.0, "fiscal_year": "2024-12-31"},
                ]
            },
            provider="fmp",
            ticker="AAPL",
            data_type=DataType.FINANCIALS,
            timestamp=datetime.now(tz=timezone.utc),
        )
        cache_key = "AAPL:historical:financials:5"
        await cache.set(DataType.HISTORICAL, cache_key, historical)
        old_time = (datetime.now(tz=timezone.utc) - timedelta(days=2)).isoformat()
        async with aiosqlite.connect(str(tmp_path / "layer_test.db")) as conn:
            await conn.execute(
                "UPDATE cache SET cached_at = ? WHERE data_type = ? AND ticker = ?",
                (old_time, raw_slot_key(DataType.HISTORICAL), cache_key),
            )
            await conn.commit()

        failing = MagicMock(spec=DataProvider)
        failing.name = "failing"
        failing.capabilities.return_value = ["financials"]
        failing.fetch = AsyncMock(side_effect=ProviderError("down"))

        layer = DataLayer(providers=[failing], cache=cache)
        results = await layer.fetch_historical("financials", "AAPL", years=5)

        assert len(results) == 2
        assert results[0].data["revenue"] == 100.0
        assert any("Historical data sources failed" in w for w in results[0].warnings)


# ---------------------------------------------------------------------------
# 门一 Step 3/4: fetch_quote + fetch_price PROPAGATE provider failure
# (unlike fetch(), which swallows it into a generic error DataResult).
# ---------------------------------------------------------------------------


class TestFetchQuoteRaises:
    async def test_returns_first_success(self, cache):
        p = MockProvider("fmp", ["quote"], result=_make_result(data_type="quote", provider="fmp"))
        layer = DataLayer([p], cache)
        result = await layer.fetch_quote("AAPL")
        assert result.provider == "fmp"

    async def test_falls_through_on_provider_error(self, cache):
        p1 = MockProvider("fmp", ["quote"], raises=ProviderError("fmp down"))
        p2 = MockProvider(
            "yfinance", ["quote"], result=_make_result(data_type="quote", provider="yfinance")
        )
        layer = DataLayer([p1, p2], cache)
        result = await layer.fetch_quote("AAPL")
        assert result.provider == "yfinance"

    async def test_raises_last_error_when_all_fail(self, cache):
        p1 = MockProvider("fmp", ["quote"], raises=ProviderError("fmp down"))
        p2 = MockProvider("yfinance", ["quote"], raises=ProviderError("429 Too Many Requests"))
        layer = DataLayer([p1, p2], cache)
        with pytest.raises(ProviderError, match="429"):
            await layer.fetch_quote("AAPL")

    async def test_raises_when_no_quote_capable_provider(self, cache):
        p = MockProvider("x", ["financials"])
        layer = DataLayer([p], cache)
        with pytest.raises(ProviderError, match="No QUOTE"):
            await layer.fetch_quote("AAPL")


class TestFetchPriceRaises:
    async def test_caches_success_and_returns(self, cache):
        p = MockProvider(
            "yfinance", ["price"], result=_make_result(data_type="price", provider="yfinance")
        )
        layer = DataLayer([p], cache)
        r1 = await layer.fetch_price("AAPL")
        assert r1.provider == "yfinance"
        assert p.fetch_called == 1
        # Second call is a fresh-cache hit — provider not re-invoked.
        await layer.fetch_price("AAPL")
        assert p.fetch_called == 1

    async def test_raises_last_error_when_all_fail_no_cache(self, cache):
        p = MockProvider("yfinance", ["price"], raises=ProviderError("Symbol delisted"))
        layer = DataLayer([p], cache)
        with pytest.raises(ProviderError, match="delisted"):
            await layer.fetch_price("AAPL")

    async def test_raises_when_no_price_capable_provider(self, cache):
        p = MockProvider("x", ["financials"])
        layer = DataLayer([p], cache)
        with pytest.raises(ProviderError, match="No PRICE"):
            await layer.fetch_price("AAPL")


def _price_result(provider: str = "mock") -> DataResult:
    return DataResult(
        data={
            "current_price": 175.0,
            "price_history": [
                {"date": "2026-05-20", "open": 170, "high": 171, "low": 169, "close": 170},
                {"date": "2026-05-21", "open": 171, "high": 176, "low": 170, "close": 175},
            ],
        },
        provider=provider,
        ticker="AAPL",
        data_type="price",
        timestamp=datetime.now(tz=timezone.utc),
    )


class TestFetchCanonical:
    """ADR-0006: DataLayer.fetch_canonical is the one normalization关卡 —
    raw fetch → normalize → versioned canonical cache, typed output."""

    async def test_price_returns_normalized_price(self, cache):
        p = MockProvider("mock", ["price"], result=_price_result())
        layer = DataLayer([p], cache)
        out = await layer.fetch_canonical("price", "AAPL")
        assert isinstance(out, NormalizedPrice)
        assert out.current_price == 175.0
        assert out.provenance.provider == "mock"
        assert out.provenance.from_cache is False

    async def test_price_divergence_stamps_structured_degraded_marker(self, cache):
        class PriceProvider(MockProvider):
            def __init__(self, name_: str, price: float):
                super().__init__(
                    name_,
                    ["price", "quote"],
                    result=DataResult(
                        data={"current_price": price, "price": price, "price_history": []},
                        provider=name_,
                        ticker="AAPL",
                        data_type="price",
                        timestamp=datetime.now(tz=timezone.utc),
                    ),
                )

        layer = DataLayer([PriceProvider("fmp", 100.0), PriceProvider("yfinance", 50.0)], cache)

        out = await layer.fetch_canonical("price", "AAPL")

        assert degraded_price_divergence("current_price") in out.provenance.degraded

    async def test_price_circuit_open_propagates_to_provenance_degraded(self, cache):
        health = ProviderHealth(failure_threshold=1, base_cooldown_s=600)
        health.record_failure("fmp", rate_limited=True)
        fmp = MockProvider("fmp", ["price"], result=_price_result(provider="fmp"))
        yfinance = MockProvider("yfinance", ["price"], result=_price_result(provider="yfinance"))
        layer = DataLayer([fmp, yfinance], cache, health=health)

        out = await layer.fetch_canonical("price", "AAPL")

        assert out.provenance.provider == "yfinance"
        assert degraded_circuit_open("fmp") in out.provenance.degraded

    async def test_financials_returns_normalized_financials(self, cache):
        r = DataResult(
            data={"revenue": 1_000, "financial_currency": "USD"},
            provider="fmp",
            ticker="AAPL",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )
        layer = DataLayer([MockProvider("fmp", ["financials"], result=r)], cache)
        out = await layer.fetch_canonical("financials", "AAPL")
        assert isinstance(out, NormalizedFinancials)
        assert out.revenue == 1_000
        assert out.reporting_currency == "USD"

    async def test_cache_hit_marks_from_cache_and_skips_provider(self, cache):
        p = MockProvider("mock", ["price"], result=_price_result())
        layer = DataLayer([p], cache)
        await layer.fetch_canonical("price", "AAPL")
        assert p.fetch_called == 1
        second = await layer.fetch_canonical("price", "AAPL")
        assert isinstance(second, NormalizedPrice)
        assert second.provenance.from_cache is True
        assert p.fetch_called == 1  # served from canonical cache, no refetch

    async def test_cross_validate_warnings_carried_onto_canonical(self, cache):
        # Two FINANCIALS providers disagree on revenue → cross_validate warns;
        # the warning must survive the normalization boundary (ADR-0006 §5 待定).
        r1 = DataResult(
            data={"revenue": 100_000_000, "financial_currency": "USD"},
            provider="fmp",
            ticker="AAPL",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )
        r2 = DataResult(
            data={"revenue": 150_000_000, "financial_currency": "USD"},  # 33% off
            provider="finnhub",
            ticker="AAPL",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )
        layer = DataLayer(
            [MockProvider("fmp", ["financials"], r1), MockProvider("finnhub", ["financials"], r2)],
            cache,
        )
        out = await layer.fetch_canonical("financials", "AAPL")
        assert any("revenue" in w and "discrepancy" in w for w in out.warnings)

    async def test_key_field_divergence_stamps_structured_degraded_marker(self, cache):
        # BUG-007: a KEY-field (revenue) cross-provider divergence beyond
        # tolerance must reach NormalizedFinancials.provenance.degraded as a
        # STRUCTURED marker (so dcf_seed/comps can react programmatically), IN
        # ADDITION to the existing free-text warning.
        r1 = DataResult(
            data={"revenue": 100_000_000, "financial_currency": "USD"},
            provider="fmp",
            ticker="AAPL",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )
        r2 = DataResult(
            data={"revenue": 150_000_000, "financial_currency": "USD"},  # 33% off
            provider="finnhub",
            ticker="AAPL",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )
        layer = DataLayer(
            [MockProvider("fmp", ["financials"], r1), MockProvider("finnhub", ["financials"], r2)],
            cache,
        )
        out = await layer.fetch_canonical("financials", "AAPL")
        assert degraded_provider_divergence("revenue") in out.provenance.degraded
        # Primary (FMP) value still flows — number not dropped, just flagged.
        assert out.revenue == 100_000_000
        # The free-text warning is STILL present alongside the structured marker.
        assert any("revenue" in w and "discrepancy" in w for w in out.warnings)

    async def test_key_field_agreement_no_divergence_marker(self, cache):
        # Non-divergent case: providers agree within tolerance → no structured
        # divergence marker on provenance.degraded.
        r1 = DataResult(
            data={"revenue": 100_000_000, "financial_currency": "USD"},
            provider="fmp",
            ticker="AAPL",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )
        r2 = DataResult(
            data={"revenue": 105_000_000, "financial_currency": "USD"},  # ~5%, within 15%
            provider="finnhub",
            ticker="AAPL",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )
        layer = DataLayer(
            [MockProvider("fmp", ["financials"], r1), MockProvider("finnhub", ["financials"], r2)],
            cache,
        )
        out = await layer.fetch_canonical("financials", "AAPL")
        assert not any(
            m.startswith(f"{DEGRADED_PROVIDER_DIVERGENCE_PREFIX}:") for m in out.provenance.degraded
        )

    async def test_unsupported_type_raises_value_error(self, cache):
        layer = DataLayer([MockProvider("mock", ["news"])], cache)
        with pytest.raises(ValueError, match="PRICE / FINANCIALS"):
            await layer.fetch_canonical("news", "AAPL")

    async def test_all_providers_fail_raises_provider_error(self, cache):
        failing = MockProvider("bad", ["financials"], raises=ProviderError("boom"))
        layer = DataLayer([failing], cache)
        # BUG-046: neutral English error at the data layer.
        with pytest.raises(ProviderError, match="all providers failed"):
            await layer.fetch_canonical("financials", "AAPL")


# ---------------------------------------------------------------------------
# BUG-045: the ProviderHealth circuit breaker is actually wired into every
# provider loop, so a tripped (rate-limited / repeatedly-failing) provider is
# skipped on the NEXT call instead of paying its full timeout again.
# ---------------------------------------------------------------------------


class TestCircuitBreakerWiring:
    async def test_default_layer_has_a_breaker(self, cache):
        """No explicit ``health`` arg → DataLayer still owns a breaker."""
        layer = DataLayer([MockProvider("fmp", ["price"])], cache)
        assert isinstance(layer._health, ProviderHealth)

    async def test_rate_limited_provider_is_skipped_next_call(self, cache):
        """A 429 trips the breaker immediately; the next PRICE call skips the
        rate-limited provider entirely (no second timeout) and the chain's next
        provider serves the request."""
        health = ProviderHealth(failure_threshold=3, base_cooldown_s=600)
        yf = MockProvider(
            "yfinance", ["price"], raises=ProviderError("Too Many Requests. Rate limited.")
        )
        fmp = MockProvider("fmp", ["price"], result=_make_result(data_type="price", provider="fmp"))
        layer = DataLayer([yf, fmp], cache, health=health)

        # Call 1: yfinance 429s (1 attempt), FMP serves it. Breaker now open on yfinance.
        r1 = await layer.fetch("price", "NVDA")
        assert r1.provider == "fmp"
        assert yf.fetch_called == 1

        # Call 2 (fresh ticker so cache is cold): yfinance is in cooldown and is
        # NOT re-attempted — that's the whole point of BUG-045.
        r2 = await layer.fetch("price", "TSLA")
        assert r2.provider == "fmp"
        assert yf.fetch_called == 1  # still 1 — skipped, did not pay the timeout
        assert fmp.fetch_called == 2

    async def test_consecutive_failures_trip_breaker(self, cache):
        """Below threshold the provider is retried; at threshold it trips and is
        skipped on the next call."""
        health = ProviderHealth(failure_threshold=2, base_cooldown_s=600)
        bad = MockProvider("bad", ["price"], raises=ProviderError("network error"))
        good = MockProvider(
            "good", ["price"], result=_make_result(data_type="price", provider="good")
        )
        layer = DataLayer([bad, good], cache, health=health)

        await layer.fetch("price", "AAA")  # bad fails (1), good serves
        assert bad.fetch_called == 1
        await layer.fetch("price", "BBB")  # bad fails (2 == threshold → trips), good serves
        assert bad.fetch_called == 2
        await layer.fetch("price", "CCC")  # bad in cooldown → skipped
        assert bad.fetch_called == 2
        assert good.fetch_called == 3

    async def test_success_closes_circuit_and_resets(self, cache):
        """A success between failures resets the consecutive-failure counter, so
        the breaker does not trip mid-way."""
        health = ProviderHealth(failure_threshold=2, base_cooldown_s=600)
        layer = DataLayer([MockProvider("p", ["price"])], cache, health=health)
        # Pre-seed one failure, then a real successful fetch should reset it.
        health.record_failure("p", rate_limited=False)
        assert health.snapshot("p").consecutive_failures == 1
        await layer.fetch("price", "AAA")
        assert health.snapshot("p").consecutive_failures == 0

    async def test_lone_healthy_provider_never_gated(self, cache):
        """Safety: the breaker must never skip the only available provider — a
        healthy provider's ``is_available`` is always True, so a single-provider
        chain is unaffected by the breaker."""
        only = MockProvider(
            "only", ["price"], result=_make_result(data_type="price", provider="only")
        )
        layer = DataLayer([only], cache)
        r = await layer.fetch("price", "AAA")
        assert r.provider == "only"
        assert only.fetch_called == 1

    async def test_breaker_shared_across_fetch_methods(self, cache):
        """A trip recorded via fetch() also gates fetch_quote()/fetch_price() —
        the breaker is one instance shared by every loop."""
        health = ProviderHealth(failure_threshold=1, base_cooldown_s=600)
        # Trip 'fmp' directly (as a rate-limit) before any call.
        health.record_failure("fmp", rate_limited=True)

        fmp = MockProvider("fmp", ["price", "quote"], result=_make_result(provider="fmp"))
        yf = MockProvider("yfinance", ["price", "quote"], result=_make_result(provider="yfinance"))
        layer = DataLayer([fmp, yf], cache, health=health)

        price = await layer.fetch("price", "AAA")
        assert price.provider == "yfinance"
        quote = await layer.fetch_quote("AAA")
        assert quote.provider == "yfinance"
        assert fmp.fetch_called == 0  # gated on both paths


class TestCanonicalSingleFlight:
    """fetch_canonical coalesces concurrent slow-path callers per (type, ticker).

    These isolate the coalescing wrapper by stubbing ``_fetch_canonical_uncached``
    (the provider→normalize→cache body, already covered elsewhere) so the test
    asserts the in-flight registry behaviour, not the normalize path.
    """

    async def test_concurrent_canonical_fetches_coalesce_to_one(self, cache):
        """A refresh fan-out (or mashed button) for one ticker hits the slow
        path once — concurrent callers ride a single in-flight Task."""
        layer = DataLayer([MockProvider("mock", ["price"])], cache)
        calls = 0
        sentinel = object()

        async def slow_uncached(data_type, ticker, **kwargs):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.02)  # hold the in-flight window open
            return sentinel

        layer._fetch_canonical_uncached = slow_uncached  # type: ignore[method-assign]

        results = await asyncio.gather(
            *[layer.fetch_canonical(DataType.PRICE, "AAPL") for _ in range(6)]
        )
        assert calls == 1
        assert all(r is sentinel for r in results)

    async def test_inflight_entry_evicts_after_completion(self, cache):
        """The registry empties after a flight completes, so a later miss starts
        a fresh fetch rather than awaiting a dead Task."""
        layer = DataLayer([MockProvider("mock", ["price"])], cache)
        calls = 0

        async def counting_uncached(data_type, ticker, **kwargs):
            nonlocal calls
            calls += 1
            return object()

        layer._fetch_canonical_uncached = counting_uncached  # type: ignore[method-assign]

        await layer.fetch_canonical(DataType.PRICE, "AAPL")
        assert layer._inflight_canonical == {}
        # Stub never writes the cache, so the next call is a cold miss → 2nd flight.
        await layer.fetch_canonical(DataType.PRICE, "AAPL")
        assert calls == 2

    async def test_distinct_tickers_do_not_coalesce(self, cache):
        """Single-flight keys on (type, ticker): different tickers run in parallel,
        each its own flight."""
        layer = DataLayer([MockProvider("mock", ["price"])], cache)
        seen: list[str] = []

        async def recording_uncached(data_type, ticker, **kwargs):
            seen.append(ticker)
            await asyncio.sleep(0.01)
            return object()

        layer._fetch_canonical_uncached = recording_uncached  # type: ignore[method-assign]

        await asyncio.gather(
            layer.fetch_canonical(DataType.PRICE, "AAPL"),
            layer.fetch_canonical(DataType.PRICE, "MSFT"),
        )
        assert sorted(seen) == ["AAPL", "MSFT"]


def _adr_financials_result(ticker: str = "TSM") -> DataResult:
    """FMP-shape TSM financials: TWD reporting line items, USD market quote."""
    return DataResult(
        data={
            "revenue": 4_113_789_591_000,  # TWD
            "net_income": 1_933_578_784_000,  # TWD
            "operating_income": 1_900_000_000_000,  # TWD
            "depreciation_amortization": 600_000_000_000,  # TWD
            "total_debt": 1_094_130_170_000,  # TWD
            "total_cash": 3_382_860_143_000,  # TWD
            "market_cap": 2_213_589_664_000,  # USD (quote currency)
            "shares_outstanding": 5_186_000_000,
            "current_price": 427.0,  # USD
            "financial_currency": "TWD",
            "quote_currency": "USD",
        },
        provider="fmp",
        ticker=ticker,
        data_type="financials",
        timestamp=datetime.now(tz=timezone.utc),
    )


class TestCanonicalFxNormalization:
    """class A: the canonical layer is the one FX关卡 (ADR-0006). A foreign ADR
    (reporting≠quote) is made single-currency here so no downstream consumer
    (the /financials route, Coverage, the AI orchestrator) can form a
    cross-currency EV — the live -75.1B TSM bug (probe 2026-06-09)."""

    async def test_adr_financials_converted_to_quote_currency(self, cache, monkeypatch):
        async def fake_fx(ccy, *, fmp_api_key=None):
            return 0.03176 if ccy.upper() == "TWD" else 1.0

        monkeypatch.setattr("finrobot.engine.data.layer.fetch_fx_rate_to_usd", fake_fx)
        layer = DataLayer(
            [MockProvider("fmp", ["financials"], result=_adr_financials_result())], cache
        )

        out = await layer.fetch_canonical("financials", "TSM")

        assert isinstance(out, NormalizedFinancials)
        # Single currency after the gate: both tags collapse to the quote currency.
        assert out.reporting_currency == "USD"
        assert out.quote_currency == "USD"
        # Reporting-currency legs scaled into USD; the USD quote is left untouched.
        assert out.total_debt == pytest.approx(1_094_130_170_000 * 0.03176)
        assert out.total_cash == pytest.approx(3_382_860_143_000 * 0.03176)
        assert out.revenue == pytest.approx(4_113_789_591_000 * 0.03176)
        assert out.market_cap == 2_213_589_664_000
        assert DEGRADED_FX_NORMALIZED in out.provenance.degraded

    async def test_us_issuer_skips_fx_fetch(self, cache, monkeypatch):
        """reporting == quote == USD: the gate is a no-op and never hits FX."""
        called = False

        async def fake_fx(ccy, *, fmp_api_key=None):
            nonlocal called
            called = True
            return 1.0

        monkeypatch.setattr("finrobot.engine.data.layer.fetch_fx_rate_to_usd", fake_fx)
        result = DataResult(
            data={"revenue": 1_000, "financial_currency": "USD"},
            provider="fmp",
            ticker="AAPL",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )
        layer = DataLayer([MockProvider("fmp", ["financials"], result=result)], cache)

        out = await layer.fetch_canonical("financials", "AAPL")

        assert isinstance(out, NormalizedFinancials)
        assert out.reporting_currency == "USD"
        assert called is False
        assert DEGRADED_FX_NORMALIZED not in out.provenance.degraded

    async def test_fx_unavailable_degrades_instead_of_failing(self, cache, monkeypatch):
        """FX down: leave the snapshot un-converted but flag it — the FinancialData
        model invariant (class B) then withholds the EV. Never fail the fetch."""

        async def boom(ccy, *, fmp_api_key=None):
            raise ProviderError("no spot FX quote for TWD→USD")

        monkeypatch.setattr("finrobot.engine.data.layer.fetch_fx_rate_to_usd", boom)
        layer = DataLayer(
            [MockProvider("fmp", ["financials"], result=_adr_financials_result())], cache
        )

        out = await layer.fetch_canonical("financials", "TSM")

        # Un-converted (still TWD) but explicitly degraded — and it did NOT raise.
        assert isinstance(out, NormalizedFinancials)
        assert out.reporting_currency == "TWD"
        assert out.total_debt == 1_094_130_170_000
        assert DEGRADED_FX_UNAVAILABLE in out.provenance.degraded
