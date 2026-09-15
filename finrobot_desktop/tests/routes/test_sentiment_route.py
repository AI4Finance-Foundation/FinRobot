"""End-to-end tests for GET /api/sentiment/{ticker} (v5 PR4b)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, ConfigDict

from finrobot.engine.data.interface import DataProvider, DataResult, ProviderError
from finrobot.engine.data.provider_health import ProviderState
from finrobot.engine.data.types import DataType
from finrobot.routes.sentiment import router

UTC = timezone.utc
NOW = datetime(2026, 5, 21, tzinfo=UTC)


class _AdanosLike(DataProvider):
    """Pretends to be the adanos provider for the sentiment endpoint test."""

    def __init__(
        self, *, raise_for: str | None = None, data: dict[str, object] | None = None
    ) -> None:
        self._raise = raise_for
        self._data = data or {}

    @property
    def name(self) -> str:
        return "adanos-stub"

    def capabilities(self) -> list[str | DataType]:
        return [DataType.SENTIMENT]

    async def fetch(self, ticker: str, data_type: str | DataType, **kwargs: object) -> DataResult:
        if self._raise:
            raise ProviderError(self._raise)
        data = {
            "ticker": ticker,
            "period_days": kwargs.get("days_back", 7),
            "coverage": "2/3",
            "coverage_ratio": 0.67,
            "average_buzz": 142.5,
            "bullish_avg": 67.5,
            "source_alignment": "aligned",
            "sources": [
                {
                    "label": "Reddit",
                    "bullish_pct": 70.0,
                    "activity_label": "Mentions",
                    "activity_value": 1240,
                    "has_data": True,
                },
                {
                    "label": "X.com",
                    "bullish_pct": 65.0,
                    "activity_label": "Mentions",
                    "activity_value": 8400,
                    "has_data": True,
                },
                {
                    "label": "Polymarket",
                    "bullish_pct": None,
                    "activity_label": "Trades",
                    "activity_value": 0,
                    "has_data": False,
                },
            ],
        }
        data.update(self._data)
        return DataResult(
            data=data,
            provider=self.name,
            ticker=ticker,
            data_type=DataType.SENTIMENT,
            timestamp=NOW,
        )


class _RawResultProvider(DataProvider):
    """Returns a caller-supplied DataResult verbatim — used to simulate what the
    real DataLayer hands the route after it has caught a provider failure: either
    a no-data error result (provider='none') or a stale-cache fallback."""

    def __init__(self, result: DataResult) -> None:
        self._result = result

    @property
    def name(self) -> str:
        return "raw-stub"

    def capabilities(self) -> list[str | DataType]:
        return [DataType.SENTIMENT]

    async def fetch(self, ticker: str, data_type: str | DataType, **kwargs: object) -> DataResult:
        return self._result


class _StubDataLayer:
    def __init__(self, providers: list[DataProvider], *, rate_limited: bool = False) -> None:
        self._providers = providers
        self._rate_limited = rate_limited

    async def fetch(self, data_type: DataType | str, ticker: str, **kwargs: object) -> DataResult:
        for p in self._providers:
            if DataType(data_type) in p.capabilities():
                return await p.fetch(ticker, data_type, **kwargs)
        raise ProviderError(f"no provider for {data_type}")

    def provider_status(self) -> list[tuple[str, bool, ProviderState]]:
        # Mirrors DataLayer.provider_status(): the route reads each sentiment
        # provider's ``last_rate_limited`` off the breaker to tell a 429 throttle
        # (transient → auto-retry) apart from a generic provider failure.
        return [
            (p.name, True, ProviderState(last_rate_limited=self._rate_limited))
            for p in self._providers
        ]


class _StubDeps(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    data_layer: _StubDataLayer


def _app(providers: list[DataProvider], *, rate_limited: bool = False) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.deps = _StubDeps(data_layer=_StubDataLayer(providers, rate_limited=rate_limited))
    return app


@pytest.mark.asyncio
async def test_sentiment_returns_normalised_snapshot() -> None:
    app = _app([_AdanosLike()])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/sentiment/NVDA?days=7")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ticker"] == "NVDA"
    assert body["available"] is True
    assert body["reason"] is None  # available → no failure reason
    assert body["bullish_pct"] == 67.5
    assert body["bearish_pct"] == pytest.approx(32.5)
    assert body["coverage"] == "2/3"
    assert len(body["sources"]) == 3
    assert {s["platform"] for s in body["sources"]} == {"Reddit", "X.com", "Polymarket"}


@pytest.mark.asyncio
async def test_sentiment_drops_nonfinite_snapshot_numbers() -> None:
    app = _app(
        [
            _AdanosLike(
                data={
                    "bullish_avg": float("nan"),
                    "average_buzz": float("inf"),
                    "sources": [
                        {
                            "label": "Reddit",
                            "bullish_pct": float("-inf"),
                            "activity_label": "Mentions",
                            "activity_value": 1240,
                            "has_data": True,
                        }
                    ],
                }
            )
        ]
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/sentiment/NVDA?days=7")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bullish_pct"] is None
    assert body["bearish_pct"] is None
    assert body["average_buzz"] is None
    assert body["sources"][0]["bullish_pct"] is None


@pytest.mark.asyncio
async def test_sentiment_drops_invalid_activity_values() -> None:
    app = _app(
        [
            _AdanosLike(
                data={
                    "sources": [
                        {
                            "label": "Reddit",
                            "bullish_pct": 70.0,
                            "activity_label": "Mentions",
                            "activity_value": float("nan"),
                            "has_data": True,
                        },
                        {
                            "label": "X.com",
                            "bullish_pct": 65.0,
                            "activity_label": "Mentions",
                            "activity_value": -1,
                            "has_data": True,
                        },
                    ],
                }
            )
        ]
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/sentiment/NVDA?days=7")

    assert r.status_code == 200, r.text
    body = r.json()
    assert [source["activity_value"] for source in body["sources"]] == [None, None]


@pytest.mark.asyncio
async def test_sentiment_returns_unavailable_when_provider_missing() -> None:
    # No SENTIMENT provider registered → endpoint must NOT 500.
    app = _app([])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/sentiment/NVDA")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    # 'unconfigured' is what tells the UI to show the "add API key" CTA — distinct
    # from a transient failure, which must NOT send a configured user to settings.
    assert body["reason"] == "unconfigured"
    assert any("adanos provider 未配置" in w for w in body["warnings"])


@pytest.mark.asyncio
async def test_sentiment_returns_unavailable_when_provider_raises() -> None:
    # A GENERIC provider failure (not a throttle) → 'provider_error' so the UI
    # shows a retry, not the misleading "not configured" CTA (the reported bug).
    app = _app([_AdanosLike(raise_for="adanos upstream connection reset")])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/sentiment/NVDA")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["reason"] == "provider_error"
    assert any("调用失败" in w for w in body["warnings"])


@pytest.mark.asyncio
async def test_sentiment_provider_raises_rate_limit_maps_to_rate_limited() -> None:
    # A provider error that IS a 429 throttle must classify as 'rate_limited' —
    # distinct from a generic outage so the UI can say "rate-limited, retrying"
    # instead of fabricating "Upstream returned 5xx".
    app = _app([_AdanosLike(raise_for="Adanos rate limited (HTTP 429)")])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/sentiment/MU")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["reason"] == "rate_limited"


@pytest.mark.asyncio
async def test_sentiment_no_data_with_rate_limited_breaker_maps_to_rate_limited() -> None:
    # The common live path: all platforms 429 with no cache → DataLayer returns a
    # no-data sentinel (it does NOT re-raise) and the breaker recorded the
    # rate-limit. The route reads ``last_rate_limited`` off provider_status() and
    # classifies 'rate_limited' — the accurate signal behind the "5xx" copy bug.
    err = DataResult(
        data={"error": "Data unavailable (MU / sentiment): all data sources failed"},
        provider="none",
        ticker="MU",
        data_type=DataType.SENTIMENT,
        timestamp=NOW,
        warnings=["Adanos rate limited on all platforms"],
    )
    app = _app([_RawResultProvider(err)], rate_limited=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/sentiment/MU")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["reason"] == "rate_limited"


def test_reason_literal_is_exhaustive() -> None:
    # T8 #1/#2: the frontend whitelist (SentimentCard reason switch + v5.ts union)
    # must mirror this set exactly — a new backend reason with no frontend case is
    # a silently dead UI state. Pin the contract here so adding/removing a reason
    # fails this test until both sides move together.
    from typing import get_args, get_type_hints

    from finrobot.routes.sentiment import SentimentSnapshot

    reason_field = get_type_hints(SentimentSnapshot)["reason"]
    literal = get_args(reason_field)[0]  # Optional[Literal[...]] → Literal[...]
    assert set(get_args(literal)) == {"unconfigured", "provider_error", "rate_limited"}


@pytest.mark.asyncio
async def test_sentiment_no_data_error_result_maps_to_provider_error() -> None:
    # When every Adanos platform 429s and there's no cache, the real DataLayer
    # returns a no-data DataResult (provider='none', data={'error': ...}) rather
    # than raising. The route must classify this as a transient failure
    # (reason='provider_error' → retry affordance), NOT render available=True
    # with a null coverage, and NOT send a configured user to the settings CTA.
    err = DataResult(
        data={"error": "Data unavailable (MU / sentiment): all data sources failed"},
        provider="none",
        ticker="MU",
        data_type=DataType.SENTIMENT,
        timestamp=NOW,
        warnings=["Adanos rate limited on all platforms"],
    )
    app = _app([_RawResultProvider(err)])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/sentiment/MU")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["reason"] == "provider_error"
    assert body["coverage"] is None
    assert body["warnings"]  # carries the underlying failure text


@pytest.mark.asyncio
async def test_sentiment_stale_cache_fallback_renders_available_with_warning() -> None:
    # When Adanos 429s but the DataLayer has last-known-good sentiment, it serves
    # the stale snapshot (real numbers) plus a 'retry later' warning. The route
    # must render it as available=True with those numbers — the graceful degrade,
    # not a blanked panel.
    stale = DataResult(
        data={
            "ticker": "MU",
            "coverage": "3/3",
            "bullish_avg": 61.0,
            "average_buzz": 88.0,
            "source_alignment": "aligned",
            "sources": [],
        },
        provider="adanos",
        ticker="MU",
        data_type=DataType.SENTIMENT,
        timestamp=NOW,
        warnings=["All data sources failed; showing cached data from 1h ago. Retry later."],
        from_stale_cache=True,
    )
    app = _app([_RawResultProvider(stale)])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/sentiment/MU")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["bullish_pct"] == 61.0
    assert body["coverage"] == "3/3"
    assert any("Retry later" in w for w in body["warnings"])


@pytest.mark.asyncio
async def test_sentiment_stale_fallback_no_usable_signal_degrades_to_soft_state() -> None:
    # The reported P0: every platform 429'd and the DataLayer grafted a 0/3 stale
    # snapshot whose cached warnings still carried raw upstream URLs. Such a graft
    # has NO usable signal — it must NOT render available=True with raw provider
    # diagnostics trailing the card. Route it to the soft rate-limited state (clean
    # affordance) and let the breaker classify the reason.
    stale = DataResult(
        data={
            "ticker": "AAPL",
            "coverage": "0/3",
            "bullish_avg": None,
            "average_buzz": None,
            "source_alignment": "no_data",
            "sources": [
                {
                    "label": "Reddit",
                    "has_data": False,
                    "bullish_pct": None,
                    "activity_label": "Mentions",
                    "activity_value": 0,
                },
            ],
        },
        provider="adanos",
        ticker="AAPL",
        data_type=DataType.SENTIMENT,
        timestamp=NOW,
        warnings=[
            "All data sources failed; showing cached data from 229h ago (AAPL / sentiment).",
            # Exact poisoned-cache shape httpx produces: URL tail + a continuation
            # line. Both must be scrubbed before reaching the contract.
            "Reddit: Adanos rate limited (HTTP 429) for Reddit: Client error '429 Too Many "
            "Requests' for url 'https://api.adanos.org/reddit/stocks/v1/compare?tickers=AAPL'"
            "\nFor more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/"
            "Status/429",
        ],
        from_stale_cache=True,
    )
    app = _app([_RawResultProvider(stale)], rate_limited=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/sentiment/AAPL")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["reason"] == "rate_limited"  # breaker recorded the 429
    # The leak: no internal endpoint / URL / httpx boilerplate may reach the contract.
    blob = " ".join(body["warnings"])
    assert "http" not in blob
    assert "api.adanos.org" not in blob
    assert "for url" not in blob
    assert "For more information" not in blob


@pytest.mark.asyncio
async def test_sentiment_available_warnings_strip_internal_urls() -> None:
    # A partial stale graft still has usable numbers → stays available, but any raw
    # upstream URL in its cached warnings is stripped at the contract boundary
    # (frontend-contract red line ⑥) so the analyst card never shows an internal
    # endpoint — defends cache entries poisoned before the provider was cleaned.
    stale = DataResult(
        data={
            "ticker": "MU",
            "coverage": "2/3",
            "bullish_avg": 61.0,
            "average_buzz": 88.0,
            "source_alignment": "aligned",
            "sources": [],
        },
        provider="adanos",
        ticker="MU",
        data_type=DataType.SENTIMENT,
        timestamp=NOW,
        warnings=[
            "Polymarket rate limited",
            "Adanos error for url 'https://api.adanos.org/x/stocks/v1/compare?tickers=MU'",
        ],
        from_stale_cache=True,
    )
    app = _app([_RawResultProvider(stale)])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/sentiment/MU")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True  # usable signal present → graceful degrade
    blob = " ".join(body["warnings"])
    assert "http" not in blob
    assert "api.adanos.org" not in blob
    assert "for url" not in blob
    assert any("Polymarket" in w for w in body["warnings"])  # clean lead text kept


@pytest.mark.asyncio
async def test_sentiment_fresh_empty_stays_available() -> None:
    # A genuine "no buzz" answer for an untracked ticker (HTTP 200, zero activity,
    # NOT a failure) is a legitimate available 0/3 state — it must NOT be demoted to
    # a soft failure. Distinguished from a stale graft by from_stale_cache=False.
    fresh = DataResult(
        data={
            "ticker": "ZZZZ",
            "coverage": "0/3",
            "bullish_avg": None,
            "average_buzz": None,
            "source_alignment": "no_data",
            "sources": [
                {
                    "label": "Reddit",
                    "has_data": False,
                    "bullish_pct": None,
                    "activity_label": "Mentions",
                    "activity_value": 0,
                },
            ],
        },
        provider="adanos",
        ticker="ZZZZ",
        data_type=DataType.SENTIMENT,
        timestamp=NOW,
    )
    app = _app([_RawResultProvider(fresh)])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/sentiment/ZZZZ")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["reason"] is None
    assert body["coverage"] == "0/3"


@pytest.mark.asyncio
async def test_sentiment_503_when_data_layer_absent() -> None:
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/sentiment/NVDA")
    assert r.status_code == 200  # graceful degradation, not 503
    assert r.json()["available"] is False


@pytest.mark.asyncio
async def test_sentiment_normalises_ticker_uppercase_and_strips_dollar() -> None:
    app = _app([_AdanosLike()])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/sentiment/$nvda")
    assert r.status_code == 200
    assert r.json()["ticker"] == "NVDA"


@pytest.mark.asyncio
async def test_sentiment_rejects_empty_dollar_ticker() -> None:
    app = _app([_AdanosLike()])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/sentiment/$")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_sentiment_rejects_invalid_ticker_characters() -> None:
    app = _app([_AdanosLike()])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/sentiment/苹果")
    assert r.status_code == 422
