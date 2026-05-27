"""Tests for engine/data/providers/fx.py — FX rate provider."""

from __future__ import annotations

import pytest

from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.providers import fx as fx_module
from finrobot.engine.data.providers.fx import _fx_ticker, fetch_fx_rate_to_usd


class TestTickerConstruction:
    def test_twd_usd(self):
        assert _fx_ticker("TWD", "USD") == "TWDUSD=X"

    def test_lowercase_input_normalized(self):
        assert _fx_ticker("eur", "usd") == "EURUSD=X"

    def test_jpy_usd(self):
        assert _fx_ticker("JPY", "USD") == "JPYUSD=X"


class TestUsdFastPath:
    @pytest.mark.asyncio
    async def test_usd_to_usd_returns_one_without_network(self, monkeypatch):
        """USD → USD must not touch the network — same-currency fast path."""
        called = {"count": 0}

        def _explode(*_args, **_kwargs):
            called["count"] += 1
            raise RuntimeError("network call must not happen for USD→USD")

        monkeypatch.setattr(fx_module.yf, "Ticker", _explode)
        rate = await fetch_fx_rate_to_usd("USD")
        assert rate == 1.0
        assert called["count"] == 0

    @pytest.mark.asyncio
    async def test_lowercase_usd_treated_as_usd(self, monkeypatch):
        monkeypatch.setattr(
            fx_module.yf, "Ticker", lambda *_a, **_k: pytest.fail("unreachable")
        )
        assert await fetch_fx_rate_to_usd("usd") == 1.0


class _FakeFastInfo:
    def __init__(self, last_price):
        self.last_price = last_price


class _FakeTicker:
    def __init__(self, last_price):
        self.fast_info = _FakeFastInfo(last_price)


class TestSuccessfulFetch:
    @pytest.mark.asyncio
    async def test_returns_float_from_yfinance(self, monkeypatch):
        monkeypatch.setattr(
            fx_module.yf, "Ticker", lambda symbol: _FakeTicker(0.03125)
        )
        rate = await fetch_fx_rate_to_usd("TWD")
        assert rate == pytest.approx(0.03125)

    @pytest.mark.asyncio
    async def test_int_coerced_to_float(self, monkeypatch):
        monkeypatch.setattr(fx_module.yf, "Ticker", lambda _: _FakeTicker(1))
        rate = await fetch_fx_rate_to_usd("EUR")
        assert isinstance(rate, float)
        assert rate == 1.0


class TestProviderErrorOnBadQuote:
    @pytest.mark.asyncio
    async def test_none_quote_raises_provider_error(self, monkeypatch):
        monkeypatch.setattr(fx_module.yf, "Ticker", lambda _: _FakeTicker(None))
        with pytest.raises(ProviderError, match="no spot FX quote for TWDUSD=X"):
            await fetch_fx_rate_to_usd("TWD")

    @pytest.mark.asyncio
    async def test_zero_quote_raises(self, monkeypatch):
        monkeypatch.setattr(fx_module.yf, "Ticker", lambda _: _FakeTicker(0.0))
        with pytest.raises(ProviderError):
            await fetch_fx_rate_to_usd("JPY")

    @pytest.mark.asyncio
    async def test_negative_quote_raises(self, monkeypatch):
        monkeypatch.setattr(fx_module.yf, "Ticker", lambda _: _FakeTicker(-1.0))
        with pytest.raises(ProviderError):
            await fetch_fx_rate_to_usd("EUR")

    @pytest.mark.asyncio
    async def test_nan_quote_raises(self, monkeypatch):
        monkeypatch.setattr(
            fx_module.yf, "Ticker", lambda _: _FakeTicker(float("nan"))
        )
        with pytest.raises(ProviderError):
            await fetch_fx_rate_to_usd("GBP")

    @pytest.mark.asyncio
    async def test_attribute_error_raises_provider_error(self, monkeypatch):
        """yfinance occasionally returns a Ticker whose fast_info raises on
        attribute access (rate-limited, partial data). Treat as no-quote."""

        class _BrokenFastInfo:
            @property
            def last_price(self):
                raise AttributeError("simulated missing attr")

        class _BrokenTicker:
            fast_info = _BrokenFastInfo()

        monkeypatch.setattr(fx_module.yf, "Ticker", lambda _: _BrokenTicker())
        with pytest.raises(ProviderError):
            await fetch_fx_rate_to_usd("KRW")
