import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from finrobot.engine.data.cache import DataCache, raw_slot_key
from finrobot.engine.data.interface import (
    DataProvider,
    DataResult,
    ProviderError,
    RateLimitedProviderError,
    is_rate_limit_error,
)
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

    async def test_kwargs_variants_get_distinct_cache_slots(self, cache):
        """Cache identity must include every kwarg that varies the provider
        payload. Live bug: /api/sentiment days=7 vs days=30 both reached
        fetch(SENTIMENT, ticker, days_back=…) but cached by ticker alone, so a
        30-day request served the cached 7-day aggregate until TTL."""

        class EchoKwargsProvider(MockProvider):
            async def fetch(self, ticker: str, data_type: str, **kwargs) -> DataResult:
                self.fetch_called += 1
                return DataResult(
                    data={"echo": dict(kwargs)},
                    provider=self._name,
                    ticker=ticker,
                    data_type=data_type,
                    timestamp=datetime.now(tz=timezone.utc),
                )

        provider = EchoKwargsProvider("adanos", ["sentiment"])
        layer = DataLayer([provider], cache)

        r7 = await layer.fetch("sentiment", "AAPL", days_back=7)
        r30 = await layer.fetch("sentiment", "AAPL", days_back=30)
        assert r7.data["echo"] == {"days_back": 7}
        assert r30.data["echo"] == {"days_back": 30}, "30d window served the 7d slot"
        assert provider.fetch_called == 2

        # Same kwargs again → cache hit, provider not called a third time.
        again = await layer.fetch("sentiment", "AAPL", days_back=7)
        assert provider.fetch_called == 2
        assert again.data["echo"] == {"days_back": 7}

    async def test_stale_cache_calls_provider_and_updates_cache(self, cache, tmp_path):
        import aiosqlite
        from datetime import timedelta

        provider = MockProvider("mock", ["financials"])
        layer = DataLayer([provider], cache)
        await layer.fetch("financials", "AAPL")

        # Backdate cache entry
        from finrobot.engine.data.cache import raw_slot_key

        old_time = (datetime.now(tz=timezone.utc) - timedelta(hours=25)).isoformat()
        async with aiosqlite.connect(str(tmp_path / "layer_test.db")) as conn:
            await conn.execute(
                "UPDATE cache SET cached_at = ? WHERE data_type = ? AND ticker = ?",
                (old_time, raw_slot_key("financials"), "AAPL"),
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
        from finrobot.engine.data.cache import raw_slot_key

        old_time = (datetime.now(tz=timezone.utc) - timedelta(hours=25)).isoformat()
        async with aiosqlite.connect(str(tmp_path / "layer_test.db")) as conn:
            await conn.execute(
                "UPDATE cache SET cached_at = ? WHERE data_type = ? AND ticker = ?",
                (old_time, raw_slot_key("financials"), "AAPL"),
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
        assert any("p3" in w for w in result.warnings), (
            f"Third provider discrepancy not in warnings: {result.warnings}"
        )

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
        assert any("cross-validation skipped" in w.lower() for w in result.warnings)
        assert p3.fetch_called > 0

    async def test_all_none_secondary_not_counted_as_validation(self, cache):
        """An all-None secondary ({"revenue": None, ...}) is non-empty, so the
        bare `if not result.data` guard used to wave it through; cross_validate
        then skipped every None field and returned [] = a phantom "two providers
        agree". It must instead be flagged "no comparable ... cross-validation
        skipped" and NOT count as a validating secondary."""
        r1 = DataResult(
            data={"revenue": 100_000, "net_income": 20_000},
            provider="p1",
            ticker="TEST",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )
        r2_all_none = DataResult(
            data={"revenue": None, "net_income": None, "market_cap": None, "total_cash": None},
            provider="p2",
            ticker="TEST",
            data_type="financials",
            timestamp=datetime.now(tz=timezone.utc),
        )
        p1 = MockProvider("p1", ["financials"], result=r1)
        p2 = MockProvider("p2", ["financials"], result=r2_all_none)
        layer = DataLayer([p1, p2], cache)
        result = await layer.fetch("financials", "TEST")
        # Primary still wins and flows untouched.
        assert result.provider == "p1"
        assert result.data["revenue"] == 100_000
        # The all-None secondary is honestly flagged as non-comparable — NOT
        # silently accepted as agreement (the discriminating assertion: the
        # pre-fix code emitted neither this skip warning nor any discrepancy).
        assert any("cross-validation skipped" in w.lower() for w in result.warnings)
        assert not any("discrepancy" in w.lower() for w in result.warnings)

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
        assert expected_marker in normalized.provenance.degraded, (
            f"Expected '{expected_marker}' in degraded={normalized.provenance.degraded}"
        )
        assert expected_marker.startswith(DEGRADED_CIRCUIT_OPEN_PREFIX)

    async def test_circuit_open_not_persisted_to_raw_cache(self, cache):
        """Item 6: fetch() stamps circuit_open on the RETURNED result but caches
        the row clean — which providers were in cooldown is a point-in-time fact
        about this fetch, not the data. Freezing it for the whole TTL would flag a
        recovered provider as down for 24h."""
        health = self._tripped_health("fmp")
        fmp = MockProvider("fmp", ["financials"])
        yf = MockProvider("yfinance", ["financials"])
        layer = DataLayer([fmp, yf], cache, health=health)

        result = await layer.fetch("financials", "AAPL")
        assert "fmp" in result.circuit_open_providers  # immediate caller sees it
        assert fmp.fetch_called == 0

        cached = await cache.get(DataType.FINANCIALS, "AAPL")
        assert cached is not None
        assert cached.data.circuit_open_providers == []  # cached row is clean

    async def test_circuit_open_marker_not_persisted_to_canonical_cache(self, cache):
        """Item 6: the canonical degraded_circuit_open marker reaches the immediate
        caller but must NOT be frozen into the cached canonical row, or a later
        read (breaker since recovered) keeps reading degraded for the full TTL."""
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

        fetched = await layer.fetch_canonical(DataType.FINANCIALS, "AAPL")
        assert degraded_circuit_open("fmp") in fetched.provenance.degraded

        # The cached canonical row, read back (the breaker may have recovered), is
        # clean of the ephemeral marker — data-provenance markers would persist.
        cached = await layer.read_canonical_cached(DataType.FINANCIALS, "AAPL")
        assert cached is not None
        cached_norm, _ = cached
        assert degraded_circuit_open("fmp") not in cached_norm.provenance.degraded


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

        # Backdate the canonical slot past the 24h FINANCIALS TTL. The slot is
        # provider-qualified (BUG: provider swap could overwrite a different
        # caliber under one shared key — fixed by folding the winning provider
        # into the slot), so target the 'mock' provider's slot the fetch wrote.
        old_time = (datetime.now(tz=timezone.utc) - timedelta(hours=25)).isoformat()
        async with aiosqlite.connect(str(tmp_path / "layer_test.db")) as conn:
            await conn.execute(
                "UPDATE cache SET cached_at = ? WHERE data_type = ? AND ticker = ?",
                (old_time, canonical_key(DataType.FINANCIALS, "mock"), "AAPL"),
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


class TestCorruptCacheSelfHeal:
    """Bug 13: DataLayer.fetch / fetch_canonical read the cache as their FIRST
    step — a corrupt row that raised there never reached the provider loop and
    never got overwritten, bricking the (data_type, ticker) slot until the
    30-day evict. A corrupt row must read as a miss, get deleted, and the
    provider chain must repopulate the slot."""

    async def test_fetch_skips_corrupt_raw_row_and_hits_provider(self, cache):
        await cache._set_slot(raw_slot_key("financials"), "AAPL", "{corrupt payload")
        provider = MockProvider("mock", ["financials"])
        layer = DataLayer([provider], cache)

        result = await layer.fetch("financials", "AAPL")
        assert provider.fetch_called == 1
        assert result.provider == "mock"

        # Slot healed: next read serves the fresh provider row from cache.
        provider.fetch_called = 0
        again = await layer.fetch("financials", "AAPL")
        assert provider.fetch_called == 0
        assert again.ticker == "AAPL"

    async def test_fetch_canonical_heals_corrupt_canonical_row(self, cache):
        await cache.set_canonical(DataType.PRICE, "AAPL", '{"not": "a NormalizedPrice"}')
        p = MockProvider("mock", ["price", "quote"], result=_price_result())
        layer = DataLayer([p], cache)

        out = await layer.fetch_canonical(DataType.PRICE, "AAPL")
        assert isinstance(out, NormalizedPrice)
        assert out.current_price == 175.0
        assert p.fetch_called >= 1  # corrupt row fell through to the provider

        # Canonical slot repopulated with a valid contract.
        hit = await layer.read_canonical_cached(DataType.PRICE, "AAPL")
        assert hit is not None
        normalized, is_stale = hit
        assert isinstance(normalized, NormalizedPrice)
        assert is_stale is False

    async def test_read_canonical_cached_corrupt_row_is_miss_and_deleted(self, cache):
        await cache.set_canonical(DataType.PRICE, "AAPL", "{mangled json")
        layer = DataLayer([], cache)

        assert await layer.read_canonical_cached(DataType.PRICE, "AAPL") is None
        # Row physically gone — the underlying canonical slot reads as a miss.
        assert await cache.get_canonical(DataType.PRICE, "AAPL") is None


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


def _fin_caliber_result(provider: str, *, period_basis: str, revenue: float) -> DataResult:
    """A FINANCIALS DataResult whose CALIBER differs by provider, the way live
    sources do: FMP serves a TTM snapshot (Σ 4 quarters, with quarter-ends),
    yfinance serves the latest ANNUAL figure (no quarter-ends). The two are NOT
    interchangeable — mixing them silently mislabels the period."""
    data: dict = {
        "revenue": revenue,
        "period_basis": period_basis,
        "fiscal_year": "2025-09-27" if period_basis == "ttm" else "2024-09-28",
        "financial_currency": "USD",
    }
    if period_basis == "ttm":
        data["ttm_quarter_ends"] = ["2024-12-28", "2025-03-29", "2025-06-28", "2025-09-27"]
    return DataResult(
        data=data,
        provider=provider,
        ticker="AAPL",
        data_type=DataType.FINANCIALS,
        timestamp=datetime.now(tz=timezone.utc),
    )


class TestCanonicalFinancialsProviderKeying:
    """Regression: the canonical FINANCIALS slot folds in the WINNING provider.

    Before the fix the slot was ``financials:canonical:v<N>/<ticker>`` — provider
    NEITHER in the key NOR period-qualified. A silent provider swap (FMP
    rate-limited → yfinance fallback wins one run) overwrote a DIFFERENT-caliber
    snapshot (TTM vs annual, distinct period_basis / ttm_quarter_ends) under the
    SAME key, and a later read served a caliber the rest of the run didn't assume.
    Folding the winning provider into the slot isolates calibers while preserving
    the steady-state single-provider cache hit.
    """

    async def test_provider_swap_writes_distinct_slots_no_overwrite(self, cache):
        # Shared breaker so we can gate FMP to force the yfinance swap.
        health = ProviderHealth()
        fmp = MockProvider(
            "fmp",
            ["financials"],
            result=_fin_caliber_result("fmp", period_basis="ttm", revenue=391_000_000_000),
        )
        yf = MockProvider(
            "yfinance",
            ["financials"],
            result=_fin_caliber_result("yfinance", period_basis="annual", revenue=383_285_000_000),
        )
        layer = DataLayer([fmp, yf], cache, health=health)

        # Run 1: FMP wins → its TTM snapshot lands in the fmp-qualified slot.
        first = await layer.fetch_canonical(DataType.FINANCIALS, "AAPL")
        assert isinstance(first, NormalizedFinancials)
        assert first.provenance.provider == "fmp"
        assert first.period_basis == "ttm"
        assert first.ttm_quarter_ends  # FMP caliber carries quarter-ends

        # Run 2: FMP gated (breaker open) → yfinance wins. Clear the raw slot so
        # the provider walk actually runs (a fresh raw row would otherwise serve
        # FMP's cached raw payload regardless of the breaker). Its ANNUAL snapshot
        # MUST land in its OWN slot, NOT overwrite the fmp canonical slot.
        await cache._delete_slot(raw_slot_key("financials"), "AAPL")
        health.record_failure("fmp", rate_limited=True)
        assert health.is_available("fmp") is False
        second = await layer.fetch_canonical(DataType.FINANCIALS, "AAPL")
        assert second.provenance.provider == "yfinance"
        assert second.period_basis == "annual"
        assert not second.ttm_quarter_ends

        # BOTH calibers coexist in DISTINCT slots — the fmp TTM snapshot was not
        # clobbered by the yfinance annual one.
        from finrobot.engine.data.cache import canonical_key

        fmp_slot = await cache.get_canonical(DataType.FINANCIALS, "AAPL", provider="fmp")
        yf_slot = await cache.get_canonical(DataType.FINANCIALS, "AAPL", provider="yfinance")
        assert fmp_slot is not None and '"period_basis":"ttm"' in fmp_slot.payload_json
        assert yf_slot is not None and '"period_basis":"annual"' in yf_slot.payload_json
        assert canonical_key(DataType.FINANCIALS, "fmp") != canonical_key(
            DataType.FINANCIALS, "yfinance"
        )

    async def test_recovered_primary_serves_its_own_caliber_not_fallback(self, cache):
        """After FMP recovers, fetch_canonical must serve the FMP (TTM) slot —
        never the yfinance (annual) caliber written during the outage."""
        health = ProviderHealth()
        fmp = MockProvider(
            "fmp",
            ["financials"],
            result=_fin_caliber_result("fmp", period_basis="ttm", revenue=391_000_000_000),
        )
        yf = MockProvider(
            "yfinance",
            ["financials"],
            result=_fin_caliber_result("yfinance", period_basis="annual", revenue=383_285_000_000),
        )
        layer = DataLayer([fmp, yf], cache, health=health)

        # Outage run writes the yfinance annual slot.
        health.record_failure("fmp", rate_limited=True)
        await layer.fetch_canonical(DataType.FINANCIALS, "AAPL")
        # FMP recovers. Clear the raw slot (its 24h TTL would otherwise serve the
        # cached yfinance raw row to the next walk and re-derive yfinance) so the
        # recovered chain genuinely re-walks and FMP wins again.
        await cache._delete_slot(raw_slot_key("financials"), "AAPL")
        health.record_success("fmp")
        fmp.fetch_called = 0
        recovered = await layer.fetch_canonical(DataType.FINANCIALS, "AAPL")
        # Preferred slot (fmp) was empty → one fetch, then the FMP TTM caliber.
        assert fmp.fetch_called == 1
        assert recovered.provenance.provider == "fmp"
        assert recovered.period_basis == "ttm"

    async def test_same_provider_reread_hits_cache_no_thrash(self, cache):
        """The steady single-provider state must still HIT the canonical cache —
        provider-qualifying the slot must not regress cache efficiency."""
        health = ProviderHealth()
        fmp = MockProvider(
            "fmp",
            ["financials"],
            result=_fin_caliber_result("fmp", period_basis="ttm", revenue=391_000_000_000),
        )
        yf = MockProvider("yfinance", ["financials"])
        layer = DataLayer([fmp, yf], cache, health=health)

        await layer.fetch_canonical(DataType.FINANCIALS, "AAPL")  # prime fmp slot
        assert fmp.fetch_called == 1
        fmp.fetch_called = 0
        yf.fetch_called = 0

        # Re-read with the same healthy chain → preferred=fmp, slot fresh → HIT,
        # no provider walk at all.
        again = await layer.fetch_canonical(DataType.FINANCIALS, "AAPL")
        assert again.provenance.provider == "fmp"
        assert fmp.fetch_called == 0  # served from cache, no re-fetch
        assert yf.fetch_called == 0

    async def test_read_canonical_cached_survives_provider_swap(self, cache):
        """The stale-while-revalidate paint must still surface a last-known
        snapshot after a provider swap, even when the preferred provider's slot
        is the one that's empty (it reads the freshest slot across providers)."""
        health = ProviderHealth()
        yf = MockProvider(
            "yfinance",
            ["financials"],
            result=_fin_caliber_result("yfinance", period_basis="annual", revenue=383_285_000_000),
        )
        # Only yfinance is wired here, so the slot written is yfinance's; the
        # preferred provider for a chain that also had fmp would differ, but the
        # cache-only read must still find the yfinance snapshot.
        layer = DataLayer([yf], cache, health=health)
        await layer.fetch_canonical(DataType.FINANCIALS, "AAPL")

        hit = await layer.read_canonical_cached(DataType.FINANCIALS, "AAPL")
        assert hit is not None
        norm, _ = hit
        assert norm.provenance.provider == "yfinance"
        assert norm.period_basis == "annual"


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

    async def test_fetch_historical_cache_key_includes_kwargs(self, cache):
        """fetch_historical folds payload-varying kwargs into the cache key, so two
        distinct parameterisations never collide in one HISTORICAL slot (the
        sentiment days_back=7-vs-30 family). Guards any future extra kwarg threaded
        through to provider.fetch beyond the already-explicit ``years``."""
        p = MockProvider("mock", ["financials"])
        layer = DataLayer([p], cache)
        await layer.fetch_historical("financials", "AAPL", years=5, variant="a")
        # Same (years, kwargs) → cache hit, provider NOT re-called.
        await layer.fetch_historical("financials", "AAPL", years=5, variant="a")
        assert p.fetch_called == 1
        # Different kwarg → different slot → cache miss → provider re-called. Pre-fix
        # the key omitted kwargs, so variant="b" would wrongly hit the variant="a" slot.
        await layer.fetch_historical("financials", "AAPL", years=5, variant="b")
        assert p.fetch_called == 2


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
        """Config-shaped exhaustion (no QUOTE-capable provider at all) must NOT
        read as a rate-limit — quote_batch is allowed to tombstone here."""
        p = MockProvider("x", ["financials"])
        layer = DataLayer([p], cache)
        with pytest.raises(ProviderError, match="No QUOTE") as excinfo:
            await layer.fetch_quote("AAPL")
        assert is_rate_limit_error(excinfo.value) is False

    async def test_all_capable_providers_gated_raises_rate_limited(self, cache):
        """Bug 12: QUOTE-capable providers exist but ALL sit in an open
        circuit-breaker cooldown → the error must carry rate-limit semantics
        (RateLimitedProviderError) so quote_batch maps it to
        QuoteFetchRateLimited and preserves stale prices instead of writing a
        None tombstone over them."""
        health = ProviderHealth()
        health.record_failure("fmp", rate_limited=True)
        health.record_failure("yfinance", rate_limited=True)
        p1 = MockProvider("fmp", ["quote"])
        p2 = MockProvider("yfinance", ["quote"])
        layer = DataLayer([p1, p2], cache, health=health)

        with pytest.raises(RateLimitedProviderError, match="circuit-breaker cooldown"):
            await layer.fetch_quote("AAPL")
        assert p1.fetch_called == 0 and p2.fetch_called == 0  # gated, never attempted

    async def test_partial_gating_still_uses_available_provider(self, cache):
        """One provider gated, the other healthy → quote still resolves."""
        health = ProviderHealth()
        health.record_failure("fmp", rate_limited=True)
        p1 = MockProvider("fmp", ["quote"])
        p2 = MockProvider(
            "yfinance", ["quote"], result=_make_result(data_type="quote", provider="yfinance")
        )
        layer = DataLayer([p1, p2], cache, health=health)
        result = await layer.fetch_quote("AAPL")
        assert result.provider == "yfinance"
        assert p1.fetch_called == 0

    async def test_attempted_failure_beats_gated_signal(self, cache):
        """A real verdict from an attempted provider (delisted/not-found) wins
        over the gated-cooldown signal — that path may still tombstone."""
        health = ProviderHealth()
        health.record_failure("fmp", rate_limited=True)
        p1 = MockProvider("fmp", ["quote"])
        p2 = MockProvider("yfinance", ["quote"], raises=ProviderError("Symbol delisted"))
        layer = DataLayer([p1, p2], cache, health=health)
        with pytest.raises(ProviderError, match="delisted") as excinfo:
            await layer.fetch_quote("AAPL")
        assert is_rate_limit_error(excinfo.value) is False


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


class TestQuoteOnlyHistoryGraft:
    """Quote-only守卫 (2026-06-11): a provider can legitimately serve a live
    quote with ZERO history bars (Finnhub free tier: /quote works,
    /stock/candle is premium-403). That result must not blank the chart nor
    overwrite the bar-carrying cached row — stale-but-complete beats
    fresh-but-empty, flagged. Production trigger: FMP daily bandwidth
    exhausted + yfinance burst-429 → finnhub quote-only displaced the 1y
    history for every ticker."""

    @staticmethod
    def _quote_only_result(provider: str = "finnhub") -> DataResult:
        return DataResult(
            data={"current_price": 291.58, "price_history": [], "exchange": "NASDAQ"},
            provider=provider,
            ticker="AAPL",
            data_type="price",
            timestamp=datetime.now(tz=timezone.utc),
        )

    @staticmethod
    async def _backdate_raw_price(tmp_path, hours: float = 1.0) -> None:
        import aiosqlite
        from datetime import timedelta

        old_time = (datetime.now(tz=timezone.utc) - timedelta(hours=hours)).isoformat()
        async with aiosqlite.connect(str(tmp_path / "layer_test.db")) as conn:
            await conn.execute(
                "UPDATE cache SET cached_at = ? WHERE data_type = ? AND ticker = ?",
                (old_time, raw_slot_key("price"), "AAPL"),
            )
            await conn.commit()

    async def test_graft_carries_cached_bars_live_quote_and_warning(self, cache, tmp_path):
        seed = MockProvider("fmp", ["price"], result=_price_result(provider="fmp"))
        await DataLayer([seed], cache).fetch_price("AAPL")
        await self._backdate_raw_price(tmp_path)

        quote_only = MockProvider("finnhub", ["price"], result=self._quote_only_result())
        result = await DataLayer([quote_only], cache).fetch_price("AAPL")

        assert result.provider == "finnhub"
        assert result.data["current_price"] == 291.58  # live quote kept
        assert len(result.data["price_history"]) == 2  # bars grafted from cache
        assert result.stale_history is True
        assert result.from_stale_cache is False  # quote is live — only bars lag
        graft = next(w for w in result.warnings if "without price history" in w)
        assert "cached history" in graft

    async def test_graft_does_not_overwrite_cached_bar_row(self, cache, tmp_path):
        seed = MockProvider("fmp", ["price"], result=_price_result(provider="fmp"))
        await DataLayer([seed], cache).fetch_price("AAPL")
        await self._backdate_raw_price(tmp_path)

        quote_only = MockProvider("finnhub", ["price"], result=self._quote_only_result())
        layer = DataLayer([quote_only], cache)
        await layer.fetch_price("AAPL")

        # The bar-carrying row must survive, honestly stale — so this next read
        # walks the (hopefully recovered) chain again instead of serving a
        # fresh-looking quote-only row for the whole TTL.
        await layer.fetch_price("AAPL")
        assert quote_only.fetch_called == 2
        row = await cache.get(DataType.PRICE, "AAPL")
        assert row is not None
        assert len(row.data.data["price_history"]) == 2
        assert row.data.provider == "fmp"

    async def test_quote_only_does_not_short_circuit_chain(self, cache):
        """Chain order is FMP → Finnhub → yfinance (Finnhub ahead of yfinance is
        deliberate, for NEWS priority). A Finnhub quote-only partial success must
        NOT stop the PRICE walk — yfinance right behind it carries the full 1y
        history for free (the second half of the 2026-06-11 blank-chart bug:
        with FMP circuit-open the chain never reached yfinance)."""
        quote_only = MockProvider("finnhub", ["price"], result=self._quote_only_result())
        full = MockProvider("yfinance", ["price"], result=_price_result(provider="yfinance"))
        layer = DataLayer([quote_only, full], cache)
        result = await layer.fetch_price("AAPL")

        assert result.provider == "yfinance"
        assert len(result.data["price_history"]) == 2
        assert result.stale_history is False
        assert quote_only.fetch_called == 1  # attempted, then walked past

    async def test_quote_only_fallback_when_whole_chain_is_barless(self, cache):
        """Every reachable provider is quote-only → fall back to the FIRST
        quote-only result (live quote still beats nothing)."""
        q1 = MockProvider("finnhub", ["price"], result=self._quote_only_result())
        q2 = MockProvider(
            "other",
            ["price"],
            result=DataResult(
                data={"current_price": 290.0, "price_history": []},
                provider="other",
                ticker="AAPL",
                data_type="price",
                timestamp=datetime.now(tz=timezone.utc),
            ),
        )
        layer = DataLayer([q1, q2], cache)
        result = await layer.fetch_price("AAPL")

        assert result.provider == "finnhub"
        assert result.data["current_price"] == 291.58
        assert q2.fetch_called == 1  # chain fully walked before falling back

    async def test_quote_only_with_no_prior_bars_caches_as_before(self, cache):
        quote_only = MockProvider("finnhub", ["price"], result=self._quote_only_result())
        layer = DataLayer([quote_only], cache)
        result = await layer.fetch_price("AAPL")

        assert result.stale_history is False
        assert result.data["price_history"] == []
        # Cached normally: second call is a fresh-cache hit, no provider call.
        await layer.fetch_price("AAPL")
        assert quote_only.fetch_called == 1

    async def test_canonical_graft_stamps_degraded_marker_and_skips_recache(self, cache, tmp_path):
        import aiosqlite
        from datetime import timedelta

        from finrobot.engine.data.cache import canonical_key
        from finrobot.engine.data.normalize.contracts import DEGRADED_PRICE_HISTORY_STALE

        seed = MockProvider("fmp", ["price"], result=_price_result(provider="fmp"))
        await DataLayer([seed], cache).fetch_canonical("price", "AAPL")
        # Backdate BOTH slots so the canonical read misses and the raw fetch
        # walks the provider chain.
        old_time = (datetime.now(tz=timezone.utc) - timedelta(hours=1)).isoformat()
        async with aiosqlite.connect(str(tmp_path / "layer_test.db")) as conn:
            for slot in (raw_slot_key("price"), canonical_key("price")):
                await conn.execute(
                    "UPDATE cache SET cached_at = ? WHERE data_type = ? AND ticker = ?",
                    (old_time, slot, "AAPL"),
                )
            await conn.commit()

        quote_only = MockProvider("finnhub", ["price"], result=self._quote_only_result())
        out = await DataLayer([quote_only], cache).fetch_canonical("price", "AAPL")

        assert isinstance(out, NormalizedPrice)
        assert out.current_price == 291.58
        assert len(out.bars) == 2  # chart keeps rendering
        assert DEGRADED_PRICE_HISTORY_STALE in out.provenance.degraded
        # Canonical slot must NOT be re-cached (freshness-clock laundering):
        # the prior fmp row stays, honestly stale.
        cached_row = await cache.get_canonical("price", "AAPL")
        assert cached_row is not None
        assert cached_row.is_stale is True
        assert '"provider":"fmp"' in cached_row.payload_json.replace(" ", "")


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
        out = await layer.fetch_canonical(DataType.FINANCIALS, "AAPL")
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

    async def test_plan_gated_failure_never_charges_breaker(self, cache):
        """A typed ProviderPlanError (key valid, endpoint outside the plan — e.g.
        NEWS on a free FMP key) is a deterministic capability gap, not provider
        ill-health: it must fall through the chain WITHOUT counting toward the
        breaker, or a news burst would open the breaker and block the endpoints
        the plan CAN serve (financials / profile / price)."""
        from finrobot.engine.data.interface import ProviderPlanError

        health = ProviderHealth(failure_threshold=2, base_cooldown_s=600)
        gated = MockProvider(
            "fmp", ["news"], raises=ProviderPlanError("FMP plan does not include /news/stock")
        )
        fallback = MockProvider(
            "aggregator", ["news"], result=_make_result(data_type="news", provider="aggregator")
        )
        layer = DataLayer([gated, fallback], cache, health=health)

        for ticker in ("AAA", "BBB", "CCC", "DDD"):
            r = await layer.fetch("news", ticker)
            assert r.provider == "aggregator"

        # Four consecutive plan-gated failures, breaker untouched: the provider
        # was attempted every call (never cooled down) and no failure recorded.
        assert gated.fetch_called == 4
        assert health.snapshot("fmp").consecutive_failures == 0
        assert health.snapshot("fmp").cooldown_until is None

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

        async def slow_uncached(data_type, ticker):
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

        async def counting_uncached(data_type, ticker):
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

        async def recording_uncached(data_type, ticker):
            seen.append(ticker)
            await asyncio.sleep(0.01)
            return object()

        layer._fetch_canonical_uncached = recording_uncached  # type: ignore[method-assign]

        await asyncio.gather(
            layer.fetch_canonical(DataType.PRICE, "AAPL"),
            layer.fetch_canonical(DataType.PRICE, "MSFT"),
        )
        assert sorted(seen) == ["AAPL", "MSFT"]


class TestRawFetchSingleFlight:
    """fetch() coalesces concurrent identical cold-cache misses (item 3) — the
    raw-path twin of fetch_canonical's single-flight."""

    async def test_concurrent_raw_fetches_coalesce_to_one(self, cache):
        """A cold-cache stampede for one (data_type, ticker) collapses to a single
        provider walk; the registry self-evicts after completion."""

        class SlowProvider(DataProvider):
            def __init__(self) -> None:
                self.calls = 0

            @property
            def name(self) -> str:
                return "slow"

            def capabilities(self) -> list[str]:
                return ["news"]

            async def fetch(self, ticker, data_type, **kwargs) -> DataResult:
                self.calls += 1
                await asyncio.sleep(0.02)  # hold the in-flight window open
                return DataResult(
                    data={"news_items": []},
                    provider="slow",
                    ticker=ticker,
                    data_type="news",
                    timestamp=datetime.now(tz=timezone.utc),
                )

        p = SlowProvider()
        layer = DataLayer([p], cache)
        results = await asyncio.gather(*[layer.fetch("news", "AAPL") for _ in range(6)])
        assert p.calls == 1  # 6 concurrent callers, ONE provider walk
        assert all(r.provider == "slow" for r in results)
        assert layer._inflight_raw == {}  # registry self-evicts

    async def test_raw_fetches_with_distinct_kwargs_do_not_coalesce(self, cache):
        """Single-flight keys on (data_type, cache_key incl kwargs): different
        days_back run as separate flights, so neither window is served the other's
        payload (ties item 3 to the item 1 kwarg-in-key fix)."""

        class RecordingProvider(DataProvider):
            def __init__(self) -> None:
                self.seen: list[int] = []

            @property
            def name(self) -> str:
                return "rec"

            def capabilities(self) -> list[str]:
                return ["sentiment"]

            async def fetch(self, ticker, data_type, **kwargs) -> DataResult:
                self.seen.append(int(kwargs["days_back"]))
                await asyncio.sleep(0.01)
                return DataResult(
                    data={"days_back": kwargs["days_back"]},
                    provider="rec",
                    ticker=ticker,
                    data_type="sentiment",
                    timestamp=datetime.now(tz=timezone.utc),
                )

        p = RecordingProvider()
        layer = DataLayer([p], cache)
        await asyncio.gather(
            layer.fetch("sentiment", "AAPL", days_back=7),
            layer.fetch("sentiment", "AAPL", days_back=30),
        )
        assert sorted(p.seen) == [7, 30]


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

        monkeypatch.setattr("finrobot.engine.data.providers.fx.fetch_fx_rate_to_usd", fake_fx)
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

        monkeypatch.setattr("finrobot.engine.data.providers.fx.fetch_fx_rate_to_usd", fake_fx)
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

        monkeypatch.setattr("finrobot.engine.data.providers.fx.fetch_fx_rate_to_usd", boom)
        layer = DataLayer(
            [MockProvider("fmp", ["financials"], result=_adr_financials_result())], cache
        )

        out = await layer.fetch_canonical("financials", "TSM")

        # Un-converted (still TWD) but explicitly degraded — and it did NOT raise.
        assert isinstance(out, NormalizedFinancials)
        assert out.reporting_currency == "TWD"
        assert out.total_debt == 1_094_130_170_000
        assert DEGRADED_FX_UNAVAILABLE in out.provenance.degraded


class TestFxRateToUsd:
    """Public FX chokepoint for live-price→USD consumers (Coverage signal/upside).
    The canonical PRICE snapshot is left in its quote currency, so a foreign LOCAL
    listing's price must be put on the USD basis before it's compared to USD
    valuations — this is the method that does it."""

    async def test_usd_returns_one(self, cache, monkeypatch):
        """USD → 1.0. (The wrapper delegates to fetch_fx_rate_to_usd, whose own
        USD fast-path — no network — is covered in test_fx_provider; here we only
        assert the wrapper threads the call through and the rate is 1.0.)"""

        async def fake_fx(ccy, *, fmp_api_key=None):
            return 1.0 if ccy.upper() == "USD" else pytest.fail(f"unexpected {ccy}")

        monkeypatch.setattr("finrobot.engine.data.providers.fx.fetch_fx_rate_to_usd", fake_fx)
        layer = DataLayer([MockProvider("fmp", ["financials"])], cache)
        assert await layer.fx_rate_to_usd("USD") == 1.0
        assert await layer.fx_rate_to_usd("usd") == 1.0

    async def test_foreign_currency_returns_rate(self, cache, monkeypatch):
        async def fake_fx(ccy, *, fmp_api_key=None):
            assert ccy.upper() == "TWD"
            return 0.03125

        monkeypatch.setattr("finrobot.engine.data.providers.fx.fetch_fx_rate_to_usd", fake_fx)
        layer = DataLayer([MockProvider("fmp", ["financials"])], cache)
        assert await layer.fx_rate_to_usd("TWD") == pytest.approx(0.03125)

    async def test_unobtainable_rate_raises(self, cache, monkeypatch):
        """No rate → ProviderError propagates; the caller drops the comparison
        rather than mixing currencies."""

        async def boom(ccy, *, fmp_api_key=None):
            raise ProviderError("no spot FX quote for TWD→USD")

        monkeypatch.setattr("finrobot.engine.data.providers.fx.fetch_fx_rate_to_usd", boom)
        layer = DataLayer([MockProvider("fmp", ["financials"])], cache)
        with pytest.raises(ProviderError):
            await layer.fx_rate_to_usd("TWD")


# ---------------------------------------------------------------------------
# Deep-history augmentation (SEC companyfacts → through-cycle DCF window)
# ---------------------------------------------------------------------------


def _sec_yearly_result(years: list[int]) -> DataResult:
    """A DataResult shaped like EdgarToolsProvider.fetch_annual_financials —
    newest-first per-year dicts under ``yearly_data`` — for the deep-history split."""
    return DataResult(
        data={
            "yearly_data": [{"fiscal_year": f"{y}-12-31", "revenue": float(y) * 1e6} for y in years]
        },
        provider="edgar_tools",
        ticker="MU",
        data_type=DataType.FINANCIALS,
        timestamp=datetime.now(tz=timezone.utc),
    )


def _make_stub_edgar(
    result: DataResult | None = None, raises: Exception | None = None
) -> DataProvider:
    """A real EdgarToolsProvider SUBCLASS instance (so the layer's
    ``isinstance(p, EdgarToolsProvider)`` selector finds it) that skips the
    parent __init__ — the real one calls ``set_identity`` and would hit SEC —
    and stubs the one method ``fetch_deep_history`` invokes.
    """
    from finrobot.engine.data.providers.edgar_provider import EdgarToolsProvider

    class _StubEdgar(EdgarToolsProvider):
        def __init__(self) -> None:
            # Deliberately do NOT call super().__init__ (identity gate / network).
            self._result = result
            self._raises = raises
            self.calls = 0

        async def fetch_annual_financials(self, ticker: str, years: int) -> DataResult:
            self.calls += 1
            if self._raises is not None:
                raise self._raises
            assert self._result is not None
            return self._result

    return _StubEdgar()


class TestFetchDeepHistory:
    async def test_returns_none_when_no_edgar_provider(self, cache):
        """No SEC provider registered (identity unwired) → None, so the caller
        cleanly falls back to the shallow provider-chain window."""
        layer = DataLayer([MockProvider("yfinance", ["historical"])], cache)
        assert await layer.fetch_deep_history("MU", 10) is None

    async def test_routes_to_edgar_and_splits_yearly(self, cache):
        """The SEC provider is selected by type and its yearly_data is split into
        one DataResult per fiscal year (the shape the extractor consumes)."""
        stub = _make_stub_edgar(result=_sec_yearly_result([2025, 2024, 2023, 2022]))
        layer = DataLayer([MockProvider("yfinance", ["historical"]), stub], cache)

        out = await layer.fetch_deep_history("MU", 10)
        assert out is not None
        assert stub.calls == 1  # type: ignore[attr-defined]
        assert [r.data["fiscal_year"][:4] for r in out] == ["2025", "2024", "2023", "2022"]

    async def test_caches_under_sec_suffix(self, cache):
        """Second call for the same (ticker, years) hits the :sec cache slot —
        the SEC fetch is not repeated."""
        stub = _make_stub_edgar(result=_sec_yearly_result([2025, 2024]))
        layer = DataLayer([stub], cache)

        await layer.fetch_deep_history("MU", 10)
        assert stub.calls == 1  # type: ignore[attr-defined]
        await layer.fetch_deep_history("MU", 10)
        assert stub.calls == 1, "second call must hit the :sec cache slot, not re-fetch"  # type: ignore[attr-defined]

    async def test_provider_error_degrades_to_none(self, cache):
        """A SEC failure (CIK miss / down / empty facts) degrades to None so the
        seed falls back to the shallow window — never crashes the caller."""
        stub = _make_stub_edgar(raises=ProviderError("SEC companyfacts: no CIK for MU"))
        layer = DataLayer([stub], cache)
        assert await layer.fetch_deep_history("MU", 10) is None
        assert stub.calls == 1  # type: ignore[attr-defined]


def _make_stub_edgar_segments(result=None, raises=None):
    """EdgarToolsProvider subclass stubbing only ``fetch_annual_segments`` (the
    method ``fetch_segments`` routes to), skipping the network-touching parent
    __init__ — mirrors ``_make_stub_edgar`` for the SOTP-floor segments path."""
    from finrobot.engine.data.providers.edgar_provider import EdgarToolsProvider

    class _StubEdgarSeg(EdgarToolsProvider):
        def __init__(self) -> None:
            self._result = result
            self._raises = raises
            self.calls = 0

        async def fetch_annual_segments(self, ticker: str) -> DataResult:
            self.calls += 1
            if self._raises is not None:
                raise self._raises
            assert self._result is not None
            return self._result

    return _StubEdgarSeg()


class TestFetchSegments:
    """SOTP-floor segment fetch: explicitly routed to SEC, degrades to None/stale
    rather than raising so the SOTP gate cleanly drops the name."""

    async def test_returns_none_when_no_edgar_provider(self, cache):
        layer = DataLayer([MockProvider("fmp", ["financials"])], cache)
        assert await layer.fetch_segments("AAPL") is None

    async def test_health_gated_returns_none_without_fetch(self, cache, monkeypatch):
        stub = _make_stub_edgar_segments(result=_make_result(data_type="filings_10k"))
        layer = DataLayer([stub], cache)
        monkeypatch.setattr(layer, "_health_gated", lambda p: True)
        assert await layer.fetch_segments("AAPL") is None
        assert stub.calls == 0  # gated before the network

    async def test_success_caches_and_second_call_hits_cache(self, cache):
        result = _make_result(ticker="AAPL", data_type="filings_10k", provider="sec-edgar")
        stub = _make_stub_edgar_segments(result=result)
        layer = DataLayer([stub], cache)
        out = await layer.fetch_segments("AAPL")
        assert out is result and stub.calls == 1
        # cached under the :segments suffix — fresh hit, no refetch.
        await layer.fetch_segments("AAPL")
        assert stub.calls == 1

    async def test_provider_error_no_cache_returns_none(self, cache):
        stub = _make_stub_edgar_segments(raises=ProviderError("SEC segments down"))
        layer = DataLayer([stub], cache)
        assert await layer.fetch_segments("AAPL") is None
        assert stub.calls == 1

    async def test_provider_error_with_stale_cache_returns_stale(self, cache, monkeypatch):
        """A failed refresh with a stale cached copy serves the stale segments
        (last-known 10-K), not None — the SOTP floor survives a transient SEC 429."""
        stub = _make_stub_edgar_segments(raises=ProviderError("SEC 429"))
        layer = DataLayer([stub], cache)
        stale = MagicMock()
        stale.is_stale = True
        stale.data = {"segments": [{"name": "iPhone"}]}

        async def _get(_dt, _key):
            return stale

        monkeypatch.setattr(layer._cache, "get", _get)
        out = await layer.fetch_segments("AAPL")
        assert out == {"segments": [{"name": "iPhone"}]}
        assert stub.calls == 1  # attempted the fetch, fell back to stale


class TestSentimentRateLimitEntersFailureMachinery:
    """A real AdanosProvider whose every platform 429s must enter the DataLayer
    failure path — NOT be folded into a successful empty 0/3 snapshot. This nails
    the cross-component contract behind the reported MU panel: the all-429 fetch
    must (1) yield the no-data sentinel (route → reason='provider_error'),
    (2) leave NOTHING in the cache (no empty-snapshot poisoning for the TTL),
    (3) trip the circuit breaker so the next call stops hammering Adanos.
    """

    def _all_429_provider(self):
        import httpx
        from unittest.mock import AsyncMock, patch

        from finrobot.engine.data.providers.adanos_provider import AdanosProvider

        provider = AdanosProvider(api_key="test-key")
        request = httpx.Request("GET", "https://adanos.example/api")
        response = httpx.Response(429, request=request)
        get_mock = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "429 Too Many Requests", request=request, response=response
            )
        )
        return provider, patch.object(provider, "_get", get_mock), get_mock

    async def test_all_429_no_cache_yields_no_data_and_caches_nothing(self, cache):
        provider, patched, _ = self._all_429_provider()
        layer = DataLayer([provider], cache)
        with patched:
            result = await layer.fetch(DataType.SENTIMENT, "MU", days_back=7)
            await provider.close()

        # No-data sentinel, not a successful empty snapshot.
        assert result.provider == "none"
        assert "error" in result.data
        # Empty result was NOT cached — the next request can retry once Adanos
        # recovers (no 1h blank-panel poisoning). cache_key mirrors DataLayer's:
        # ticker + sorted kwargs.
        assert await cache.get(DataType.SENTIMENT, "MU:days_back=7") is None

    async def test_all_429_trips_breaker_and_stops_hammering_adanos(self, cache):
        provider, patched, get_mock = self._all_429_provider()
        layer = DataLayer([provider], cache)
        with patched:
            await layer.fetch(DataType.SENTIMENT, "MU", days_back=7)
            calls_after_first = get_mock.call_count  # 3 platforms attempted
            # Breaker is now open → the second fetch must skip Adanos entirely.
            second = await layer.fetch(DataType.SENTIMENT, "MU", days_back=7)
            await provider.close()

        assert calls_after_first == 3
        assert get_mock.call_count == 3, "breaker should have gated the 2nd fetch"
        assert layer._health.is_available("adanos") is False
        assert second.provider == "none"
