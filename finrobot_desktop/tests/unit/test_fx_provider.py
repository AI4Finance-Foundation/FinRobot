"""Tests for engine/data/providers/fx.py — FX rate provider."""

from __future__ import annotations

from typing import cast

import httpx
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
        monkeypatch.setattr(fx_module.yf, "Ticker", lambda *_a, **_k: pytest.fail("unreachable"))
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
        monkeypatch.setattr(fx_module.yf, "Ticker", lambda symbol: _FakeTicker(0.03125))
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
        """yfinance no-quote AND no FMP key → ProviderError naming yfinance only."""
        monkeypatch.setattr(fx_module.yf, "Ticker", lambda _: _FakeTicker(None))
        with pytest.raises(ProviderError, match=r"No spot FX quote.*TWDUSD=X"):
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
        monkeypatch.setattr(fx_module.yf, "Ticker", lambda _: _FakeTicker(float("nan")))
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


class TestFmpFallback:
    """yfinance shares Yahoo's rate-limit budget with every peer quote, so under
    a 429 storm the FX read is the first thing to fail. FMP is an independent
    source consulted only when a key is supplied AND yfinance returned nothing."""

    @pytest.mark.asyncio
    async def test_fmp_used_when_yfinance_returns_none(self, monkeypatch):
        monkeypatch.setattr(fx_module.yf, "Ticker", lambda _: _FakeTicker(None))

        async def _fake_fmp(from_ccy, api_key):
            assert from_ccy == "CNY"
            assert api_key == "key123"
            return 0.1478

        monkeypatch.setattr(fx_module, "_fmp_fx_rate_to_usd", _fake_fmp)
        rate = await fetch_fx_rate_to_usd("CNY", fmp_api_key="key123")
        assert rate == pytest.approx(0.1478)

    @pytest.mark.asyncio
    async def test_yfinance_primary_skips_fmp_when_it_succeeds(self, monkeypatch):
        """FMP must NOT be hit when yfinance already returned a good quote."""
        monkeypatch.setattr(fx_module.yf, "Ticker", lambda _: _FakeTicker(0.1480))

        async def _explode_fmp(*_a, **_k):
            pytest.fail("FMP must not be consulted when yfinance succeeds")

        monkeypatch.setattr(fx_module, "_fmp_fx_rate_to_usd", _explode_fmp)
        rate = await fetch_fx_rate_to_usd("CNY", fmp_api_key="key123")
        assert rate == pytest.approx(0.1480)

    @pytest.mark.asyncio
    async def test_both_sources_fail_raises_mentioning_fmp(self, monkeypatch):
        monkeypatch.setattr(fx_module.yf, "Ticker", lambda _: _FakeTicker(None))

        async def _fmp_none(*_a, **_k):
            return None

        monkeypatch.setattr(fx_module, "_fmp_fx_rate_to_usd", _fmp_none)
        with pytest.raises(ProviderError, match=r"yfinance.*or FMP"):
            await fetch_fx_rate_to_usd("CNY", fmp_api_key="key123")

    @pytest.mark.asyncio
    async def test_fmp_inverse_pair_inverted(self, monkeypatch):
        """When only USD{FROM} quotes (e.g. USDCNY≈6.77), invert to FROM→USD."""

        async def _fake_quote(client, pair, api_key):
            return 6.77 if pair == "USDCNY" else None

        monkeypatch.setattr(fx_module, "_fmp_quote_price", _fake_quote)
        rate = await fx_module._fmp_fx_rate_to_usd("CNY", "key123")
        assert rate == pytest.approx(1.0 / 6.77)


class _FakeResp:
    """Minimal httpx.Response stand-in for _fmp_quote_price unit tests."""

    def __init__(self, *, json_data=None, raise_for_status_exc=None, json_exc=None):
        self._json_data = json_data
        self._raise_for_status_exc = raise_for_status_exc
        self._json_exc = json_exc

    def raise_for_status(self):
        if self._raise_for_status_exc is not None:
            raise self._raise_for_status_exc

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._json_data


class _FakeClient:
    def __init__(self, resp):
        self._resp = resp
        self.calls: list[dict] = []

    async def get(self, url, params=None):
        self.calls.append({"url": url, "params": params})
        return self._resp


async def _quote(client: _FakeClient, pair: str = "USDCNY", api_key: str = "key") -> float | None:
    """Call _fmp_quote_price with the fake client cast to its typed param."""
    return await fx_module._fmp_quote_price(cast(httpx.AsyncClient, client), pair, api_key)


class TestFmpQuotePriceBody:
    """Direct coverage of _fmp_quote_price's HTTP/parse body — the existing
    TestFmpFallback monkeypatches the whole function away, so its failure
    branches (the yfinance-429-storm last-resort FX path) were untested."""

    @pytest.mark.asyncio
    async def test_valid_quote_returns_price(self):
        client = _FakeClient(_FakeResp(json_data=[{"symbol": "USDCNY", "price": 6.77}]))
        rate = await _quote(client)
        assert rate == pytest.approx(6.77)
        # query carries the pair symbol + key (key never asserted-printed elsewhere)
        assert client.calls[0]["params"] == {"symbol": "USDCNY", "apikey": "key"}

    @pytest.mark.asyncio
    async def test_int_price_coerced_to_float(self):
        client = _FakeClient(_FakeResp(json_data=[{"price": 1}]))
        rate = await _quote(client, "EURUSD")
        assert isinstance(rate, float) and rate == 1.0

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self):
        client = _FakeClient(_FakeResp(raise_for_status_exc=httpx.HTTPError("429")))
        assert await _quote(client) is None

    @pytest.mark.asyncio
    async def test_json_decode_error_returns_none(self):
        client = _FakeClient(_FakeResp(json_exc=ValueError("not json")))
        assert await _quote(client) is None

    @pytest.mark.asyncio
    async def test_non_list_payload_returns_none(self):
        client = _FakeClient(_FakeResp(json_data={"price": 6.77}))
        assert await _quote(client) is None

    @pytest.mark.asyncio
    async def test_empty_list_returns_none(self):
        client = _FakeClient(_FakeResp(json_data=[]))
        assert await _quote(client) is None

    @pytest.mark.asyncio
    async def test_first_element_not_dict_returns_none(self):
        client = _FakeClient(_FakeResp(json_data=["6.77"]))
        assert await _quote(client) is None

    @pytest.mark.asyncio
    async def test_missing_price_key_returns_none(self):
        client = _FakeClient(_FakeResp(json_data=[{"symbol": "USDCNY"}]))
        assert await _quote(client) is None

    @pytest.mark.asyncio
    async def test_non_numeric_price_returns_none(self):
        client = _FakeClient(_FakeResp(json_data=[{"price": "n/a"}]))
        assert await _quote(client) is None

    @pytest.mark.asyncio
    async def test_zero_price_returns_none(self):
        client = _FakeClient(_FakeResp(json_data=[{"price": 0}]))
        assert await _quote(client) is None

    @pytest.mark.asyncio
    async def test_negative_price_returns_none(self):
        client = _FakeClient(_FakeResp(json_data=[{"price": -1.0}]))
        assert await _quote(client) is None

    @pytest.mark.asyncio
    async def test_nan_price_returns_none(self):
        client = _FakeClient(_FakeResp(json_data=[{"price": float("nan")}]))
        assert await _quote(client) is None


class TestFmpFxRateDirectPair:
    @pytest.mark.asyncio
    async def test_direct_pair_used_without_inverse(self, monkeypatch):
        """When {FROM}USD quotes directly (e.g. CNYUSD≈0.1478), use it as-is and
        never consult the USD{FROM} inverse pair."""
        seen: list[str] = []

        async def _fake_quote(client, pair, api_key):
            seen.append(pair)
            return 0.1478 if pair == "CNYUSD" else pytest.fail(f"inverse hit: {pair}")

        monkeypatch.setattr(fx_module, "_fmp_quote_price", _fake_quote)
        rate = await fx_module._fmp_fx_rate_to_usd("CNY", "key")
        assert rate == pytest.approx(0.1478)
        assert seen == ["CNYUSD"]  # inverse never attempted

    @pytest.mark.asyncio
    async def test_both_pairs_miss_returns_none(self, monkeypatch):
        async def _none(client, pair, api_key):
            return None

        monkeypatch.setattr(fx_module, "_fmp_quote_price", _none)
        assert await fx_module._fmp_fx_rate_to_usd("CNY", "key") is None

    @pytest.mark.asyncio
    async def test_inverse_zero_guarded_returns_none(self, monkeypatch):
        """A 0.0 inverse quote must not divide-by-zero — guarded to None."""

        async def _quote(client, pair, api_key):
            return 0.0 if pair == "USDCNY" else None

        monkeypatch.setattr(fx_module, "_fmp_quote_price", _quote)
        assert await fx_module._fmp_fx_rate_to_usd("CNY", "key") is None


class TestFxCaching:
    @pytest.mark.asyncio
    async def test_repeat_currency_fetches_spot_once(self, monkeypatch):
        """A comps fan-out converting many same-currency peers reads the spot once,
        not once per peer — the bug this fixes."""
        calls = {"n": 0}

        def _make(symbol):
            calls["n"] += 1
            return _FakeTicker(0.03125)

        monkeypatch.setattr(fx_module.yf, "Ticker", _make)
        r1 = await fetch_fx_rate_to_usd("TWD")
        r2 = await fetch_fx_rate_to_usd("TWD")
        r3 = await fetch_fx_rate_to_usd("TWD")
        assert r1 == r2 == r3 == 0.03125
        assert calls["n"] == 1  # cached after the first

    @pytest.mark.asyncio
    async def test_concurrent_same_currency_single_flight(self, monkeypatch):
        """Concurrent identical misses (a peer fan-out hitting the cold cache at
        once) collapse onto a single upstream fetch."""
        import asyncio

        calls = {"n": 0}

        def _make(symbol):
            calls["n"] += 1
            return _FakeTicker(1.08)

        monkeypatch.setattr(fx_module.yf, "Ticker", _make)
        rates = await asyncio.gather(*[fetch_fx_rate_to_usd("EUR") for _ in range(6)])
        assert all(r == 1.08 for r in rates)
        assert calls["n"] == 1

    @pytest.mark.asyncio
    async def test_distinct_currencies_cached_independently(self, monkeypatch):
        seen: list[str] = []

        def _make(symbol):
            seen.append(symbol)
            return _FakeTicker(2.0 if symbol.startswith("GBP") else 0.5)

        monkeypatch.setattr(fx_module.yf, "Ticker", _make)
        await fetch_fx_rate_to_usd("GBP")
        await fetch_fx_rate_to_usd("JPY")
        await fetch_fx_rate_to_usd("GBP")  # cached
        await fetch_fx_rate_to_usd("JPY")  # cached
        assert sorted(seen) == ["GBPUSD=X", "JPYUSD=X"]

    @pytest.mark.asyncio
    async def test_failure_is_not_cached(self, monkeypatch):
        """A transient failure must not poison the slot — only successes are
        cached, so a 429-stranded rate can recover on the next call."""
        state: dict[str, float | None] = {"price": None}

        def _make(symbol):
            return _FakeTicker(state["price"])

        monkeypatch.setattr(fx_module.yf, "Ticker", _make)
        with pytest.raises(ProviderError):
            await fetch_fx_rate_to_usd("TWD")  # no quote, no fmp key → raises, NOT cached
        state["price"] = 0.03  # source recovers
        assert await fetch_fx_rate_to_usd("TWD") == 0.03

    @pytest.mark.asyncio
    async def test_clear_fx_cache_forces_refetch(self, monkeypatch):
        calls = {"n": 0}

        def _make(symbol):
            calls["n"] += 1
            return _FakeTicker(0.9)

        monkeypatch.setattr(fx_module.yf, "Ticker", _make)
        await fetch_fx_rate_to_usd("CHF")
        fx_module.clear_fx_cache()
        await fetch_fx_rate_to_usd("CHF")
        assert calls["n"] == 2
