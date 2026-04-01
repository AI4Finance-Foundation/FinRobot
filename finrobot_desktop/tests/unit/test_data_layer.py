from datetime import datetime, timezone

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
    return DataCache(db_path=str(tmp_path / "layer_test.db"))


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
        assert any("stale" in w for w in result.warnings)

    async def test_provider_fails_no_cache_returns_error_result(self, cache):
        """No crash — returns a DataResult the LLM can relay to the user."""
        failing = MockProvider("fail", ["financials"], raises=ProviderError("down"))
        layer = DataLayer([failing], cache)
        result = await layer.fetch("financials", "AAPL")
        assert result is not None
        assert result.provider == "none"
        assert len(result.warnings) > 0
        assert any("unavailable" in w.lower() or "failed" in w.lower() for w in result.warnings)


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
        p1 = MockProvider("fmp", ["financials"], result=_make_result(provider="fmp"))
        p2 = MockProvider("finnhub", ["financials"])
        p3 = MockProvider("yfinance", ["financials"])
        layer = DataLayer([p1, p2, p3], cache)
        result = await layer.fetch("financials", "AAPL")
        assert result.provider == "fmp"
        assert p1.fetch_called == 1
        assert p2.fetch_called == 0
        assert p3.fetch_called == 0

    async def test_three_provider_chain_first_fails_second_succeeds(self, cache):
        p1 = MockProvider("fmp", ["financials"], raises=ProviderError("fmp down"))
        p2 = MockProvider("finnhub", ["financials"], result=_make_result(provider="finnhub"))
        p3 = MockProvider("yfinance", ["financials"])
        layer = DataLayer([p1, p2, p3], cache)
        result = await layer.fetch("financials", "AAPL")
        assert result.provider == "finnhub"
        assert p1.fetch_called == 1
        assert p2.fetch_called == 1
        assert p3.fetch_called == 0

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
        assert any("unavailable" in w.lower() or "failed" in w.lower() for w in result.warnings)
