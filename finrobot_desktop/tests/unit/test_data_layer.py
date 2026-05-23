from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from finagent.engine.data.cache import DataCache
from finagent.engine.data.interface import DataProvider, DataResult, ProviderError
from finagent.engine.data.layer import DataLayer


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
        # The fallback warning is 中文 (surfaces in the desktop UI); check for
        # the user-facing "缓存数据" phrase rather than the old English "stale".
        assert any("缓存数据" in w for w in result.warnings)

    async def test_provider_fails_no_cache_returns_error_result(self, cache):
        """No crash — returns a DataResult the LLM can relay to the user."""
        failing = MockProvider("fail", ["financials"], raises=ProviderError("down"))
        layer = DataLayer([failing], cache)
        result = await layer.fetch("financials", "AAPL")
        assert result is not None
        assert result.provider == "none"
        assert len(result.warnings) > 0
        # Message was 中文-ified for the desktop UI (was: "Data unavailable... all providers failed").
        assert any("不可用" in w or "失败" in w for w in result.warnings)


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
        # Message was 中文-ified for the desktop UI (was: "Data unavailable... all providers failed").
        assert any("不可用" in w or "失败" in w for w in result.warnings)


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
