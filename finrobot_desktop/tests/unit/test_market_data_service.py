"""Unit tests for finrobot/engine/services/market_data.py (ADR-0006 Step 5).

fetch_price_history now fetches through DataLayer.fetch_canonical(PRICE) and
computes day-over-day change via NormalizedPrice.latest_session_change() instead
of the removed _change_from_history raw-dict helper.

The _FakeLayer provides fetch_canonical returning a NormalizedPrice built from
a raw DataResult fixture so the test data shape is unchanged.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from finrobot.engine.data.interface import DataResult, ProviderError
from finrobot.engine.data.normalize.contracts import NormalizedPrice
from finrobot.engine.data.normalize.price import normalize_price
from finrobot.engine.data.types import DataType
from finrobot.engine.services.market_data import fetch_price_history


def _price_raw(
    *,
    current_price: float | None = 152.0,
    history: list[dict[str, Any]] | None = None,
    exchange: str | None = "NasdaqGS",
    provider: str = "yfinance",
    quote_currency: str = "USD",
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
            "quote_currency": quote_currency,
        },
        provider=provider,
        ticker="AAPL",
        data_type=DataType.PRICE,
        timestamp=datetime.now(tz=timezone.utc),
    )


class _FakeLayer:
    """DataLayer stand-in exposing fetch_canonical(PRICE) → NormalizedPrice."""

    def __init__(
        self, *, result: DataResult | None = None, raises: Exception | None = None
    ) -> None:
        self._result = result
        self._raises = raises

    async def fetch_canonical(self, data_type: Any, ticker: str) -> NormalizedPrice:
        if self._raises is not None:
            raise self._raises
        assert self._result is not None
        return normalize_price(self._result)


async def _fetch(layer: _FakeLayer, ticker: str = "AAPL") -> dict[str, Any]:
    return await fetch_price_history(layer, ticker)  # type: ignore[arg-type]


class TestFetchPriceHistorySuccess:
    @pytest.mark.asyncio
    async def test_returns_payload_shape(self):
        result = await _fetch(_FakeLayer(result=_price_raw()))
        # current_price comes from the raw dict field (152.0 in _price_raw default)
        assert result["current_price"] == pytest.approx(152.0)
        assert len(result["history"]) == 2
        assert result["exchange"] == "NasdaqGS"
        assert result["data_source"] == "yfinance"
        # market_cap / company_name are filled by the route, not here.
        assert result["market_cap"] is None
        assert result["company_name"] is None

    @pytest.mark.asyncio
    async def test_carries_quote_currency_for_cross_currency_consumers(self):
        """The payload must carry the live price's native quote currency. The
        canonical PRICE is NEVER FX-normalized, so a foreign LOCAL listing's price
        is in the exchange currency — consumers comparing it against a USD artifact
        target (the verdict gauge) need the tag to abstain rather than mix."""
        # US issuer → USD.
        usd = await _fetch(_FakeLayer(result=_price_raw()))
        assert usd["quote_currency"] == "USD"
        # Foreign LOCAL listing → native exchange currency, NOT USD.
        twd = await _fetch(_FakeLayer(result=_price_raw(quote_currency="TWD")))
        assert twd["quote_currency"] == "TWD"

    @pytest.mark.asyncio
    async def test_change_computed_from_history(self):
        result = await _fetch(_FakeLayer(result=_price_raw()))
        # 101.5 → 102.5: +1.0, +0.985%
        assert result["change"] == pytest.approx(1.0)
        assert result["change_pct"] == pytest.approx(0.985, abs=0.01)

    @pytest.mark.asyncio
    async def test_fetched_at_is_iso8601_tz_aware(self):
        result = await _fetch(_FakeLayer(result=_price_raw()))
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
        """No bars and no current_price → invalid ticker → ValueError."""
        layer = _FakeLayer(result=_price_raw(current_price=None, history=[]))
        with pytest.raises(ValueError):
            await _fetch(layer, "XYZINVALID")


class TestLatestSessionChange:
    """NormalizedPrice.latest_session_change() replaces the removed _change_from_history.

    These tests verify the canonical method's contract (which the service now uses).
    """

    def _price(self, bars: list[dict[str, Any]]) -> NormalizedPrice:
        raw = DataResult(
            data={"current_price": bars[-1]["close"], "price_history": bars},
            provider="test",
            ticker="TEST",
            data_type=DataType.PRICE,
            timestamp=datetime.now(tz=timezone.utc),
        )
        return normalize_price(raw)

    def test_two_closes(self):
        price = self._price(
            [
                {"date": "2026-05-26", "close": 100.0},
                {"date": "2026-05-27", "close": 110.0},
            ]
        )
        change, pct = price.latest_session_change()
        assert change == pytest.approx(10.0)
        assert pct == pytest.approx(10.0)

    def test_single_bar_returns_none(self):
        price = self._price([{"date": "2026-05-27", "close": 100.0}])
        assert price.latest_session_change() == (None, None)

    def test_zero_prev_close_returns_none(self):
        price = self._price(
            [
                {"date": "2026-05-26", "close": 0.0},
                {"date": "2026-05-27", "close": 5.0},
            ]
        )
        assert price.latest_session_change() == (None, None)
