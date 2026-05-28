"""Unit tests for finrobot/engine/services/market_data.py (门一 Step 4).

fetch_price_history now fetches through DataLayer.fetch_price (provider chain)
instead of direct yfinance. These tests mock the DataLayer and verify the
payload shape + the bad-ticker(→422 ValueError) vs upstream-down(→502
ProviderError) classification the /price route depends on.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from finrobot.engine.data.interface import DataResult, ProviderError
from finrobot.engine.data.types import DataType
from finrobot.engine.services.market_data import (
    _change_from_history,
    fetch_price_history,
)


class _FakeLayer:
    """DataLayer stand-in exposing only fetch_price."""

    def __init__(
        self, *, result: DataResult | None = None, raises: Exception | None = None
    ) -> None:
        self._result = result
        self._raises = raises

    async def fetch_price(self, ticker: str) -> DataResult:
        if self._raises is not None:
            raise self._raises
        assert self._result is not None
        return self._result


def _price_result(
    *,
    current_price: float | None = 152.0,
    history: list[dict[str, Any]] | None = None,
    exchange: str | None = "NasdaqGS",
    provider: str = "yfinance",
) -> DataResult:
    if history is None:
        history = [
            {"date": "2026-05-26", "close": 101.5},
            {"date": "2026-05-27", "close": 102.5},
        ]
    return DataResult(
        data={
            "current_price": current_price,
            "price_history": history,
            "exchange": exchange,
        },
        provider=provider,
        ticker="AAPL",
        data_type=DataType.PRICE,
        timestamp=datetime.now(tz=timezone.utc),
    )


async def _fetch(layer: _FakeLayer, ticker: str = "AAPL") -> dict[str, Any]:
    return await fetch_price_history(layer, ticker)  # type: ignore[arg-type]


class TestFetchPriceHistorySuccess:
    @pytest.mark.asyncio
    async def test_returns_payload_shape(self):
        result = await _fetch(_FakeLayer(result=_price_result()))
        assert result["current_price"] == 152.0
        assert len(result["history"]) == 2
        assert result["exchange"] == "NasdaqGS"
        assert result["data_source"] == "yfinance"
        # market_cap / company_name are filled by the route, not here.
        assert result["market_cap"] is None
        assert result["company_name"] is None

    @pytest.mark.asyncio
    async def test_change_computed_from_history(self):
        result = await _fetch(_FakeLayer(result=_price_result()))
        # 101.5 → 102.5: +1.0, +0.985%
        assert result["change"] == pytest.approx(1.0)
        assert result["change_pct"] == pytest.approx(0.985, abs=0.01)

    @pytest.mark.asyncio
    async def test_fetched_at_is_iso8601_tz_aware(self):
        result = await _fetch(_FakeLayer(result=_price_result()))
        fetched = datetime.fromisoformat(result["fetched_at"])
        assert fetched.tzinfo is not None


class TestFetchPriceHistoryErrorMapping:
    @pytest.mark.asyncio
    async def test_rate_limit_provider_error_propagates_502(self):
        """A service-down ProviderError (429) re-raises as ProviderError → 502."""
        layer = _FakeLayer(raises=ProviderError("HTTP Error 429: Too Many Requests"))
        with pytest.raises(ProviderError):
            await _fetch(layer)

    @pytest.mark.asyncio
    async def test_timeout_provider_error_propagates_502(self):
        layer = _FakeLayer(raises=ProviderError("connection timeout fetching AAPL"))
        with pytest.raises(ProviderError):
            await _fetch(layer)

    @pytest.mark.asyncio
    async def test_non_service_down_provider_error_becomes_value_error_422(self):
        """A non-service-down provider error (delisted/unknown) → ValueError → 422."""
        layer = _FakeLayer(raises=ProviderError("Ticker 'XYZ' not found or returned no data"))
        with pytest.raises(ValueError):
            await _fetch(layer, "XYZ")

    @pytest.mark.asyncio
    async def test_empty_data_raises_value_error_422(self):
        """No current_price and no history → invalid ticker → ValueError."""
        layer = _FakeLayer(result=_price_result(current_price=None, history=[]))
        with pytest.raises(ValueError):
            await _fetch(layer, "XYZINVALID")


class TestChangeFromHistory:
    def test_two_closes(self):
        change, pct = _change_from_history(
            [{"close": 100.0}, {"close": 110.0}]
        )
        assert change == pytest.approx(10.0)
        assert pct == pytest.approx(10.0)

    def test_single_close_returns_none(self):
        assert _change_from_history([{"close": 100.0}]) == (None, None)

    def test_zero_prev_close_returns_none(self):
        assert _change_from_history([{"close": 0.0}, {"close": 5.0}]) == (None, None)

    def test_ignores_non_numeric_rows(self):
        change, pct = _change_from_history(
            [{"close": "bad"}, {"close": 100.0}, {"close": 105.0}]
        )
        assert change == pytest.approx(5.0)
