"""
Unit tests use mocked yfinance.
Integration tests (marked @pytest.mark.integration) hit real yfinance.
"""

import time
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from finrobot.engine.data.interface import (
    DataResult,
    ProviderError,
    RateLimitedProviderError,
    is_rate_limit_error,
)
from finrobot.engine.data.providers.yfinance_provider import YFinanceProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_ticker(
    info: dict,
    news: list | None = None,
    history: pd.DataFrame | None = None,
    income_stmt: pd.DataFrame | None = None,
    cashflow: pd.DataFrame | None = None,
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
    # income_stmt / cashflow default to empty DataFrames (no historical data)
    if income_stmt is None:
        income_stmt = pd.DataFrame()
    mock.income_stmt = income_stmt
    if cashflow is None:
        cashflow = pd.DataFrame()
    mock.cashflow = cashflow
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
    "currency": "USD",
}


# ---------------------------------------------------------------------------
# Unit tests (mocked)
# ---------------------------------------------------------------------------


class TestYFinanceProviderMeta:
    def test_name(self):
        assert YFinanceProvider().name == "yfinance"

    def test_capabilities(self):
        caps = YFinanceProvider().capabilities()
        assert set(caps) == {"financials", "price", "price_range", "quote", "news"}


class TestFetchFinancials:
    @pytest.mark.asyncio
    async def test_returns_dataresult_with_revenue(self):
        provider = YFinanceProvider()
        mock_ticker = _make_mock_ticker(VALID_INFO)
        with patch(
            "finrobot.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker
        ):
            result = await provider.fetch("AAPL", "financials")
        assert isinstance(result, DataResult)
        assert result.data["revenue"] == 385_000_000_000
        assert result.data["market_cap"] is not None
        assert result.ticker == "AAPL"
        assert result.data_type == "financials"

    @pytest.mark.asyncio
    async def test_invalid_ticker_raises_provider_error(self):
        provider = YFinanceProvider()
        mock_ticker = _make_mock_ticker(
            {"regularMarketPrice": None, "currentPrice": None, "marketCap": None}
        )
        # Empty-ish info → invalid ticker
        mock_ticker.info = {}
        with patch(
            "finrobot.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker
        ):
            with pytest.raises(ProviderError):
                await provider.fetch("INVALID_TICKER_XYZ", "financials")

    @pytest.mark.asyncio
    async def test_key_rich_but_priceless_info_raises_provider_error(self):
        """Bug 21 entry gate: a delisted/OTC residual page can return a key-RICH
        info dict whose price/cap anchors (regularMarketPrice, currentPrice,
        marketCap) are ALL None. The old ``len(info) <= 1`` sub-gate let it
        through, and the priceless payload fabricated a $0 quote downstream."""
        provider = YFinanceProvider()
        mock_ticker = _make_mock_ticker(
            {
                "regularMarketPrice": None,
                "currentPrice": None,
                "marketCap": None,
                # Residual page noise — plenty of keys, zero price anchors.
                "longName": "Ghost Holdings Corp",
                "exchange": "PNK",
                "quoteType": "EQUITY",
                "currency": "USD",
                "symbol": "GHST",
            }
        )
        with patch(
            "finrobot.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker
        ):
            with pytest.raises(ProviderError, match="not found or returned no data"):
                await provider.fetch("GHST", "financials")


class TestFetchQuote:
    """门一 Step 3: lightweight QUOTE path via fast_info.last_price (no .info)."""

    class _FastInfo:
        def __init__(self, price: float | None, currency: str | None = "USD") -> None:
            self.last_price = price
            self.currency = currency

    def test_quote_in_capabilities(self):
        assert "quote" in YFinanceProvider().capabilities()

    @pytest.mark.asyncio
    async def test_quote_returns_price_from_fast_info(self):
        provider = YFinanceProvider()
        mock_ticker = MagicMock()
        mock_ticker.fast_info = self._FastInfo(187.5)
        with patch(
            "finrobot.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker
        ):
            result = await provider.fetch("AAPL", "quote")
        # The QUOTE payload now carries the quote currency from fast_info.currency
        # (same cheap call, no .info round-trip) so a foreign listing's price
        # travels with its currency.
        assert result.data == {"price": 187.5, "quote_currency": "USD"}
        assert result.data_type == "quote"

    @pytest.mark.asyncio
    async def test_quote_carries_foreign_currency_from_fast_info(self):
        """A foreign LOCAL listing (2330.TW) quotes in TWD — fast_info.currency
        surfaces it, and it must ride on the QUOTE payload."""
        provider = YFinanceProvider()
        mock_ticker = MagicMock()
        mock_ticker.fast_info = self._FastInfo(640.0, currency="TWD")
        with patch(
            "finrobot.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker
        ):
            result = await provider.fetch("2330.TW", "quote")
        assert result.data == {"price": 640.0, "quote_currency": "TWD"}

    @pytest.mark.asyncio
    async def test_quote_currency_none_when_fast_info_lacks_it(self):
        """fast_info without a currency → quote_currency None (consumer abstains,
        never assumes USD)."""
        provider = YFinanceProvider()
        mock_ticker = MagicMock()
        mock_ticker.fast_info = self._FastInfo(187.5, currency=None)
        with patch(
            "finrobot.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker
        ):
            result = await provider.fetch("AAPL", "quote")
        assert result.data == {"price": 187.5, "quote_currency": None}

    @pytest.mark.asyncio
    async def test_quote_none_price_raises_provider_error(self):
        provider = YFinanceProvider()
        mock_ticker = MagicMock()
        mock_ticker.fast_info = self._FastInfo(None)
        with patch(
            "finrobot.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker
        ):
            with pytest.raises(ProviderError):
                await provider.fetch("AAPL", "quote")


class TestFetchPrice:
    @pytest.mark.asyncio
    async def test_returns_price_history(self):
        provider = YFinanceProvider()
        mock_ticker = _make_mock_ticker(VALID_INFO)
        with patch(
            "finrobot.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker
        ):
            result = await provider.fetch("AAPL", "price")
        assert isinstance(result, DataResult)
        assert "price_history" in result.data
        assert result.data["quote_currency"] == "USD"
        assert len(result.data["price_history"]) == 1
        assert result.data["price_history"][0]["close"] == 152.0

    @pytest.mark.asyncio
    async def test_fetch_price_carries_foreign_quote_currency(self):
        provider = YFinanceProvider()
        mock_ticker = _make_mock_ticker({**VALID_INFO, "currency": "TWD"})
        with patch(
            "finrobot.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker
        ):
            result = await provider.fetch("2330.TW", "price")
        assert result.data["current_price"] == 150.0
        assert result.data["quote_currency"] == "TWD"


class TestFetchPriceRange:
    @pytest.mark.asyncio
    async def test_returns_adjusted_bars(self):
        provider = YFinanceProvider()
        hist = pd.DataFrame(
            {
                "Open": [100.0, 102.0],
                "High": [101.0, 103.0],
                "Low": [99.0, 101.0],
                "Close": [100.5, 102.5],
                "Volume": [1_000_000, 1_100_000],
            },
            index=pd.to_datetime(["2020-01-02", "2020-01-03"]),
        )
        mock_ticker = _make_mock_ticker(VALID_INFO, history=hist)
        with patch(
            "finrobot.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker
        ):
            result = await provider.fetch(
                "AAPL", "price_range", start="2020-01-01", end="2020-01-04", interval="1d"
            )
        assert result.data_type == "price_range"
        assert result.data["adjusted"] is True
        assert result.data["source_provider"] == "yfinance"
        bars = result.data["bars"]
        assert [b["date"] for b in bars] == ["2020-01-02", "2020-01-03"]
        assert bars[1]["close"] == 102.5
        # history called with auto_adjust=True (the adjusted basis).
        _, kwargs = mock_ticker.history.call_args
        assert kwargs["auto_adjust"] is True
        assert kwargs["start"] == "2020-01-01"

    @pytest.mark.asyncio
    async def test_empty_range_raises(self):
        provider = YFinanceProvider()
        mock_ticker = _make_mock_ticker(VALID_INFO, history=pd.DataFrame())
        with patch(
            "finrobot.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker
        ):
            with pytest.raises(ProviderError, match="no bars"):
                await provider.fetch("AAPL", "price_range", start="1990-01-01", end="1990-01-02")


class TestFetchNews:
    @pytest.mark.asyncio
    async def test_returns_news_items_list(self):
        provider = YFinanceProvider()
        raw_news = [
            {
                "content": {
                    "title": "Apple hits new high",
                    "provider": {"displayName": "Reuters"},
                    "pubDate": "2024-10-31T16:00:00Z",
                    "canonicalUrl": {"url": "https://example.com/1"},
                }
            },
            {
                "content": {
                    "title": "AAPL earnings beat",
                    "provider": {"displayName": "Bloomberg"},
                    "pubDate": "2024-10-30T14:00:00Z",
                    "canonicalUrl": {"url": "https://example.com/2"},
                }
            },
        ]
        mock_ticker = _make_mock_ticker(VALID_INFO, news=raw_news)
        with patch(
            "finrobot.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker
        ):
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
        with patch(
            "finrobot.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker
        ):
            result = await provider.fetch("AAPL", "news")
        assert result.data["news_items"] == []

    @pytest.mark.asyncio
    async def test_news_items_compatible_with_parse_raw_news(self):
        """Verify yfinance news format is parseable by parse_raw_news."""
        from finrobot.engine.compute.coordinators.news import RawNewsItem, parse_raw_news

        provider = YFinanceProvider()
        raw_news = [
            {
                "content": {
                    "title": "Apple Q4 beat",
                    "provider": {"displayName": "Reuters"},
                    "pubDate": "2024-10-31T16:00:00Z",
                    "canonicalUrl": {"url": "https://example.com/1"},
                }
            },
            {
                "content": {
                    "title": "iPhone sales surge",
                    "provider": {"displayName": "CNBC"},
                    "pubDate": "2024-10-30T10:00:00Z",
                    "canonicalUrl": {"url": "https://example.com/2"},
                }
            },
        ]
        mock_ticker = _make_mock_ticker(VALID_INFO, news=raw_news)
        with patch(
            "finrobot.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker
        ):
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
            {
                "content": {"title": "Old format news"},
                "publisher": "Yahoo",
                "link": "https://y.com",
            },
        ]
        mock_ticker = _make_mock_ticker(VALID_INFO, news=raw_news)
        with patch(
            "finrobot.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker
        ):
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
                "finrobot.engine.data.providers.yfinance_provider.yf.Ticker",
                side_effect=tracking_ticker,
            ):
                result = await provider.fetch(ticker, "financials")
            assert received_symbols == [ticker], (
                f"Ticker '{ticker}' was not passed through to yfinance"
            )
            assert isinstance(result, DataResult)
            assert result.ticker == ticker


class TestRateLimitBehavior:
    """Provider must surface 429 immediately so DataLayer falls back fast.

    The in-provider retry loop (3 attempts × [2,5,10]s sleep = up to 17s
    per call) was removed because:
      1. DataLayer already iterates providers in priority order on
         ProviderError, so retry-inside-provider blocked the fallback
         to FMP/Finnhub by ~17s.
      2. Sleeping inside the rate-limit window burns the same Yahoo quota
         on retry that already failed — counterproductive.
    """

    @pytest.mark.asyncio
    async def test_rate_limit_raises_provider_error_within_1s(self):
        """Yahoo 429 must raise ProviderError in <1s, not sleep 17s.

        Guards against re-introducing the in-provider retry loop.
        """
        from yfinance.exceptions import YFRateLimitError

        # Mock t.info to raise YFRateLimitError so the error path fires.
        # We use PropertyMock so the access pattern (t.info inside the
        # asyncio.to_thread lambda) matches production. NOTE: yfinance 1.x's
        # YFRateLimitError takes NO message argument (fixed text) — passing one
        # raised TypeError inside the lambda, which the generic except arm also
        # wrapped into ProviderError, so the old test was green WITHOUT ever
        # exercising the rate-limit path (fake-green, caught 2026-06-11).
        provider = YFinanceProvider()
        mock_ticker = MagicMock()
        type(mock_ticker).info = property(lambda self: (_ for _ in ()).throw(YFRateLimitError()))

        start = time.monotonic()
        with patch(
            "finrobot.engine.data.providers.yfinance_provider.yf.Ticker",
            return_value=mock_ticker,
        ):
            # The typed YFRateLimitError must map to RateLimitedProviderError
            # (primary classification path — survives Yahoo rewording the
            # message), and the classifier must recognise it structurally.
            with pytest.raises(RateLimitedProviderError, match="Failed to fetch ticker") as ei:
                await provider.fetch("AAPL", "financials")
        assert is_rate_limit_error(ei.value)
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, (
            f"Provider took {elapsed:.2f}s — retry loop must stay deleted. "
            "DataLayer.fetch() already iterates providers on ProviderError; "
            "retry-inside-provider blocks fallback to FMP/Finnhub."
        )

    @pytest.mark.asyncio
    async def test_no_retry_constants_exposed(self):
        """The retry constants must not be re-introduced as module symbols.

        Guards against partial-revert: if a future commit re-adds
        ``_MAX_RETRIES`` / ``_RETRY_DELAYS`` even without wiring them
        into ``fetch``, the next reviewer should be forced to defend it.
        """
        from finrobot.engine.data.providers import yfinance_provider

        assert not hasattr(yfinance_provider, "_MAX_RETRIES"), (
            "_MAX_RETRIES re-introduced — retry-inside-provider conflicts "
            "with DataLayer fallback. See yfinance_provider.py docstring."
        )
        assert not hasattr(yfinance_provider, "_RETRY_DELAYS"), (
            "_RETRY_DELAYS re-introduced — see _MAX_RETRIES rationale."
        )


class TestUnsupportedDataType:
    @pytest.mark.asyncio
    async def test_filings_raises_provider_error(self):
        provider = YFinanceProvider()
        mock_ticker = _make_mock_ticker(VALID_INFO)
        with patch(
            "finrobot.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker
        ):
            with pytest.raises(ProviderError, match="not supported"):
                await provider.fetch("AAPL", "filings")

    @pytest.mark.asyncio
    async def test_unknown_type_raises_provider_error(self):
        provider = YFinanceProvider()
        mock_ticker = _make_mock_ticker(VALID_INFO)
        with patch(
            "finrobot.engine.data.providers.yfinance_provider.yf.Ticker", return_value=mock_ticker
        ):
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
        columns = pd.to_datetime([f"{2024 - i}-09-30" for i in range(years)])
        data = {
            col: {
                "Total Revenue": (400 - i * 10) * 1e9,
                "EBITDA": (130 - i * 5) * 1e9,
                "Net Income": (95 - i * 3) * 1e9,
                "Gross Profit": (170 - i * 4) * 1e9,
                "Operating Income": (120 - i * 5) * 1e9,
                "Basic EPS": 6.15 - i * 0.4,
                "Selling General Administrative": (25 - i) * 1e9,
            }
            for i, col in enumerate(columns)
        }
        return pd.DataFrame(data)

    @staticmethod
    def _build_cashflow(years: int = 3) -> pd.DataFrame:
        """Build a mock cashflow DataFrame aligned by fiscal-year-end date to
        ``_build_income_stmt``. CapEx is negative (yfinance convention)."""
        columns = pd.to_datetime([f"{2024 - i}-09-30" for i in range(years)])
        data = {
            col: {
                "Operating Cash Flow": (110 - i * 5) * 1e9,
                "Investing Cash Flow": -(8 + i * 0.4) * 1e9,
                "Financing Cash Flow": -(95 - i * 3) * 1e9,
                "Depreciation And Amortization": (11 - i * 0.1) * 1e9,
                "Capital Expenditure": -(10 + i * 0.5) * 1e9,
                "Change In Working Capital": (-2 + i * 0.3) * 1e9,
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
            "finrobot.engine.data.providers.yfinance_provider.yf.Ticker",
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
            "finrobot.engine.data.providers.yfinance_provider.yf.Ticker",
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
            "finrobot.engine.data.providers.yfinance_provider.yf.Ticker",
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
            "finrobot.engine.data.providers.yfinance_provider.yf.Ticker",
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
            "finrobot.engine.data.providers.yfinance_provider.yf.Ticker",
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
            "finrobot.engine.data.providers.yfinance_provider.yf.Ticker",
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
            "finrobot.engine.data.providers.yfinance_provider.yf.Ticker",
            return_value=mock_ticker,
        ):
            result = await provider.fetch("AAPL", "financials")
        assert "revenue" in result.data
        assert "yearly_data" not in result.data


class TestFetchHistoricalFinancialsFullSchema:
    """门一 Step 2: yfinance historical yearly_data must carry the SAME rich
    per-year schema as FMP (cash-flow trio + D&A + EPS + SGA + absolutes), so
    that when historical_extractor routes through DataLayer and FMP is down,
    the yfinance fallback still yields a complete HistoricalMetrics instead of
    silently degrading DCF to industry medians."""

    def _build_ticker(self, years: int = 3):
        income = TestFetchHistoricalFinancials._build_income_stmt(years)
        cashflow = TestFetchHistoricalFinancials._build_cashflow(years)
        return _make_mock_ticker(VALID_INFO, income_stmt=income, cashflow=cashflow)

    async def _fetch_yearly(self, years: int = 3):
        provider = YFinanceProvider()
        with patch(
            "finrobot.engine.data.providers.yfinance_provider.yf.Ticker",
            return_value=self._build_ticker(years),
        ):
            result = await provider.fetch("AAPL", "financials", years=years)
        return result.data["yearly_data"]

    @pytest.mark.asyncio
    async def test_income_statement_absolutes_and_eps_sga(self):
        y = await self._fetch_yearly(3)
        assert y[0]["gross_profit"] == 170e9
        assert y[0]["operating_income"] == 120e9
        assert y[0]["eps"] == pytest.approx(6.15)
        assert y[0]["sga_expense"] == 25e9

    @pytest.mark.asyncio
    async def test_cash_flow_statement_populated(self):
        y = await self._fetch_yearly(3)
        assert y[0]["operating_cash_flow"] == 110e9
        assert y[0]["investing_cash_flow"] == -8e9
        assert y[0]["financing_cash_flow"] == -95e9
        assert y[0]["depreciation_amortization"] == pytest.approx(11e9)
        assert y[0]["change_in_working_capital"] == pytest.approx(-2e9)

    @pytest.mark.asyncio
    async def test_capex_sign_normalized_to_positive(self):
        """CapEx is negative in raw yfinance (outflow); provider stores it as a
        positive magnitude so DCF capex/revenue ratios compute directly."""
        y = await self._fetch_yearly(3)
        assert y[0]["capital_expenditure"] == 10e9
        assert all(yr["capital_expenditure"] >= 0 for yr in y)

    @pytest.mark.asyncio
    async def test_empty_cashflow_yields_none_cf_fields_not_crash(self):
        """Missing cash-flow statement → CF fields are None (consumer zero-fills),
        income-statement fields still populate."""
        income = TestFetchHistoricalFinancials._build_income_stmt(2)
        mock_ticker = _make_mock_ticker(VALID_INFO, income_stmt=income, cashflow=pd.DataFrame())
        provider = YFinanceProvider()
        with patch(
            "finrobot.engine.data.providers.yfinance_provider.yf.Ticker",
            return_value=mock_ticker,
        ):
            result = await provider.fetch("AAPL", "financials", years=2)
        y = result.data["yearly_data"]
        assert y[0]["revenue"] == 400e9
        assert y[0]["operating_cash_flow"] is None
        assert y[0]["capital_expenditure"] is None


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
