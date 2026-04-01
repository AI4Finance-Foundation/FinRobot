"""Finnhub Provider unit tests. All HTTP calls are mocked."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from finagent.engine.data.interface import ProviderError
from finagent.engine.data.providers.finnhub_provider import FinnhubProvider


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
            await provider.fetch("AAPL", "news")

    @pytest.mark.asyncio
    async def test_timeout_raises_provider_error(self, provider):
        with patch.object(
            provider, "_get", AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        ):
            with pytest.raises(ProviderError, match="timeout"):
                await provider.fetch("AAPL", "financials")


class TestFinnhubInterface:
    def test_name(self, provider):
        assert provider.name == "finnhub"

    def test_capabilities(self, provider):
        caps = provider.capabilities()
        assert "financials" in caps
        assert "profile" in caps
