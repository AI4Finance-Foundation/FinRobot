"""Finnhub Provider unit tests. All HTTP calls are mocked."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from finrobot.engine.data.interface import DataResult, ProviderError
from finrobot.engine.data.providers.finnhub_provider import FinnhubProvider


@pytest.fixture
def provider():
    return FinnhubProvider(api_key="test-key")


def _finnhub_profile_response() -> dict:
    """Mock Finnhub /stock/profile2 response."""
    return {
        "ticker": "AAPL",
        "name": "Apple Inc",
        "finnhubIndustry": "Technology",
        "marketCapitalization": 2_620_000,  # Finnhub reports in millions
        "shareOutstanding": 15_000,  # millions
        "exchange": "NASDAQ",
    }


def _finnhub_financials_reported_response() -> dict:
    """Mock Finnhub /stock/financials-reported response (SEC filings)."""
    return {
        "data": [
            {
                "year": 2025,
                "quarter": 0,
                "endDate": "2025-09-27 00:00:00",
                "filedDate": "2025-11-01 00:00:00",
                "report": {
                    "ic": [
                        {"concept": "Revenues", "value": 394_328_000_000},
                        {"concept": "CostOfGoodsAndServicesSold", "value": 213_645_000_000},
                        {"concept": "OperatingIncomeLoss", "value": 123_216_000_000},
                        {"concept": "NetIncomeLoss", "value": 96_995_000_000},
                        {"concept": "DepreciationAndAmortization", "value": 11_519_000_000},
                    ],
                    "bs": [
                        {"concept": "LongTermDebt", "value": 98_071_000_000},
                        {
                            "concept": "CashAndCashEquivalentsAtCarryingValue",
                            "value": 29_965_000_000,
                        },
                    ],
                },
            }
        ]
    }


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


class TestFinnhubFetch:
    @pytest.mark.asyncio
    async def test_fetch_financials_returns_normalized_keys(self, provider):
        responses = [
            _mock_response(_finnhub_profile_response()),
            _mock_response(_finnhub_financials_reported_response()),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "financials")

        assert result.provider == "finnhub"
        assert result.data["revenue"] == 394_328_000_000
        assert result.data["depreciation_amortization"] == 11_519_000_000
        assert result.data["market_cap"] == 2_620_000_000_000  # converted from millions
        # freq=annual SEC filings must be tagged so normalize doesn't mislabel a
        # stale 10-K as a fresh TTM snapshot stamped to the fetch wall-clock.
        assert result.data["period_basis"] == "annual"
        assert result.data["fiscal_year"] == "2025-09-27 00:00:00"

    @pytest.mark.asyncio
    async def test_annual_filing_normalizes_to_period_end_not_fetch_time(self, provider):
        """End-to-end: the annual filing's as_of must be the fiscal-period end
        (2025-09-27), NOT the fetch wall-clock, and period_basis must be annual."""
        from finrobot.engine.data.normalize.financials import normalize_financials

        responses = [
            _mock_response(_finnhub_profile_response()),
            _mock_response(_finnhub_financials_reported_response()),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "financials")
        norm = normalize_financials(result)
        assert norm.period_basis == "annual"
        assert norm.as_of.date().isoformat() == "2025-09-27"
        # as_of must be the period end, not "now" (the fetch timestamp).
        assert norm.as_of.date() != result.timestamp.date()

    @pytest.mark.asyncio
    async def test_fetch_profile(self, provider):
        with patch.object(
            provider,
            "_get",
            AsyncMock(return_value=_mock_response(_finnhub_profile_response())),
        ):
            result = await provider.fetch("AAPL", "profile")
        assert result.data_type == "profile"
        assert result.data["company_name"] == "Apple Inc"

    @pytest.mark.asyncio
    async def test_unsupported_type_raises(self, provider):
        with pytest.raises(ProviderError, match="not supported"):
            await provider.fetch("AAPL", "unknown_type")

    @pytest.mark.asyncio
    async def test_timeout_raises_provider_error(self, provider):
        with patch.object(
            provider, "_get", AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        ):
            with pytest.raises(ProviderError, match="timeout"):
                await provider.fetch("AAPL", "financials")


def _finnhub_multi_year_reported(ticker="AAPL", years=3):
    return {
        "data": [
            {
                "year": 2024 - i,
                "report": {
                    "ic": [
                        {"concept": "Revenues", "value": 394e9 - i * 10e9},
                        {"concept": "NetIncomeLoss", "value": 97e9 - i * 3e9},
                        {"concept": "DepreciationAndAmortization", "value": 11e9},
                        {"concept": "OperatingIncomeLoss", "value": 119e9 - i * 3e9},
                        {"concept": "CostOfGoodsAndServicesSold", "value": 213e9 + i * 5e9},
                    ],
                    "bs": [
                        {"concept": "LongTermDebt", "value": 100e9},
                        {"concept": "CashAndCashEquivalentsAtCarryingValue", "value": 30e9},
                    ],
                },
            }
            for i in range(years)
        ]
    }


def _finnhub_financials_missing_debt_cash() -> dict:
    """SEC filing whose balance sheet omits LongTermDebt and Cash concepts.

    XBRL omitting a concept must surface as None, never a fabricated 0 — a 0
    would defeat extractor.py's EV guard (raw_debt/raw_cash is not None) and
    fabricate a "zero net debt" enterprise value.
    """
    return {
        "data": [
            {
                "year": 2025,
                "endDate": "2025-09-27 00:00:00",
                "filedDate": "2025-11-01 00:00:00",
                "report": {
                    "ic": [
                        {"concept": "Revenues", "value": 394_328_000_000},
                        {"concept": "OperatingIncomeLoss", "value": 123_216_000_000},
                        {"concept": "NetIncomeLoss", "value": 96_995_000_000},
                        {"concept": "DepreciationAndAmortization", "value": 11_519_000_000},
                    ],
                    # No LongTermDebt, no CashAndCashEquivalentsAtCarryingValue.
                    "bs": [],
                },
            }
        ]
    }


class TestFinnhubNonePreservation:
    """Missing XBRL concepts must stay None (BUG-008), never fabricated 0."""

    @pytest.mark.asyncio
    async def test_missing_debt_cash_stay_none_not_zero(self, provider):
        responses = [
            _mock_response(_finnhub_profile_response()),
            _mock_response(_finnhub_financials_missing_debt_cash()),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "financials")

        # None, not 0 — a fabricated 0 defeats extractor.py's EV guard.
        assert result.data["total_debt"] is None
        assert result.data["total_cash"] is None
        assert result.data["total_debt"] != 0
        assert result.data["total_cash"] != 0

    @pytest.mark.asyncio
    async def test_missing_debt_cash_survive_normalization_as_none(self, provider):
        """None must propagate through normalize so extractor.py's EV guard
        (raw_debt/raw_cash is not None) skips EV instead of fabricating
        market_cap + 0 - 0."""
        from finrobot.engine.data.normalize.financials import normalize_financials

        responses = [
            _mock_response(_finnhub_profile_response()),
            _mock_response(_finnhub_financials_missing_debt_cash()),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "financials")
        norm = normalize_financials(result)
        assert norm.total_debt is None
        assert norm.total_cash is None

    @pytest.mark.asyncio
    async def test_missing_da_yields_none_ebitda_not_understated(self, provider):
        """EBITDA must be None when D&A is missing, not a silent +0 understatement."""
        profile = _mock_response(_finnhub_profile_response())
        no_da = {
            "data": [
                {
                    "year": 2025,
                    "endDate": "2025-09-27 00:00:00",
                    "report": {
                        "ic": [
                            {"concept": "Revenues", "value": 394_328_000_000},
                            {"concept": "OperatingIncomeLoss", "value": 123_216_000_000},
                            {"concept": "NetIncomeLoss", "value": 96_995_000_000},
                            # No DepreciationAndAmortization.
                        ],
                        "bs": [],
                    },
                }
            ]
        }
        with patch.object(
            provider, "_get", AsyncMock(side_effect=[profile, _mock_response(no_da)])
        ):
            result = await provider.fetch("AAPL", "financials")
        assert result.data["ebitda"] is None


class TestFinnhubFetchHistorical:
    @pytest.mark.asyncio
    async def test_fetch_with_years_packs_yearly_data(self, provider):
        profile_resp = _mock_response(_finnhub_profile_response())
        reported_resp = _mock_response(_finnhub_multi_year_reported("AAPL", 3))
        with patch.object(provider, "_get", AsyncMock(side_effect=[profile_resp, reported_resp])):
            result = await provider.fetch("AAPL", "financials", years=3)
        assert isinstance(result, DataResult)
        assert "yearly_data" in result.data
        assert len(result.data["yearly_data"]) == 3
        assert result.data["yearly_data"][0]["revenue"] == 394e9

    @pytest.mark.asyncio
    async def test_fetch_without_years_returns_flat(self, provider):
        profile_resp = _mock_response(_finnhub_profile_response())
        reported_resp = _mock_response(_finnhub_financials_reported_response())
        with patch.object(provider, "_get", AsyncMock(side_effect=[profile_resp, reported_resp])):
            result = await provider.fetch("AAPL", "financials")
        assert isinstance(result, DataResult)
        assert "yearly_data" not in result.data


class TestFinnhubInterface:
    def test_name(self, provider):
        assert provider.name == "finnhub"

    def test_capabilities(self, provider):
        caps = provider.capabilities()
        assert "financials" in caps
        assert "profile" in caps


def _finnhub_news_response():
    return [
        {
            "headline": "Apple Q4 Beat",
            "source": "Reuters",
            "datetime": 1730390400,
            "url": "https://example.com/1",
            "category": "company news",
        },
        {
            "headline": "iPhone strong",
            "source": "Bloomberg",
            "datetime": 1730304000,
            "url": "https://example.com/2",
            "category": "company news",
        },
    ]


class TestFinnhubNews:
    @pytest.mark.asyncio
    async def test_fetch_news(self, provider):
        with patch.object(
            provider, "_get", AsyncMock(return_value=_mock_response(_finnhub_news_response()))
        ):
            result = await provider.fetch("AAPL", "news")
        assert result.data_type == "news"
        items = result.data["news_items"]
        assert len(items) == 2
        assert items[0]["title"] == "Apple Q4 Beat"

    @pytest.mark.asyncio
    async def test_news_in_capabilities(self, provider):
        assert "news" in provider.capabilities()


class TestFinnhubNetworkErrors:
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
                await provider.fetch("AAPL", "profile")


class TestFinnhubRateLimiter:
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
        from finrobot.engine.data.providers.finnhub_provider import _MIN_INTERVAL

        sleep_durations: list[float] = []

        async def mock_sleep(secs: float) -> None:
            sleep_durations.append(secs)

        monkeypatch.setattr(asyncio, "sleep", mock_sleep)

        # Simulate last call happening just now
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
