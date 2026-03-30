"""
Unit tests use mocked yfinance.
Integration tests (marked @pytest.mark.integration) hit real yfinance.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from finagent.engine.data.interface import DataResult, ProviderError
from finagent.engine.data.providers.yfinance_provider import YFinanceProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_ticker(info: dict, news: list | None = None, history: pd.DataFrame | None = None):
    mock = MagicMock()
    mock.info = info
    mock.news = news or []
    if history is None:
        history = pd.DataFrame(
            {
                "Open": [150.0],
                "High": [155.0],
                "Low": [148.0],
                "Close": [152.0],
                "Volume": [1_000_000],
            },
            index=pd.to_datetime(["2024-01-01"]),
        )
    mock.history.return_value = history
    return mock


VALID_INFO = {
    "regularMarketPrice": 150.0,
    "marketCap": 2_500_000_000_000,
    "totalRevenue": 385_000_000_000,
    "ebitda": 130_000_000_000,
    "netIncomeToCommon": 97_000_000_000,
    "grossMargins": 0.44,
    "operatingMargins": 0.30,
    "trailingPE": 28.3,
    "sharesOutstanding": 15_500_000_000,
}


# ---------------------------------------------------------------------------
# Unit tests (mocked)
# ---------------------------------------------------------------------------

class TestYFinanceProviderMeta:
    def test_name(self):
        assert YFinanceProvider().name == "yfinance"

    def test_capabilities(self):
        caps = YFinanceProvider().capabilities()
        assert set(caps) == {"financials", "price", "news"}


class TestFetchFinancials:
    @pytest.mark.asyncio
    async def test_returns_dataresult_with_revenue(self):
        provider = YFinanceProvider()
        mock_ticker = _make_mock_ticker(VALID_INFO)
        with patch("finagent.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker):
            result = await provider.fetch("AAPL", "financials")
        assert isinstance(result, DataResult)
        assert result.data["revenue"] == 385_000_000_000
        assert result.data["market_cap"] is not None
        assert result.ticker == "AAPL"
        assert result.data_type == "financials"

    @pytest.mark.asyncio
    async def test_invalid_ticker_raises_provider_error(self):
        provider = YFinanceProvider()
        mock_ticker = _make_mock_ticker({"regularMarketPrice": None, "currentPrice": None, "marketCap": None})
        # Empty-ish info → invalid ticker
        mock_ticker.info = {}
        with patch("finagent.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker):
            with pytest.raises(ProviderError):
                await provider.fetch("INVALID_TICKER_XYZ", "financials")


class TestFetchPrice:
    @pytest.mark.asyncio
    async def test_returns_price_history(self):
        provider = YFinanceProvider()
        mock_ticker = _make_mock_ticker(VALID_INFO)
        with patch("finagent.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker):
            result = await provider.fetch("AAPL", "price")
        assert isinstance(result, DataResult)
        assert "price_history" in result.data
        assert len(result.data["price_history"]) == 1
        assert result.data["price_history"][0]["close"] == 152.0


class TestFetchNews:
    @pytest.mark.asyncio
    async def test_returns_headlines_list(self):
        provider = YFinanceProvider()
        raw_news = [{"content": {"title": "Apple hits new high"}}, {"content": {"title": "AAPL earnings beat"}}]
        mock_ticker = _make_mock_ticker(VALID_INFO, news=raw_news)
        with patch("finagent.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker):
            result = await provider.fetch("AAPL", "news")
        assert isinstance(result, DataResult)
        assert "headlines" in result.data
        assert "Apple hits new high" in result.data["headlines"]

    @pytest.mark.asyncio
    async def test_empty_news_returns_empty_list(self):
        provider = YFinanceProvider()
        mock_ticker = _make_mock_ticker(VALID_INFO, news=[])
        with patch("finagent.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker):
            result = await provider.fetch("AAPL", "news")
        assert result.data["headlines"] == []


class TestUnsupportedDataType:
    @pytest.mark.asyncio
    async def test_filings_raises_provider_error(self):
        provider = YFinanceProvider()
        mock_ticker = _make_mock_ticker(VALID_INFO)
        with patch("finagent.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker):
            with pytest.raises(ProviderError, match="not supported"):
                await provider.fetch("AAPL", "filings")

    @pytest.mark.asyncio
    async def test_unknown_type_raises_provider_error(self):
        provider = YFinanceProvider()
        mock_ticker = _make_mock_ticker(VALID_INFO)
        with patch("finagent.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker):
            with pytest.raises(ProviderError):
                await provider.fetch("AAPL", "unknown_type")


# ---------------------------------------------------------------------------
# Integration tests (real yfinance — run manually with -m integration)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestYFinanceIntegration:
    @pytest.mark.asyncio
    async def test_fetch_financials_real(self):
        result = await YFinanceProvider().fetch("AAPL", "financials")
        assert result.data.get("revenue") is not None
        assert result.data["revenue"] > 0

    @pytest.mark.asyncio
    async def test_fetch_price_real(self):
        result = await YFinanceProvider().fetch("AAPL", "price")
        assert len(result.data["price_history"]) > 0

    @pytest.mark.asyncio
    async def test_fetch_news_real(self):
        result = await YFinanceProvider().fetch("AAPL", "news")
        assert isinstance(result.data["headlines"], list)

    @pytest.mark.asyncio
    async def test_invalid_ticker_raises_real(self):
        with pytest.raises(ProviderError):
            await YFinanceProvider().fetch("INVALID_TICKER_XYZ_999", "financials")
