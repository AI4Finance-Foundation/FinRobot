"""Finnhub Provider unit tests. All HTTP calls are mocked."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from finrobot.engine.data.interface import (
    DataResult,
    ProviderError,
    RateLimitedProviderError,
    is_rate_limit_error,
)
from finrobot.engine.data.providers.finnhub_provider import FinnhubProvider


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
        "currency": "USD",
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
    async def test_profile_no_longer_supported(self, provider):
        """PROFILE was a DEAD capability (nothing in the codebase fetches
        DataType.PROFILE) AND a 0-fabrication landmine — _fetch_profile coerced a
        missing marketCapitalization/shareOutstanding to a fake $0 / 0 shares.
        Removed 2026-06-10: it must now raise, not fabricate."""
        assert "profile" not in provider.capabilities()
        with pytest.raises(ProviderError, match="not supported"):
            await provider.fetch("AAPL", "profile")

    @pytest.mark.asyncio
    async def test_unsupported_type_raises(self, provider):
        with pytest.raises(ProviderError, match="not supported"):
            await provider.fetch("AAPL", "unknown_type")

    @pytest.mark.asyncio
    async def test_financials_no_longer_supported(self, provider):
        """Finnhub dropped FINANCIALS (option B, 2026-06-08): its XBRL parser never
        worked, and fundamentals are owned by FMP + yfinance. Must raise, not
        silently return all-None fundamentals into FMP's cross-validation."""
        assert "financials" not in provider.capabilities()
        with pytest.raises(ProviderError, match="not supported"):
            await provider.fetch("AAPL", "financials")

    @pytest.mark.asyncio
    async def test_timeout_raises_provider_error(self, provider):
        with patch.object(
            provider, "_get", AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        ):
            with pytest.raises(ProviderError, match="timeout"):
                await provider.fetch("AAPL", "price")


class TestFinnhubInterface:
    def test_name(self, provider):
        assert provider.name == "finnhub"

    def test_capabilities(self, provider):
        caps = provider.capabilities()
        # FINANCIALS removed (option B): fundamentals are FMP + yfinance.
        # PROFILE removed 2026-06-10: dead capability + 0-fabrication landmine.
        assert "financials" not in caps
        assert "profile" not in caps
        assert "price" in caps
        assert "news" in caps

    def test_price_in_capabilities(self, provider):
        assert "price" in provider.capabilities()


def _finnhub_quote_response(price: float = 175.5) -> dict:
    """Mock Finnhub /quote response (single object; arrays only on /stock/candle).

    Finnhub field shape: c=current price, h/l/o=day high/low/open, pc=prev close,
    t=unix timestamp.
    """
    return {
        "c": price,
        "d": 1.23,
        "dp": 0.71,
        "h": 176.4,
        "l": 173.1,
        "o": 174.0,
        "pc": 174.27,
        "t": 1_730_476_800,
    }


_CANDLE_DATES = ("2026-05-21", "2026-05-22", "2026-05-23")


def _ts(iso_date: str) -> int:
    from datetime import datetime, timezone

    return int(datetime.fromisoformat(iso_date).replace(tzinfo=timezone.utc).timestamp())


def _finnhub_candle_response(days: int = 3) -> dict:
    """Mock Finnhub /stock/candle response — parallel arrays, oldest-first.

    s='ok' on success; t are unix-second timestamps (derived from the calendar
    dates so the decoded bar dates round-trip exactly); o/h/l/c/v are parallel.
    """
    base = [
        (_CANDLE_DATES[0], 170.0, 172.5, 169.5, 172.0, 45_000_000),
        (_CANDLE_DATES[1], 172.0, 174.5, 171.0, 174.0, 48_000_000),
        (_CANDLE_DATES[2], 174.0, 176.0, 173.5, 175.0, 50_000_000),
    ][:days]
    return {
        "s": "ok",
        "t": [_ts(row[0]) for row in base],
        "o": [row[1] for row in base],
        "h": [row[2] for row in base],
        "l": [row[3] for row in base],
        "c": [row[4] for row in base],
        "v": [row[5] for row in base],
    }


class TestFinnhubPrice:
    """PRICE = the third live-quote leg (yfinance dead + no FMP key). Shape must
    match YFinance/FMP _fetch_price: current_price + price_history + exchange."""

    @pytest.mark.asyncio
    async def test_fetch_price_returns_provider_agnostic_shape(self, provider):
        responses = [
            _mock_response(_finnhub_quote_response(price=175.5)),
            _mock_response(_finnhub_profile_response()),
            _mock_response(_finnhub_candle_response(days=3)),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "price")

        assert isinstance(result, DataResult)
        assert result.provider == "finnhub"
        assert result.ticker == "AAPL"
        assert result.data_type == "price"
        assert result.data["current_price"] == 175.5
        assert result.data["exchange"] == "NASDAQ"
        assert result.data["quote_currency"] == "USD"
        history = result.data["price_history"]
        # Oldest-first ordering — the 52w high/low window relies on it.
        assert [p["date"] for p in history] == list(_CANDLE_DATES)
        assert history[0]["close"] == 172.0
        assert history[-1]["close"] == 175.0
        # Every bar carries the full OHLCV contract (same keys as yfinance/FMP).
        for bar in history:
            assert set(bar.keys()) == {"date", "open", "high", "low", "close", "volume"}

    @pytest.mark.asyncio
    async def test_fetch_price_candle_403_degrades_to_quote_only(self, provider):
        """/stock/candle is premium-only on the free tier (HTTP 403). Degrade to
        a quote-only PRICE (live price, empty history) instead of 500ing — that's
        the whole point of this leg for FMP-less free-tier users.

        ``_get`` raises HTTPStatusError on a 4xx (it calls raise_for_status), so
        the mock side_effect raises it directly for the candle call.
        """
        candle_403_resp = _mock_response({"error": "You don't have access."}, status_code=403)
        candle_403 = httpx.HTTPStatusError("403", request=MagicMock(), response=candle_403_resp)
        responses = [
            _mock_response(_finnhub_quote_response(price=200.0)),
            _mock_response(_finnhub_profile_response()),
            candle_403,
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "price")
        assert result.data["current_price"] == 200.0
        assert result.data["exchange"] == "NASDAQ"
        assert result.data["price_history"] == []

    @pytest.mark.asyncio
    async def test_fetch_price_candle_no_data_yields_empty_history(self, provider):
        """s != 'ok' (no_data body, not an HTTP error) → empty history, live price kept."""
        responses = [
            _mock_response(_finnhub_quote_response(price=88.0)),
            _mock_response(_finnhub_profile_response()),
            _mock_response({"s": "no_data"}),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "price")
        assert result.data["current_price"] == 88.0
        assert result.data["price_history"] == []

    @pytest.mark.asyncio
    async def test_fetch_price_zero_quote_raises(self, provider):
        """Finnhub returns c=0 for an unknown/delisted symbol — must raise so
        DataLayer falls through, not stamp a fabricated $0 live price."""
        with patch.object(
            provider,
            "_get",
            AsyncMock(return_value=_mock_response(_finnhub_quote_response(price=0.0))),
        ):
            with pytest.raises(ProviderError, match="no usable price"):
                await provider.fetch("DELISTED", "price")

    @pytest.mark.asyncio
    async def test_fetch_price_normalizes_to_canonical_price(self, provider):
        """End-to-end: the Finnhub PRICE result must normalize identically to the
        other providers — current_price preserved, bars built, exchange carried."""
        from finrobot.engine.data.normalize.price import normalize_price

        responses = [
            _mock_response(_finnhub_quote_response(price=175.5)),
            _mock_response(_finnhub_profile_response()),
            _mock_response(_finnhub_candle_response(days=3)),
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("AAPL", "price")
        norm = normalize_price(result)
        assert norm.current_price == 175.5
        assert norm.exchange == "NASDAQ"
        assert norm.quote_currency == "USD"
        assert len(norm.bars) == 3
        assert norm.is_ohlc_complete is True

    @pytest.mark.asyncio
    async def test_fetch_price_candle_non_403_http_error_propagates(self, provider):
        """A non-403 candle failure (e.g. 500) must NOT be swallowed — it should
        surface as a ProviderError so a real outage isn't masked as empty history."""
        candle_500_resp = _mock_response({"error": "server error"}, status_code=500)
        candle_500 = httpx.HTTPStatusError("500", request=MagicMock(), response=candle_500_resp)
        responses = [
            _mock_response(_finnhub_quote_response(price=175.5)),
            _mock_response(_finnhub_profile_response()),
            candle_500,
        ]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            with pytest.raises(ProviderError, match="API error"):
                await provider.fetch("AAPL", "price")


def _finnhub_news_response():
    return [
        {
            "headline": "Apple Q4 Beat",
            "source": "Reuters",
            "datetime": 1730390400,
            "url": "https://example.com/1",
            "category": "company news",
        },
        {
            "headline": "iPhone strong",
            "source": "Bloomberg",
            "datetime": 1730304000,
            "url": "https://example.com/2",
            "category": "company news",
        },
    ]


class TestFinnhubNews:
    @pytest.mark.asyncio
    async def test_fetch_news(self, provider):
        with patch.object(
            provider, "_get", AsyncMock(return_value=_mock_response(_finnhub_news_response()))
        ):
            result = await provider.fetch("AAPL", "news")
        assert result.data_type == "news"
        items = result.data["news_items"]
        assert len(items) == 2
        assert items[0]["title"] == "Apple Q4 Beat"

    @pytest.mark.asyncio
    async def test_news_in_capabilities(self, provider):
        assert "news" in provider.capabilities()


class TestFinnhubNetworkErrors:
    """New catch branches: ConnectError / RemoteProtocolError / ReadError / WriteError."""

    @pytest.mark.asyncio
    async def test_connect_error_raises_provider_error(self, provider):
        with patch.object(
            provider,
            "_get",
            AsyncMock(side_effect=httpx.ConnectError("connection refused")),
        ):
            with pytest.raises(ProviderError, match="network error"):
                await provider.fetch("AAPL", "price")

    @pytest.mark.asyncio
    async def test_remote_protocol_error_raises_provider_error(self, provider):
        with patch.object(
            provider,
            "_get",
            AsyncMock(side_effect=httpx.RemoteProtocolError("unexpected EOF")),
        ):
            with pytest.raises(ProviderError, match="network error"):
                await provider.fetch("AAPL", "price")

    @pytest.mark.asyncio
    async def test_read_error_raises_provider_error(self, provider):
        with patch.object(
            provider,
            "_get",
            AsyncMock(side_effect=httpx.ReadError("read failed")),
        ):
            with pytest.raises(ProviderError, match="network error"):
                await provider.fetch("AAPL", "news")

    @pytest.mark.asyncio
    async def test_write_error_raises_provider_error(self, provider):
        with patch.object(
            provider,
            "_get",
            AsyncMock(side_effect=httpx.WriteError("write failed")),
        ):
            with pytest.raises(ProviderError, match="network error"):
                await provider.fetch("AAPL", "price")

    @pytest.mark.asyncio
    async def test_http_429_raises_typed_rate_limited_error(self, provider):
        """A Finnhub 429 (60 req/min free tier) must surface as the TYPED
        RateLimitedProviderError so classification survives any upstream
        rewording; substring matching is fallback only."""
        request = httpx.Request("GET", "https://finnhub.io/api/v1/quote?symbol=AAPL")
        response = httpx.Response(429, request=request)
        with patch.object(
            provider,
            "_get",
            AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "Client error '429 Too Many Requests' for url "
                    "'https://finnhub.io/api/v1/quote?symbol=AAPL'",
                    request=request,
                    response=response,
                )
            ),
        ):
            with pytest.raises(RateLimitedProviderError) as exc_info:
                await provider.fetch("AAPL", "price")
        assert is_rate_limit_error(exc_info.value)
        message = str(exc_info.value)
        assert "HTTP 429" in message
        assert "finnhub.io" not in message
        assert "for url" not in message

    @pytest.mark.asyncio
    async def test_non_429_http_error_is_clean_no_raw_url(self, provider):
        request = httpx.Request("GET", "https://finnhub.io/api/v1/quote?symbol=AAPL")
        response = httpx.Response(500, request=request)
        with patch.object(
            provider,
            "_get",
            AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "Server error '500 Internal Server Error' for url "
                    "'https://finnhub.io/api/v1/quote?symbol=AAPL'",
                    request=request,
                    response=response,
                )
            ),
        ):
            with pytest.raises(ProviderError) as exc_info:
                await provider.fetch("AAPL", "price")
        message = str(exc_info.value)
        assert "HTTP 500" in message
        assert "finnhub.io" not in message
        assert "for url" not in message


class TestFinnhubRateLimiter:
    def test_provider_has_rate_limit_attributes(self, provider):
        """Rate limiter requires _lock and _last_call on every instance."""
        import asyncio

        assert hasattr(provider, "_lock")
        assert isinstance(provider._lock, asyncio.Lock)
        assert hasattr(provider, "_last_call")
        assert isinstance(provider._last_call, float)

    @pytest.mark.asyncio
    async def test_rate_limiter_sleeps_on_rapid_calls(self, provider, monkeypatch):
        """Second call within MIN_INTERVAL must trigger asyncio.sleep."""
        import asyncio
        import time
        from finrobot.engine.data.providers.finnhub_provider import _MIN_INTERVAL

        sleep_durations: list[float] = []

        async def mock_sleep(secs: float) -> None:
            sleep_durations.append(secs)

        monkeypatch.setattr(asyncio, "sleep", mock_sleep)

        # Simulate last call happening just now
        provider._last_call = time.monotonic()

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        # Provider now owns a long-lived httpx client (instantiated in __init__)
        # so we monkeypatch the per-instance .get instead of httpx.AsyncClient.
        provider._client.get = AsyncMock(return_value=mock_resp)

        await provider._get("/test")

        assert len(sleep_durations) == 1
        assert sleep_durations[0] <= _MIN_INTERVAL
        assert sleep_durations[0] > 0

    @pytest.mark.asyncio
    async def test_get_does_not_serialize_concurrent_http(self, provider, monkeypatch):
        """Sibling of the FMP fix: the lock paces request STARTS but must not wrap
        the HTTP round-trip, so concurrent _get calls are all in flight at once.
        Pre-fix they ran one-at-a-time → this would deadlock and trip the timeout."""
        import asyncio

        monkeypatch.setattr(asyncio, "sleep", AsyncMock())  # don't wait real pacing
        provider._last_call = 0.0

        n = 3
        in_flight = 0
        max_in_flight = 0
        all_in = asyncio.Event()

        async def slow_get(*args, **kwargs):
            nonlocal in_flight, max_in_flight
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            if in_flight >= n:
                all_in.set()
            await all_in.wait()
            in_flight -= 1
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            return resp

        provider._client.get = slow_get
        await asyncio.wait_for(
            asyncio.gather(*[provider._get(f"/p{i}") for i in range(n)]), timeout=2.0
        )
        assert max_in_flight == n
