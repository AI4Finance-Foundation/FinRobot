"""FMP Provider unit tests. All HTTP calls are mocked."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from finagent.engine.data.interface import DataResult, ProviderError
from finagent.engine.data.providers.fmp_provider import FMPProvider


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
            _mock_response(_fmp_income_response()),
            _mock_response(_fmp_balance_response()),
            _mock_response(_fmp_profile_response()),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "financials")

        assert result.provider == "fmp"
        assert result.ticker == "AAPL"
        assert result.data_type == "financials"
        # Key normalization checks
        assert result.data["revenue"] == 394_328_000_000
        assert result.data["ebitda"] == 137_352_000_000
        assert result.data["depreciation_amortization"] == 11_519_000_000
        assert result.data["rd_expense"] == 29_915_000_000
        assert result.data["sga_expense"] == 27_552_000_000
        assert result.data["interest_expense"] == 3_933_000_000
        assert result.data["total_debt"] == 111_088_000_000
        assert result.data["total_cash"] == 29_965_000_000
        assert result.data["market_cap"] == 2_620_000_000_000

    @pytest.mark.asyncio
    async def test_fetch_unsupported_data_type_raises(self, provider):
        with pytest.raises(ProviderError, match="not supported"):
            await provider.fetch("AAPL", "news")

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
            "date": f"{2024 - i}-09-30", "symbol": ticker,
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

    @pytest.mark.asyncio
    async def test_fetch_without_years_returns_flat(self, provider):
        responses = [
            _mock_response(_fmp_income_response()),
            _mock_response(_fmp_balance_response()),
            _mock_response(_fmp_profile_response()),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "financials")
        assert isinstance(result, DataResult)
        assert "yearly_data" not in result.data
        assert result.data["revenue"] == 394_328_000_000


class TestFMPProviderInterface:
    def test_name(self, provider):
        assert provider.name == "fmp"

    def test_capabilities(self, provider):
        caps = provider.capabilities()
        assert "financials" in caps
