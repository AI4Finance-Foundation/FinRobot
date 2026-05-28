"""FMP Provider unit tests. All HTTP calls are mocked."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from finrobot.engine.data.interface import DataResult, ProviderError
from finrobot.engine.data.providers.fmp_provider import FMPProvider


@pytest.fixture
def provider():
    return FMPProvider(api_key="test-key")


def _fmp_income_response(ticker: str = "AAPL") -> list[dict]:
    """Mock FMP /income-statement response (array of annual periods)."""
    return [
        {
            "date": "2025-09-30",
            "symbol": ticker,
            "revenue": 394_328_000_000,
            "ebitda": 137_352_000_000,
            "netIncome": 96_995_000_000,
            "depreciationAndAmortization": 11_519_000_000,
            "grossProfit": 180_683_000_000,
            "operatingIncome": 123_216_000_000,
            "researchAndDevelopmentExpenses": 29_915_000_000,
            "sellingGeneralAndAdministrative": 27_552_000_000,
            "interestExpense": 3_933_000_000,
        }
    ]


def _fmp_quarterly_income_response(ticker: str = "AAPL") -> list[dict]:
    """Mock FMP quarterly income rows used for current TTM financials."""
    return [
        {
            "date": f"2026-0{quarter + 1}-28",
            "symbol": ticker,
            "revenue": 100_000_000_000,
            "ebitda": 30_000_000_000,
            "netIncome": 20_000_000_000,
            "depreciationAndAmortization": 3_000_000_000,
            "grossProfit": 45_000_000_000,
            "operatingIncome": 25_000_000_000,
            "researchAndDevelopmentExpenses": 7_000_000_000,
            "sellingGeneralAndAdministrative": 6_000_000_000,
            "interestExpense": 1_000_000_000,
        }
        for quarter in range(4)
    ]


def _fmp_balance_response(ticker: str = "AAPL") -> list[dict]:
    return [
        {
            "date": "2025-09-30",
            "symbol": ticker,
            "totalDebt": 111_088_000_000,
            "cashAndCashEquivalents": 29_965_000_000,
            "totalStockholdersEquity": 56_950_000_000,
        }
    ]


def _fmp_profile_response(ticker: str = "AAPL") -> list[dict]:
    return [
        {
            "symbol": ticker,
            "mktCap": 2_620_000_000_000,
            "beta": 1.24,
            "price": 175.0,
            "volAvg": 54_000_000,
            "companyName": "Apple Inc.",
            "industry": "Consumer Electronics",
            "sector": "Technology",
            "exchange": "NASDAQ",
        }
    ]


def _mock_response(json_data, status_code=200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


class TestFMPFetch:
    @pytest.mark.asyncio
    async def test_fetch_financials_returns_normalized_keys(self, provider):
        """FMP-specific keys are normalized to common format."""
        responses = [
            _mock_response(_fmp_quarterly_income_response()),
            _mock_response(_fmp_balance_response()),
            _mock_response(_fmp_profile_response()),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "financials")

        assert result.provider == "fmp"
        assert result.ticker == "AAPL"
        assert result.data_type == "financials"
        # Key normalization checks
        assert result.data["period_basis"] == "ttm"
        assert result.data["revenue"] == 400_000_000_000
        assert result.data["ebitda"] == 120_000_000_000
        assert result.data["depreciation_amortization"] == 12_000_000_000
        assert result.data["rd_expense"] == 28_000_000_000
        assert result.data["sga_expense"] == 24_000_000_000
        assert result.data["interest_expense"] == 4_000_000_000
        assert result.data["total_debt"] == 111_088_000_000
        assert result.data["total_cash"] == 29_965_000_000
        assert result.data["market_cap"] == 2_620_000_000_000

    @pytest.mark.asyncio
    async def test_fetch_unsupported_data_type_raises(self, provider):
        with pytest.raises(ProviderError, match="not supported"):
            await provider.fetch("AAPL", "unknown_type")

    @pytest.mark.asyncio
    async def test_api_error_raises_provider_error(self, provider):
        with patch.object(
            provider,
            "_get",
            AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "403", request=MagicMock(), response=MagicMock(status_code=403)
                )
            ),
        ):
            with pytest.raises(ProviderError):
                await provider.fetch("AAPL", "financials")

    @pytest.mark.asyncio
    async def test_timeout_raises_provider_error(self, provider):
        with patch.object(
            provider,
            "_get",
            AsyncMock(side_effect=httpx.TimeoutException("timeout")),
        ):
            with pytest.raises(ProviderError, match="timeout"):
                await provider.fetch("AAPL", "financials")


def _fmp_multi_year_income(ticker="AAPL", years=3):
    base_revenue = 394_328_000_000
    return [
        {
            "date": f"{2024 - i}-09-30",
            "symbol": ticker,
            "revenue": base_revenue - i * 10_000_000_000,
            "ebitda": 130_000_000_000 - i * 5_000_000_000,
            "netIncome": 97_000_000_000 - i * 3_000_000_000,
            "grossProfit": 181_000_000_000 - i * 4_000_000_000,
            "operatingIncome": 119_000_000_000 - i * 3_000_000_000,
            "depreciationAndAmortization": 11_000_000_000,
            "researchAndDevelopmentExpenses": 30_000_000_000,
            "sellingGeneralAndAdministrative": 25_000_000_000,
            "interestExpense": 3_500_000_000,
        }
        for i in range(years)
    ]


class TestFMPFetchHistorical:
    @pytest.mark.asyncio
    async def test_fetch_with_years_packs_yearly_data(self, provider):
        responses = [
            _mock_response(_fmp_multi_year_income("AAPL", 3)),
            _mock_response(_fmp_balance_response()),
            _mock_response(_fmp_profile_response()),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "financials", years=3)
        assert isinstance(result, DataResult)
        assert "yearly_data" in result.data
        assert len(result.data["yearly_data"]) == 3
        assert result.data["yearly_data"][0]["revenue"] == 394_328_000_000
        # fiscal_year must be present and non-None in every yearly entry;
        # historical_loaders.py line 55 does `data.get("fiscal_year") or data.get("date")`
        # — a missing fiscal_year causes all years to be skipped → band.sample_count == 0.
        for entry in result.data["yearly_data"]:
            assert entry.get("fiscal_year") is not None, (
                f"yearly entry missing fiscal_year: {entry}"
            )

    @pytest.mark.asyncio
    async def test_fetch_without_years_returns_flat(self, provider):
        responses = [
            _mock_response(_fmp_quarterly_income_response()),
            _mock_response(_fmp_balance_response()),
            _mock_response(_fmp_profile_response()),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "financials")
        assert isinstance(result, DataResult)
        assert "yearly_data" not in result.data
        assert result.data["revenue"] == 400_000_000_000
        # Single-year flat result must also carry fiscal_year
        assert result.data.get("fiscal_year") is not None


class TestFMPProviderInterface:
    def test_name(self, provider):
        assert provider.name == "fmp"

    def test_capabilities(self, provider):
        caps = provider.capabilities()
        assert "financials" in caps
        # price was added when yfinance rate-limit fallback became necessary
        # — exercise here so a future trim of _SUPPORTED can't silently
        # break the multi-provider PRICE fallback chain.
        assert "price" in caps


def _fmp_news_response(ticker="AAPL"):
    return [
        {
            "title": "Apple Q4 earnings beat",
            "site": "Reuters",
            "publishedDate": "2024-10-31T16:00:00.000Z",
            "url": "https://example.com/1",
        },
        {
            "title": "iPhone 16 sales strong",
            "site": "Bloomberg",
            "publishedDate": "2024-10-30T14:00:00.000Z",
            "url": "https://example.com/2",
        },
    ]


class TestFMPNews:
    @pytest.mark.asyncio
    async def test_fetch_news_returns_news_items(self, provider):
        with patch.object(
            provider, "_get", AsyncMock(return_value=_mock_response(_fmp_news_response()))
        ):
            result = await provider.fetch("AAPL", "news")
        assert isinstance(result, DataResult)
        assert result.data_type == "news"
        items = result.data["news_items"]
        assert len(items) == 2
        assert items[0]["title"] == "Apple Q4 earnings beat"
        assert items[0]["source"] == "Reuters"

    @pytest.mark.asyncio
    async def test_news_in_capabilities(self, provider):
        assert "news" in provider.capabilities()


def _fmp_earnings_response(ticker="AAPL"):
    return [
        {
            "date": "2024-10-31",
            "symbol": ticker,
            "epsActual": 1.64,
            "epsEstimated": 1.60,
            "revenueActual": 94_930_000_000,
            "revenueEstimated": 94_210_000_000,
        },
        {
            "date": "2024-07-31",
            "symbol": ticker,
            "epsActual": 1.40,
            "epsEstimated": 1.35,
            "revenueActual": 85_778_000_000,
            "revenueEstimated": 84_530_000_000,
        },
    ]


class TestFMPEarnings:
    @pytest.mark.asyncio
    async def test_fetch_earnings_returns_normalized_keys(self, provider):
        """FMP earnings-surprises response is normalized to common format."""
        with patch.object(
            provider, "_get", AsyncMock(return_value=_mock_response(_fmp_earnings_response()))
        ):
            result = await provider.fetch("AAPL", "earnings")
        assert result.provider == "fmp"
        assert result.data_type == "earnings"
        history = result.data["earnings_history"]
        assert len(history) == 2
        first = history[0]
        assert first["date"] == "2024-10-31"
        assert first["eps_actual"] == 1.64
        assert first["eps_estimated"] == 1.60
        assert first["revenue_actual"] == 94_930_000_000
        assert first["revenue_estimated"] == 94_210_000_000

    @pytest.mark.asyncio
    async def test_earnings_in_capabilities(self, provider):
        assert "earnings" in provider.capabilities()

    @pytest.mark.asyncio
    async def test_earnings_skips_entries_with_null_eps(self, provider):
        """Entries without epsActual or epsEstimated should be filtered out."""
        raw = [
            {
                "date": "2024-10-31",
                "epsActual": 1.64,
                "epsEstimated": 1.60,
                "revenueActual": 90e9,
                "revenueEstimated": 89e9,
            },
            {
                "date": "2024-07-31",
                "epsActual": None,
                "epsEstimated": 1.35,
                "revenueActual": 85e9,
                "revenueEstimated": 84e9,
            },
        ]
        with patch.object(provider, "_get", AsyncMock(return_value=_mock_response(raw))):
            result = await provider.fetch("AAPL", "earnings")
        assert len(result.data["earnings_history"]) == 1


def _fmp_quote_response(ticker: str = "AAPL", price: float = 175.0) -> list[dict]:
    """Mock FMP /quote/{ticker} response."""
    return [
        {
            "symbol": ticker,
            "name": "Apple Inc.",
            "price": price,
            "exchange": "NASDAQ",
            "exchangeShortName": "NASDAQ",
            "marketCap": 2_620_000_000_000,
            "volume": 54_000_000,
        }
    ]


def _fmp_historical_price_response(days: int = 3) -> dict:
    """Mock FMP /historical-price-full/{ticker} response.

    FMP returns newest-first; the provider reverses to match yfinance's
    oldest-first ordering. We hand back newest-first here to exercise that.
    """
    return {
        "symbol": "AAPL",
        "historical": [
            {
                "date": "2026-05-23",
                "open": 174.0,
                "high": 176.0,
                "low": 173.5,
                "close": 175.0,
                "volume": 50_000_000,
            },
            {
                "date": "2026-05-22",
                "open": 172.0,
                "high": 174.5,
                "low": 171.0,
                "close": 174.0,
                "volume": 48_000_000,
            },
            {
                "date": "2026-05-21",
                "open": 170.0,
                "high": 172.5,
                "low": 169.5,
                "close": 172.0,
                "volume": 45_000_000,
            },
        ][:days],
    }


class TestFMPPrice:
    """PRICE fallback path — exists so yfinance rate-limit failures hit FMP
    next instead of falling straight through to the 20h-stale-cache warning
    the user saw in production (2026-05-25)."""

    @pytest.mark.asyncio
    async def test_fetch_price_returns_yfinance_compatible_shape(self, provider):
        responses = [
            _mock_response(_fmp_quote_response("AAPL", price=175.5)),
            _mock_response(_fmp_historical_price_response(days=3)),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "price")

        assert isinstance(result, DataResult)
        assert result.provider == "fmp"
        assert result.ticker == "AAPL"
        assert result.data_type == "price"
        assert result.data["current_price"] == 175.5
        assert result.data["exchange"] == "NASDAQ"
        # Oldest first — extract_financial_data relies on this ordering when
        # it pulls 52w high/low from the close column.
        history = result.data["price_history"]
        assert [p["date"] for p in history] == ["2026-05-21", "2026-05-22", "2026-05-23"]
        assert history[0]["close"] == 172.0
        assert history[-1]["close"] == 175.0

    @pytest.mark.asyncio
    async def test_fetch_price_empty_quote_raises(self, provider):
        with patch.object(
            provider,
            "_get",
            AsyncMock(side_effect=[_mock_response([]), _mock_response({"historical": []})]),
        ):
            with pytest.raises(ProviderError, match="no data"):
                await provider.fetch("DELISTED", "price")

    @pytest.mark.asyncio
    async def test_fetch_price_missing_price_field_raises(self, provider):
        responses = [
            _mock_response([{"symbol": "BAD", "exchange": "NASDAQ"}]),  # no price
            _mock_response({"historical": []}),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            with pytest.raises(ProviderError, match="no price field"):
                await provider.fetch("BAD", "price")

    @pytest.mark.asyncio
    async def test_fetch_price_handles_empty_history(self, provider):
        """No history rows → empty price_history list, not a crash."""
        responses = [
            _mock_response(_fmp_quote_response("NEW", price=10.0)),
            _mock_response({"symbol": "NEW", "historical": []}),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("NEW", "price")
        assert result.data["current_price"] == 10.0
        assert result.data["price_history"] == []


class TestFMPNetworkErrors:
    """New catch branches: ConnectError / RemoteProtocolError / ReadError / WriteError."""

    @pytest.mark.asyncio
    async def test_connect_error_raises_provider_error(self, provider):
        with patch.object(
            provider,
            "_get",
            AsyncMock(side_effect=httpx.ConnectError("connection refused")),
        ):
            with pytest.raises(ProviderError, match="network error"):
                await provider.fetch("AAPL", "financials")

    @pytest.mark.asyncio
    async def test_remote_protocol_error_raises_provider_error(self, provider):
        with patch.object(
            provider,
            "_get",
            AsyncMock(side_effect=httpx.RemoteProtocolError("unexpected EOF")),
        ):
            with pytest.raises(ProviderError, match="network error"):
                await provider.fetch("AAPL", "financials")

    @pytest.mark.asyncio
    async def test_read_error_raises_provider_error(self, provider):
        with patch.object(
            provider,
            "_get",
            AsyncMock(side_effect=httpx.ReadError("read failed")),
        ):
            with pytest.raises(ProviderError, match="network error"):
                await provider.fetch("AAPL", "news")

    @pytest.mark.asyncio
    async def test_write_error_raises_provider_error(self, provider):
        with patch.object(
            provider,
            "_get",
            AsyncMock(side_effect=httpx.WriteError("write failed")),
        ):
            with pytest.raises(ProviderError, match="network error"):
                await provider.fetch("AAPL", "earnings")


class TestFMPRateLimiter:
    def test_provider_has_rate_limit_attributes(self, provider):
        """Rate limiter requires _lock and _last_call on every instance."""
        import asyncio

        assert hasattr(provider, "_lock")
        assert isinstance(provider._lock, asyncio.Lock)
        assert hasattr(provider, "_last_call")
        assert isinstance(provider._last_call, float)

    @pytest.mark.asyncio
    async def test_rate_limiter_sleeps_on_rapid_calls(self, provider, monkeypatch):
        """Second call within MIN_INTERVAL must trigger asyncio.sleep."""
        import asyncio
        import time
        from finrobot.engine.data.providers.fmp_provider import _MIN_INTERVAL

        sleep_durations: list[float] = []

        async def mock_sleep(secs: float) -> None:
            sleep_durations.append(secs)

        monkeypatch.setattr(asyncio, "sleep", mock_sleep)

        # Simulate last call happening just now (elapsed << _MIN_INTERVAL)
        provider._last_call = time.monotonic()

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        # Provider now owns a long-lived httpx client (instantiated in __init__)
        # so we monkeypatch the per-instance .get instead of httpx.AsyncClient.
        provider._client.get = AsyncMock(return_value=mock_resp)

        await provider._get("/test")

        assert len(sleep_durations) == 1
        assert sleep_durations[0] <= _MIN_INTERVAL
        assert sleep_durations[0] > 0
