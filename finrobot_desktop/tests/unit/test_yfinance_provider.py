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

def _make_mock_ticker(
    info: dict,
    news: list | None = None,
    history: pd.DataFrame | None = None,
    income_stmt: pd.DataFrame | None = None,
):
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
    # income_stmt defaults to empty DataFrame (no historical data)
    if income_stmt is None:
        income_stmt = pd.DataFrame()
    mock.income_stmt = income_stmt
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
    async def test_returns_news_items_list(self):
        provider = YFinanceProvider()
        raw_news = [
            {"content": {
                "title": "Apple hits new high",
                "provider": {"displayName": "Reuters"},
                "pubDate": "2024-10-31T16:00:00Z",
                "canonicalUrl": {"url": "https://example.com/1"},
            }},
            {"content": {
                "title": "AAPL earnings beat",
                "provider": {"displayName": "Bloomberg"},
                "pubDate": "2024-10-30T14:00:00Z",
                "canonicalUrl": {"url": "https://example.com/2"},
            }},
        ]
        mock_ticker = _make_mock_ticker(VALID_INFO, news=raw_news)
        with patch("finagent.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker):
            result = await provider.fetch("AAPL", "news")
        assert isinstance(result, DataResult)
        assert "news_items" in result.data
        items = result.data["news_items"]
        assert len(items) == 2
        assert items[0]["title"] == "Apple hits new high"
        assert items[0]["source"] == "Reuters"
        assert items[0]["url"] == "https://example.com/1"

    @pytest.mark.asyncio
    async def test_empty_news_returns_empty_list(self):
        provider = YFinanceProvider()
        mock_ticker = _make_mock_ticker(VALID_INFO, news=[])
        with patch("finagent.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker):
            result = await provider.fetch("AAPL", "news")
        assert result.data["news_items"] == []

    @pytest.mark.asyncio
    async def test_news_items_compatible_with_parse_raw_news(self):
        """Verify yfinance news format is parseable by parse_raw_news."""
        from finagent.engine.compute.news import RawNewsItem, parse_raw_news

        provider = YFinanceProvider()
        raw_news = [
            {"content": {
                "title": "Apple Q4 beat",
                "provider": {"displayName": "Reuters"},
                "pubDate": "2024-10-31T16:00:00Z",
                "canonicalUrl": {"url": "https://example.com/1"},
            }},
            {"content": {
                "title": "iPhone sales surge",
                "provider": {"displayName": "CNBC"},
                "pubDate": "2024-10-30T10:00:00Z",
                "canonicalUrl": {"url": "https://example.com/2"},
            }},
        ]
        mock_ticker = _make_mock_ticker(VALID_INFO, news=raw_news)
        with patch("finagent.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker):
            result = await provider.fetch("AAPL", "news")
        items = parse_raw_news(result)
        assert len(items) == 2
        assert all(isinstance(item, RawNewsItem) for item in items)
        assert items[0].title == "Apple Q4 beat"
        assert items[0].source == "Reuters"

    @pytest.mark.asyncio
    async def test_news_fallback_fields(self):
        """When content sub-fields are missing, falls back to top-level fields."""
        provider = YFinanceProvider()
        # Old-style yfinance news format (no nested content.provider etc.)
        raw_news = [
            {"content": {"title": "Old format news"}, "publisher": "Yahoo", "link": "https://y.com"},
        ]
        mock_ticker = _make_mock_ticker(VALID_INFO, news=raw_news)
        with patch("finagent.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker):
            result = await provider.fetch("AAPL", "news")
        items = result.data["news_items"]
        assert len(items) == 1
        assert items[0]["source"] == "Yahoo"
        assert items[0]["url"] == "https://y.com"


class TestNonUSTickerFormat:
    """Track E: A-share / HK tickers must reach yfinance without format rejection."""

    @pytest.mark.asyncio
    async def test_non_us_ticker_format_not_rejected(self):
        """600519.SS (A-share), 000858.SZ (Shenzhen), 0700.HK must pass through."""
        received_symbols: list[str] = []

        original_make_mock = _make_mock_ticker

        def tracking_ticker(symbol: str):
            received_symbols.append(symbol)
            return original_make_mock(VALID_INFO)

        provider = YFinanceProvider()
        for ticker in ("600519.SS", "000858.SZ", "0700.HK"):
            received_symbols.clear()
            with patch(
                "finagent.engine.data.providers.yfinance_provider.yf.Ticker",
                side_effect=tracking_ticker,
            ):
                result = await provider.fetch(ticker, "financials")
            assert received_symbols == [ticker], (
                f"Ticker '{ticker}' was not passed through to yfinance"
            )
            assert isinstance(result, DataResult)
            assert result.ticker == ticker


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


class TestFetchHistoricalFinancials:
    """Tests for multi-year financials via income_stmt DataFrame."""

    @staticmethod
    def _build_income_stmt(years: int = 3) -> pd.DataFrame:
        """Build a mock income_stmt DataFrame with `years` columns.

        Columns are fiscal-year-end dates (most recent first).
        Rows are standard yfinance income statement labels.
        """
        columns = pd.to_datetime(
            [f"{2024 - i}-09-30" for i in range(years)]
        )
        data = {
            col: {
                "Total Revenue": (400 - i * 10) * 1e9,
                "EBITDA": (130 - i * 5) * 1e9,
                "Net Income": (95 - i * 3) * 1e9,
                "Gross Profit": (170 - i * 4) * 1e9,
                "Operating Income": (120 - i * 5) * 1e9,
            }
            for i, col in enumerate(columns)
        }
        return pd.DataFrame(data)

    @pytest.mark.asyncio
    async def test_multi_year_returns_yearly_data(self):
        """When years > 1, result.data['yearly_data'] has N entries."""
        income_stmt = self._build_income_stmt(3)
        mock_ticker = _make_mock_ticker(VALID_INFO, income_stmt=income_stmt)
        provider = YFinanceProvider()
        with patch(
            "finagent.engine.data.providers.yfinance_provider.yf.Ticker",
            return_value=mock_ticker,
        ):
            result = await provider.fetch("AAPL", "financials", years=3)
        assert isinstance(result, DataResult)
        assert "yearly_data" in result.data
        yearly = result.data["yearly_data"]
        assert len(yearly) == 3
        # Most recent year first
        assert yearly[0]["revenue"] == 400e9
        assert yearly[1]["revenue"] == 390e9
        assert yearly[2]["revenue"] == 380e9

    @pytest.mark.asyncio
    async def test_multi_year_extracts_margins(self):
        """Each year entry includes computed margins."""
        income_stmt = self._build_income_stmt(2)
        mock_ticker = _make_mock_ticker(VALID_INFO, income_stmt=income_stmt)
        provider = YFinanceProvider()
        with patch(
            "finagent.engine.data.providers.yfinance_provider.yf.Ticker",
            return_value=mock_ticker,
        ):
            result = await provider.fetch("AAPL", "financials", years=2)
        yearly = result.data["yearly_data"]
        # gross_margin = Gross Profit / Total Revenue
        expected_gm = 170e9 / 400e9
        assert abs(yearly[0]["gross_margin"] - expected_gm) < 1e-6
        # operating_margin = Operating Income / Total Revenue
        expected_om = 120e9 / 400e9
        assert abs(yearly[0]["operating_margin"] - expected_om) < 1e-6

    @pytest.mark.asyncio
    async def test_multi_year_includes_fiscal_year(self):
        """Each yearly entry includes the fiscal_year string."""
        income_stmt = self._build_income_stmt(2)
        mock_ticker = _make_mock_ticker(VALID_INFO, income_stmt=income_stmt)
        provider = YFinanceProvider()
        with patch(
            "finagent.engine.data.providers.yfinance_provider.yf.Ticker",
            return_value=mock_ticker,
        ):
            result = await provider.fetch("AAPL", "financials", years=2)
        yearly = result.data["yearly_data"]
        assert yearly[0]["fiscal_year"] == "2024-09-30"
        assert yearly[1]["fiscal_year"] == "2023-09-30"

    @pytest.mark.asyncio
    async def test_multi_year_caps_at_available_columns(self):
        """If years > available columns, return only available data."""
        income_stmt = self._build_income_stmt(2)
        mock_ticker = _make_mock_ticker(VALID_INFO, income_stmt=income_stmt)
        provider = YFinanceProvider()
        with patch(
            "finagent.engine.data.providers.yfinance_provider.yf.Ticker",
            return_value=mock_ticker,
        ):
            result = await provider.fetch("AAPL", "financials", years=5)
        assert len(result.data["yearly_data"]) == 2

    @pytest.mark.asyncio
    async def test_multi_year_empty_income_stmt_falls_back(self):
        """If income_stmt is empty, fall back to single-year from info."""
        mock_ticker = _make_mock_ticker(VALID_INFO, income_stmt=pd.DataFrame())
        provider = YFinanceProvider()
        with patch(
            "finagent.engine.data.providers.yfinance_provider.yf.Ticker",
            return_value=mock_ticker,
        ):
            result = await provider.fetch("AAPL", "financials", years=3)
        # Falls back to single-year: no yearly_data key, has revenue directly
        assert "revenue" in result.data
        assert result.data["revenue"] == 385_000_000_000

    @pytest.mark.asyncio
    async def test_years_one_uses_single_year_path(self):
        """years=1 should use single-year (info dict) path."""
        mock_ticker = _make_mock_ticker(VALID_INFO)
        provider = YFinanceProvider()
        with patch(
            "finagent.engine.data.providers.yfinance_provider.yf.Ticker",
            return_value=mock_ticker,
        ):
            result = await provider.fetch("AAPL", "financials", years=1)
        assert "revenue" in result.data
        assert "yearly_data" not in result.data

    @pytest.mark.asyncio
    async def test_no_years_kwarg_uses_single_year(self):
        """No years kwarg → single-year path (backward compatible)."""
        mock_ticker = _make_mock_ticker(VALID_INFO)
        provider = YFinanceProvider()
        with patch(
            "finagent.engine.data.providers.yfinance_provider.yf.Ticker",
            return_value=mock_ticker,
        ):
            result = await provider.fetch("AAPL", "financials")
        assert "revenue" in result.data
        assert "yearly_data" not in result.data


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
        assert isinstance(result.data["news_items"], list)

    @pytest.mark.asyncio
    async def test_invalid_ticker_raises_real(self):
        with pytest.raises(ProviderError):
            await YFinanceProvider().fetch("INVALID_TICKER_XYZ_999", "financials")
