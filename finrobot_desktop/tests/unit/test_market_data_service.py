"""Unit tests for finrobot/engine/services/market_data.py.

All yfinance calls are mocked. Tests verify that YFException and other
library errors are translated to ProviderError so layer.py fallback chain
can catch them.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from yfinance.exceptions import YFException

from finrobot.engine.data.interface import ProviderError
from finrobot.engine.services.market_data import (
    fetch_performance_data,
    fetch_price_history,
    fetch_quarterly_data,
)


def _make_empty_df() -> pd.DataFrame:
    return pd.DataFrame()


def _make_hist_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [150.0, 152.0],
            "High": [155.0, 158.0],
            "Low": [148.0, 150.0],
            "Close": [152.0, 155.0],
            "Volume": [1_000_000, 1_100_000],
        },
        index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
    )


class TestFetchPriceHistoryErrors:
    @pytest.mark.asyncio
    async def test_yf_exception_raises_provider_error(self):
        with patch(
            "finrobot.engine.services.market_data.yf.Ticker",
            side_effect=YFException("rate limited"),
        ):
            with pytest.raises(ProviderError, match="price history failed"):
                await fetch_price_history("AAPL")

    @pytest.mark.asyncio
    async def test_runtime_error_raises_provider_error(self):
        with patch(
            "finrobot.engine.services.market_data.yf.Ticker",
            side_effect=RuntimeError("something broke"),
        ):
            with pytest.raises(ProviderError, match="price history failed"):
                await fetch_price_history("AAPL")

    @pytest.mark.asyncio
    async def test_os_error_raises_provider_error(self):
        with patch(
            "finrobot.engine.services.market_data.yf.Ticker",
            side_effect=OSError("network unavailable"),
        ):
            with pytest.raises(ProviderError, match="price history failed"):
                await fetch_price_history("AAPL")

    @pytest.mark.asyncio
    async def test_success_path_returns_dict(self):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = _make_hist_df()
        mock_ticker.info = {"longName": "Apple Inc.", "marketCap": 3_000_000_000_000}
        with patch(
            "finrobot.engine.services.market_data.yf.Ticker",
            return_value=mock_ticker,
        ):
            result = await fetch_price_history("AAPL")
        assert result["data_source"] == "yfinance"
        assert len(result["history"]) == 2
        assert result["company_name"] == "Apple Inc."


@pytest.mark.asyncio
async def test_fetch_price_history_returns_fetched_at():
    """fetch_price_history must inject ISO8601 fetched_at into the return dict."""
    from datetime import datetime, timezone

    fake_hist = pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.5],
            "Close": [101.5, 102.5],
            "Volume": [1_000_000, 1_100_000],
        },
        index=pd.to_datetime(["2026-05-26", "2026-05-27"]),
    )
    fake_info = {
        "currentPrice": 102.5,
        "marketCap": 3_000_000_000,
        "longName": "Test Corp",
        "fullExchangeName": "NasdaqGS",
    }

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = fake_hist
    mock_ticker.info = fake_info

    with patch(
        "finrobot.engine.services.market_data.yf.Ticker", return_value=mock_ticker
    ):
        result = await fetch_price_history("TEST", "1y")

    assert "fetched_at" in result
    fetched = datetime.fromisoformat(result["fetched_at"])
    assert fetched.tzinfo is not None  # ISO8601 with tz
    # Within 5 seconds of "now"
    assert (datetime.now(tz=timezone.utc) - fetched).total_seconds() < 5


class TestFetchQuarterlyDataErrors:
    @pytest.mark.asyncio
    async def test_yf_exception_raises_provider_error(self):
        mock_ticker = MagicMock()
        mock_ticker.quarterly_income_stmt = None
        with patch(
            "finrobot.engine.services.market_data.yf.Ticker",
            side_effect=YFException("rate limited"),
        ):
            with pytest.raises(ProviderError, match="quarterly data failed"):
                await fetch_quarterly_data("AAPL")

    @pytest.mark.asyncio
    async def test_attribute_error_raises_provider_error(self):
        with patch(
            "finrobot.engine.services.market_data.yf.Ticker",
            side_effect=AttributeError("no attr"),
        ):
            with pytest.raises(ProviderError, match="quarterly data failed"):
                await fetch_quarterly_data("AAPL")

    @pytest.mark.asyncio
    async def test_empty_income_stmt_raises_provider_error(self):
        mock_ticker = MagicMock()
        mock_ticker.quarterly_income_stmt = pd.DataFrame()
        mock_ticker.quarterly_cashflow = pd.DataFrame()
        with patch(
            "finrobot.engine.services.market_data.yf.Ticker",
            return_value=mock_ticker,
        ):
            with pytest.raises(ProviderError, match="No quarterly data available"):
                await fetch_quarterly_data("AAPL")


class TestFetchPerformanceDataErrors:
    @pytest.mark.asyncio
    async def test_yf_exception_on_download_raises_provider_error(self):
        with patch(
            "finrobot.engine.services.market_data.yf.download",
            side_effect=YFException("download failed"),
        ):
            with pytest.raises(ProviderError, match="yfinance download failed"):
                await fetch_performance_data(["AAPL"], "SPY", "1y")

    @pytest.mark.asyncio
    async def test_empty_download_raises_provider_error(self):
        with patch(
            "finrobot.engine.services.market_data.yf.download",
            return_value=pd.DataFrame(),
        ):
            with pytest.raises(ProviderError, match="No price data"):
                await fetch_performance_data(["AAPL"], "SPY", "1y")
