"""Adanos Provider unit tests. All HTTP calls are mocked."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from finrobot.engine.data.interface import (
    DataResult,
    ProviderError,
    RateLimitedProviderError,
    is_rate_limit_error,
)
from finrobot.engine.data.providers.adanos_provider import (
    _PLATFORM_SPECS,
    AdanosProvider,
    _compute_alignment,
    _normalize_source,
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
        # spread = 62-55 = 7 (<=10) → sources agree; direction lives in the bar
        assert result.data["source_alignment"] == "aligned"
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
    async def test_fetch_all_sources_fail_raises_provider_error(self, provider):
        """EVERY platform attempt raised → this is a provider-level failure, NOT a
        "no buzz" answer. The provider must RAISE so the DataLayer failure path
        engages (stale fallback + circuit breaker) instead of returning a
        successful empty 0/3 snapshot that poisons the cache and records a false
        success. Timeouts aren't throttling, so it's a plain ProviderError."""

        async def mock_get(path, params=None):
            raise httpx.TimeoutException("timeout")

        with patch.object(provider, "_get", side_effect=mock_get):
            with pytest.raises(ProviderError) as exc_info:
                await provider.fetch("AAPL", "sentiment")
        # Timeouts are not rate-limit — must NOT be classified as throttling.
        assert not is_rate_limit_error(exc_info.value)

    @pytest.mark.asyncio
    async def test_fetch_all_sources_429_raises_rate_limited_error(self, provider):
        """The reported MU scenario: all three Adanos endpoints return HTTP 429.
        The provider must raise the TYPED RateLimitedProviderError so the
        DataLayer trips the circuit breaker (BUG-045) and serves last-known-good
        stale sentiment instead of caching an empty 0/3 snapshot for the TTL."""
        request = httpx.Request(
            "GET", "https://api.adanos.org/reddit/stocks/v1/compare?tickers=MU&days=7"
        )
        response = httpx.Response(429, request=request)

        async def mock_get(path, params=None):
            raise httpx.HTTPStatusError(
                "Client error '429 Too Many Requests' for url "
                "'https://api.adanos.org/reddit/stocks/v1/compare?tickers=MU&days=7'",
                request=request,
                response=response,
            )

        with patch.object(provider, "_get", side_effect=mock_get):
            with pytest.raises(RateLimitedProviderError) as exc_info:
                await provider.fetch("MU", "sentiment")
        assert is_rate_limit_error(exc_info.value)
        message = str(exc_info.value)
        assert "HTTP 429" in message or "rate limited" in message
        assert "api.adanos.org" not in message
        assert "for url" not in message

    @pytest.mark.asyncio
    async def test_fetch_partial_errors_with_one_response_does_not_raise(self, provider):
        """Discriminator is "did EVERY attempt raise", NOT "is coverage 0/3". When
        at least one platform RESPONDS (here an untracked-ticker HTTP 200 with zero
        buzz) the snapshot is a legitimate, cacheable answer even though two other
        platforms 429'd — we genuinely reached Adanos. It must NOT raise."""
        request = httpx.Request("GET", "https://adanos.example/api")
        response = httpx.Response(429, request=request)

        async def mock_get(path, params=None):
            if "reddit" in path:
                return _mock_response(
                    {"stocks": [{"ticker": "ZZZZ", "buzz_score": 0, "mentions": 0}]}
                )
            raise httpx.HTTPStatusError("429 Too Many Requests", request=request, response=response)

        with patch.object(provider, "_get", side_effect=mock_get):
            result = await provider.fetch("ZZZZ", "sentiment")

        assert result.data["coverage"] == "0/3"
        assert result.data["coverage_ratio"] == 0.0
        assert result.data["average_buzz"] is None
        assert result.data["bullish_avg"] is None
        assert len(result.warnings) == 2  # the two 429'd platforms

    @pytest.mark.asyncio
    async def test_partial_failure_warning_is_clean_no_raw_url(self, provider):
        """The per-platform degradation note is cached and later re-surfaced to the
        analyst card on a stale fallback — it must carry NO raw upstream URL or
        httpx repr (frontend-contract red line ⑥), only a clean platform + reason.
        The 429 here carries a production-style message WITH a URL so this fails on
        the old `f"{label}: {exc}"` form."""
        request = httpx.Request(
            "GET", "https://api.adanos.org/x/stocks/v1/compare?tickers=ZZZZ&days=7"
        )
        response = httpx.Response(429, request=request)

        async def mock_get(path, params=None):
            if "reddit" in path:
                return _mock_response(
                    {"stocks": [{"ticker": "ZZZZ", "buzz_score": 0, "mentions": 0}]}
                )
            raise httpx.HTTPStatusError(
                "Client error '429 Too Many Requests' for url "
                "'https://api.adanos.org/x/stocks/v1/compare?tickers=ZZZZ&days=7'",
                request=request,
                response=response,
            )

        with patch.object(provider, "_get", side_effect=mock_get):
            result = await provider.fetch("ZZZZ", "sentiment")

        blob = " ".join(result.warnings)
        assert "http" not in blob
        assert "api.adanos.org" not in blob
        assert "for url" not in blob
        assert all("rate limited" in w for w in result.warnings)

    @pytest.mark.asyncio
    async def test_unsupported_type_raises(self, provider):
        with pytest.raises(ProviderError, match="not supported"):
            await provider.fetch("AAPL", "financials")

    @pytest.mark.asyncio
    async def test_platform_429_raises_typed_rate_limited_error(self, provider):
        """An Adanos 429 at the per-platform wrap point must surface as the
        TYPED RateLimitedProviderError (fetch() currently folds it into a
        warning, but the wrap point owns the structural classification)."""
        request = httpx.Request(
            "GET", "https://api.adanos.org/reddit/stocks/v1/compare?tickers=AAPL&days=7"
        )
        response = httpx.Response(429, request=request)
        with patch.object(
            provider,
            "_get",
            AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "Client error '429 Too Many Requests' for url "
                    "'https://api.adanos.org/reddit/stocks/v1/compare?tickers=AAPL&days=7'",
                    request=request,
                    response=response,
                )
            ),
        ):
            with pytest.raises(RateLimitedProviderError) as exc_info:
                await provider._fetch_one_platform(_PLATFORM_SPECS[0], "AAPL", 7)
        assert is_rate_limit_error(exc_info.value)
        message = str(exc_info.value)
        assert "HTTP 429" in message
        assert "api.adanos.org" not in message
        assert "for url" not in message

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
    """_compute_alignment returns stable enum tokens (cross-language contract:
    provider ⊆ route Literal ⊆ frontend ALIGNMENT_KEYS ⊆ i18n keys). The old
    free-English phrases ('Wide divergence' …) never matched the frontend
    whitelist, so the alignment badge was dead UI. Direction (bullish/bearish/
    neutral) is NOT in the token — the bull/bear split bar next to the badge
    already shows it; the badge answers only "do the sources agree?"."""

    def test_agreeing_sources_are_aligned_regardless_of_direction(self):
        assert _compute_alignment([60, 62, 58]) == "aligned"  # bullish consensus
        assert _compute_alignment([40, 42, 38]) == "aligned"  # bearish consensus
        assert _compute_alignment([48, 50, 52]) == "aligned"  # neutral consensus

    def test_partial_divergence(self):
        assert _compute_alignment([40, 55]) == "partial_divergence"

    def test_wide_divergence_is_split(self):
        assert _compute_alignment([30, 70]) == "split"

    def test_single_source(self):
        assert _compute_alignment([60]) == "single_source"

    def test_no_coverage(self):
        assert _compute_alignment([]) == "no_data"

    def test_every_produced_token_is_in_the_shared_literal(self):
        """Provider output ⊆ AlignmentToken — the route reuses this Literal, so
        a new phrase that isn't a known token fails here, not in production."""
        from typing import get_args

        from finrobot.engine.data.providers.adanos_provider import AlignmentToken

        tokens = set(get_args(AlignmentToken))
        produced = {
            _compute_alignment(vals)
            for vals in ([], [60.0], [60.0, 62.0], [40.0, 55.0], [30.0, 70.0], [40.0, 42.0, 38.0])
        }
        assert produced <= tokens


class TestAdanosNoDataNotFabricated:
    """A zero-activity placeholder row must NOT be counted as coverage and a
    missing bullish_pct must NOT be fabricated as 0% bullish.

    The live bug (probe 2026-06-09): GET /api/sentiment/ZZZZ returned
    available=true, coverage 3/3, bearish_pct 100, "Bearish alignment" — three
    sources with activity_value=0. Root: ``has_data`` accepted
    ``bullish_pct is not None``, and ``_safe_float`` coerced a missing bullish_pct
    to 0.0 (never None), so a no-data row read as a confident 0%-bullish source.
    Violates "可溯源确定性底座" — a confident bearish signal conjured from nothing.
    """

    def test_zero_activity_placeholder_row_is_not_data(self):
        spec = _PLATFORM_SPECS[0]
        row = {"ticker": "ZZZZ", "buzz_score": 0, spec["activity_field"]: 0, "bullish_pct": 0}
        out = _normalize_source(spec, row)
        assert out["has_data"] is False

    def test_zero_activity_with_missing_bullish_is_not_data(self):
        spec = _PLATFORM_SPECS[0]
        row = {"ticker": "ZZZZ", "buzz_score": 0, spec["activity_field"]: 0}  # no bullish_pct
        out = _normalize_source(spec, row)
        assert out["has_data"] is False
        assert out["bullish_pct"] is None

    def test_real_activity_with_missing_bullish_preserves_none(self):
        """Real mentions but the provider omitted bullish_pct → the source has data
        (activity), but bullish_pct stays None — never a fabricated 0% bullish."""
        spec = _PLATFORM_SPECS[0]
        row = {"ticker": "AAPL", "buzz_score": 0, spec["activity_field"]: 500}  # no bullish_pct
        out = _normalize_source(spec, row)
        assert out["has_data"] is True
        assert out["bullish_pct"] is None

    def test_real_data_unchanged(self):
        spec = _PLATFORM_SPECS[0]
        row = {
            "ticker": "AAPL",
            "buzz_score": 82.0,
            spec["activity_field"]: 1200,
            "bullish_pct": 58.0,
        }
        out = _normalize_source(spec, row)
        assert out["has_data"] is True
        assert out["bullish_pct"] == 58.0

    @pytest.mark.asyncio
    async def test_fetch_untracked_ticker_zero_activity_is_no_coverage(self, provider):
        """End-to-end reproduction of the ZZZZ bug: every platform returns a
        zero-activity placeholder row → coverage 0/3, no fabricated bearish signal."""

        def empty_row_resp() -> dict:
            return {
                "stocks": [
                    {
                        "ticker": "ZZZZ",
                        "buzz_score": 0,
                        "mentions": 0,
                        "trade_count": 0,
                        "bullish_pct": 0,
                    }
                ]
            }

        responses = [_mock_response(empty_row_resp()) for _ in range(3)]
        with patch.object(provider, "_get", AsyncMock(side_effect=responses)):
            result = await provider.fetch("ZZZZ", "sentiment")

        assert result.data["coverage"] == "0/3"
        assert result.data["coverage_ratio"] == 0.0
        assert result.data["bullish_avg"] is None
        assert result.data["source_alignment"] == "no_data"


class TestAdanosRateLimiter:
    @pytest.mark.asyncio
    async def test_rate_limiter_sleeps_on_rapid_calls(self, provider, monkeypatch):
        import asyncio
        import time

        from finrobot.engine.data.providers.adanos_provider import _MIN_INTERVAL

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
