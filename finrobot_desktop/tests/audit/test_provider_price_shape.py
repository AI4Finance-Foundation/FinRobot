"""Cross-provider PRICE shape parity guard (yfinance-限流根治路线图 门二).

Downstream consumers (normalize_price → extract_financial_data / MarketDataZone
/ technical_payload) read a PRICE ``DataResult.data`` with NO provider-specific
branch. So every PRICE-capable provider must emit the IDENTICAL shape:

    {
        "current_price": float,
        "price_history": [ {date, open, high, low, close, volume}, ... ],
        "exchange": str | None,
    }

This test drives yfinance, FMP, and Finnhub through their PRICE path with mocked
HTTP and asserts the three ``DataResult.data`` payloads are structurally
identical — top-level keys, per-bar keys, and value types. A new provider that
implements PRICE with a divergent shape (e.g. ``history`` instead of
``price_history``, or a bar missing ``volume``) fails here, before it can corrupt
the 52-week high/low or the live pill.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pandas as pd
import pytest

from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.providers.finnhub_provider import FinnhubProvider
from finrobot.engine.data.providers.fmp_provider import FMPProvider
from finrobot.engine.data.providers.yfinance_provider import YFinanceProvider

# The canonical PRICE shape every provider must honour.
_TOP_LEVEL_KEYS = {"current_price", "price_history", "exchange"}
_BAR_KEYS = {"date", "open", "high", "low", "close", "volume"}


def _mock_response(json_data: Any, status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


async def _yfinance_price() -> DataResult:
    info = {
        "currentPrice": 175.5,
        "regularMarketPrice": 175.5,
        "marketCap": 2_620_000_000_000,
        "fullExchangeName": "NasdaqGS",
    }
    hist = pd.DataFrame(
        {
            "Open": [170.0, 172.0, 174.0],
            "High": [172.5, 174.5, 176.0],
            "Low": [169.5, 171.0, 173.5],
            "Close": [172.0, 174.0, 175.0],
            "Volume": [45_000_000, 48_000_000, 50_000_000],
        },
        index=pd.to_datetime(["2026-05-21", "2026-05-22", "2026-05-23"]),
    )
    mock_ticker = MagicMock()
    mock_ticker.info = info
    mock_ticker.history.return_value = hist
    with patch(
        "finrobot.engine.data.providers.yfinance_provider.yf.Ticker",
        return_value=mock_ticker,
    ):
        return await YFinanceProvider().fetch("AAPL", "price")


async def _fmp_price() -> DataResult:
    quote = [
        {
            "symbol": "AAPL",
            "price": 175.5,
            "exchange": "NASDAQ",
            "marketCap": 2_620_000_000_000,
        }
    ]
    # Stable /historical-price-eod/dividend-adjusted: bare array, whole bar
    # pre-adjusted (adjOpen/adjHigh/adjLow/adjClose).
    historical = [
        {
            "symbol": "AAPL",
            "date": "2026-05-23",
            "adjOpen": 174.0,
            "adjHigh": 176.0,
            "adjLow": 173.5,
            "adjClose": 175.0,
            "volume": 50_000_000,
        },
        {
            "symbol": "AAPL",
            "date": "2026-05-22",
            "adjOpen": 172.0,
            "adjHigh": 174.5,
            "adjLow": 171.0,
            "adjClose": 174.0,
            "volume": 48_000_000,
        },
        {
            "symbol": "AAPL",
            "date": "2026-05-21",
            "adjOpen": 170.0,
            "adjHigh": 172.5,
            "adjLow": 169.5,
            "adjClose": 172.0,
            "volume": 45_000_000,
        },
    ]
    provider = FMPProvider(api_key="test-key")
    with patch.object(
        provider,
        "_get",
        AsyncMock(
            side_effect=[
                _mock_response(quote),
                _mock_response(historical),
                _mock_response([{"currency": "USD"}]),
            ]
        ),
    ):
        return await provider.fetch("AAPL", "price")


async def _finnhub_price() -> DataResult:
    quote = {"c": 175.5, "h": 176.0, "l": 173.5, "o": 174.0, "pc": 174.27, "t": 1_747_958_400}
    profile = {"name": "Apple Inc", "exchange": "NASDAQ"}
    candle = {
        "s": "ok",
        "t": [1_747_785_600, 1_747_872_000, 1_747_958_400],
        "o": [170.0, 172.0, 174.0],
        "h": [172.5, 174.5, 176.0],
        "l": [169.5, 171.0, 173.5],
        "c": [172.0, 174.0, 175.0],
        "v": [45_000_000, 48_000_000, 50_000_000],
    }
    provider = FinnhubProvider(api_key="test-key")
    with patch.object(
        provider,
        "_get",
        AsyncMock(
            side_effect=[
                _mock_response(quote),
                _mock_response(profile),
                _mock_response(candle),
            ]
        ),
    ):
        return await provider.fetch("AAPL", "price")


@pytest.fixture(scope="module")
def price_results() -> dict[str, DataResult]:
    import asyncio

    async def gather() -> dict[str, DataResult]:
        return {
            "yfinance": await _yfinance_price(),
            "fmp": await _fmp_price(),
            "finnhub": await _finnhub_price(),
        }

    return asyncio.run(gather())


@pytest.mark.parametrize("name", ["yfinance", "fmp", "finnhub"])
def test_price_top_level_keys_present(name: str, price_results: dict[str, DataResult]) -> None:
    """Every PRICE provider emits exactly current_price + price_history + exchange.

    Extra keys are tolerated (a provider may carry richer metadata), but the
    three the consumers read MUST be present.
    """
    data = price_results[name].data
    assert _TOP_LEVEL_KEYS.issubset(data.keys()), (
        f"{name} PRICE missing required keys: {_TOP_LEVEL_KEYS - set(data.keys())}"
    )


@pytest.mark.parametrize("name", ["yfinance", "fmp", "finnhub"])
def test_current_price_is_positive_float(name: str, price_results: dict[str, DataResult]) -> None:
    cp = price_results[name].data["current_price"]
    assert isinstance(cp, float), f"{name} current_price is {type(cp)}, expected float"
    assert cp > 0


@pytest.mark.parametrize("name", ["yfinance", "fmp", "finnhub"])
def test_price_history_bars_have_canonical_keys(
    name: str, price_results: dict[str, DataResult]
) -> None:
    history = price_results[name].data["price_history"]
    assert isinstance(history, list)
    assert history, f"{name} price_history is empty"
    for bar in history:
        assert set(bar.keys()) == _BAR_KEYS, (
            f"{name} bar keys {set(bar.keys())} != canonical {_BAR_KEYS}"
        )


@pytest.mark.parametrize("name", ["yfinance", "fmp", "finnhub"])
def test_price_history_oldest_first(name: str, price_results: dict[str, DataResult]) -> None:
    """The 52-week high/low window and SMA series assume oldest-first ordering."""
    dates = [bar["date"] for bar in price_results[name].data["price_history"]]
    assert dates == sorted(dates), f"{name} price_history not oldest-first: {dates}"


def test_all_providers_emit_identical_top_level_shape(
    price_results: dict[str, DataResult],
) -> None:
    """The required-key set is identical across all three providers (the core
    门二 invariant: consumers never branch on provider for PRICE)."""
    required = {
        name: _TOP_LEVEL_KEYS & set(result.data.keys()) for name, result in price_results.items()
    }
    assert required["yfinance"] == required["fmp"] == required["finnhub"] == _TOP_LEVEL_KEYS
