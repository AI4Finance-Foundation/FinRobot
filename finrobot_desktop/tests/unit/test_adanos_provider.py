"""Adanos Provider unit tests. All HTTP calls are mocked."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from finagent.engine.data.interface import DataResult, ProviderError
from finagent.engine.data.providers.adanos_provider import (
    AdanosProvider,
    _compute_alignment,
)


@pytest.fixture
def provider():
    return AdanosProvider(api_key="test-key")


def _adanos_reddit_response() -> dict:
    return {
        "stocks": [
            {
                "ticker": "AAPL",
                "buzz_score": 82.0,
                "bullish_pct": 58.0,
                "mentions": 1200,
                "trend": "rising",
            }
        ]
    }


def _adanos_x_response() -> dict:
    return {
        "stocks": [
            {
                "ticker": "AAPL",
                "buzz_score": 76.0,
                "bullish_pct": 62.0,
                "mentions": 800,
                "trend": "stable",
            }
        ]
    }


def _adanos_polymarket_response() -> dict:
    return {
        "stocks": [
            {
                "ticker": "AAPL",
                "buzz_score": 68.0,
                "bullish_pct": 55.0,
                "trade_count": 450,
                "trend": "falling",
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


class TestAdanosInterface:
    def test_name(self, provider):
        assert provider.name == "adanos"

    def test_capabilities(self, provider):
        caps = provider.capabilities()
        assert "sentiment" in caps

    def test_has_rate_limit_attrs(self, provider):
        import asyncio

        assert isinstance(provider._lock, asyncio.Lock)
        assert isinstance(provider._last_call, float)


class TestAdanosFetch:
    @pytest.mark.asyncio
    async def test_fetch_sentiment_aggregates_three_sources(self, provider):
        responses = [
            _mock_response(_adanos_reddit_response()),
            _mock_response(_adanos_x_response()),
            _mock_response(_adanos_polymarket_response()),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "sentiment")

        assert isinstance(result, DataResult)
        assert result.provider == "adanos"
        assert result.data["coverage"] == "3/3"
        assert result.data["coverage_ratio"] == 1.0
        # (82 + 76 + 68) / 3 = 75.333... → 75.3
        assert result.data["average_buzz"] == 75.3
        # (58 + 62 + 55) / 3 = 58.333... → 58.3
        assert result.data["bullish_avg"] == 58.3
        # spread = 62-55 = 7 (<=10), avg = 58.3 (>=55) → Bullish alignment
        assert result.data["source_alignment"] == "Bullish alignment"
        assert len(result.data["sources"]) == 3

    @pytest.mark.asyncio
    async def test_fetch_sentiment_one_source_fails(self, provider):
        async def side_effect_fn(*args, **kwargs):
            # Track call count via side_effect list
            raise AssertionError("should not reach")

        responses = [
            _mock_response(_adanos_reddit_response()),
            _mock_response(_adanos_x_response()),
        ]
        call_count = 0

        async def mock_get(path, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 3:
                raise httpx.TimeoutException("timeout")
            return responses.pop(0)

        with patch.object(provider, "_get", side_effect=mock_get):
            result = await provider.fetch("AAPL", "sentiment")

        assert result.data["coverage"] == "2/3"
        assert len(result.warnings) > 0
        assert result.data["average_buzz"] is not None

    @pytest.mark.asyncio
    async def test_fetch_sentiment_all_sources_fail(self, provider):
        async def mock_get(path, params=None):
            raise httpx.TimeoutException("timeout")

        with patch.object(provider, "_get", side_effect=mock_get):
            result = await provider.fetch("AAPL", "sentiment")

        assert result.data["coverage"] == "0/3"
        assert result.data["coverage_ratio"] == 0.0
        assert result.data["average_buzz"] is None
        assert result.data["bullish_avg"] is None

    @pytest.mark.asyncio
    async def test_unsupported_type_raises(self, provider):
        with pytest.raises(ProviderError, match="not supported"):
            await provider.fetch("AAPL", "financials")

    @pytest.mark.asyncio
    async def test_ticker_normalization(self, provider):
        responses = [
            _mock_response(_adanos_reddit_response()),
            _mock_response(_adanos_x_response()),
            _mock_response(_adanos_polymarket_response()),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch(" $aapl ", "sentiment")

        assert result.data["ticker"] == "AAPL"


class TestAdanosAlignment:
    def test_bullish_alignment(self):
        assert _compute_alignment([60, 62, 58]) == "Bullish alignment"

    def test_bearish_alignment(self):
        assert _compute_alignment([40, 42, 38]) == "Bearish alignment"

    def test_neutral_alignment(self):
        assert _compute_alignment([48, 50, 52]) == "Neutral alignment"

    def test_partial_divergence(self):
        assert _compute_alignment([40, 55]) == "Partial divergence"

    def test_wide_divergence(self):
        assert _compute_alignment([30, 70]) == "Wide divergence"

    def test_single_source(self):
        assert _compute_alignment([60]) == "Single-source signal"

    def test_no_coverage(self):
        assert _compute_alignment([]) == "No coverage"


class TestAdanosRateLimiter:
    @pytest.mark.asyncio
    async def test_rate_limiter_sleeps_on_rapid_calls(self, provider, monkeypatch):
        import asyncio
        import time

        from finagent.engine.data.providers.adanos_provider import _MIN_INTERVAL

        sleep_durations: list[float] = []

        async def mock_sleep(secs: float) -> None:
            sleep_durations.append(secs)

        monkeypatch.setattr(asyncio, "sleep", mock_sleep)

        # Simulate last call happening just now
        provider._last_call = time.monotonic()

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await provider._get("/test")

        assert len(sleep_durations) == 1
        assert sleep_durations[0] <= _MIN_INTERVAL
        assert sleep_durations[0] > 0
