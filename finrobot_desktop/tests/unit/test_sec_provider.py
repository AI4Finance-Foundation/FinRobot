"""SEC EDGAR Provider unit tests. All HTTP calls are mocked."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from finagent.engine.data.interface import ProviderError
from finagent.engine.data.providers.sec_provider import SECEdgarProvider


@pytest.fixture
def provider():
    return SECEdgarProvider(user_agent="TestAgent test@test.com")


def _sec_company_tickers_response() -> dict:
    """Mock SEC company_tickers.json — used by _resolve_cik()."""
    return {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc"},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
    }


def _sec_submissions_response() -> dict:
    """Mock SEC EDGAR /submissions/ response."""
    return {
        "cik": "0000320193",
        "entityType": "operating",
        "name": "Apple Inc",
        "tickers": ["AAPL"],
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-24-000081"],
                "filingDate": ["2024-11-01"],
                "form": ["10-K"],
                "primaryDocument": ["aapl-20240928.htm"],
            }
        },
    }


def _mock_response(json_data=None, text_data=None, status_code=200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    if json_data is not None:
        resp.json.return_value = json_data
    if text_data is not None:
        resp.text = text_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


class TestSECEdgarFetch:
    async def test_fetch_filings_returns_10k_info(self, provider):
        """_fetch_filings calls _get twice: _resolve_cik then submissions."""
        responses = [
            _mock_response(_sec_company_tickers_response()),  # _resolve_cik
            _mock_response(_sec_submissions_response()),  # submissions
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "filings")

        assert result.provider == "sec_edgar"
        assert result.data_type == "filings"
        assert result.data["latest_10k_date"] == "2024-11-01"
        assert result.data["has_10k"] is True

    async def test_unsupported_type_raises(self, provider):
        with pytest.raises(ProviderError, match="not supported"):
            await provider.fetch("AAPL", "financials")

    async def test_user_agent_in_headers(self, provider):
        """SEC EDGAR requires User-Agent header."""
        assert provider._user_agent == "TestAgent test@test.com"

    async def test_timeout_raises_provider_error(self, provider):
        with patch.object(
            provider,
            "_get",
            AsyncMock(side_effect=httpx.TimeoutException("timeout")),
        ):
            with pytest.raises(ProviderError, match="timeout"):
                await provider.fetch("AAPL", "filings")

    async def test_rate_limit_403_raises_provider_error(self, provider):
        with patch.object(
            provider,
            "_get",
            AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "403",
                    request=MagicMock(),
                    response=MagicMock(status_code=403),
                )
            ),
        ):
            with pytest.raises(ProviderError):
                await provider.fetch("AAPL", "filings")


class TestSECEdgarInterface:
    def test_name(self, provider):
        assert provider.name == "sec_edgar"

    def test_capabilities(self, provider):
        caps = provider.capabilities()
        assert "filings" in caps
        assert "financials" not in caps
