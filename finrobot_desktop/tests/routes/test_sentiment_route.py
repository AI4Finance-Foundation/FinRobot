"""End-to-end tests for GET /api/sentiment/{ticker} (v5 PR4b)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, ConfigDict

from finrobot.engine.data.interface import DataProvider, DataResult, ProviderError
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


class _StubDataLayer:
    def __init__(self, providers: list[DataProvider]) -> None:
        self._providers = providers

    async def fetch(self, data_type: DataType | str, ticker: str, **kwargs: object) -> DataResult:
        for p in self._providers:
            if DataType(data_type) in p.capabilities():
                return await p.fetch(ticker, data_type, **kwargs)
        raise ProviderError(f"no provider for {data_type}")


class _StubDeps(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    data_layer: _StubDataLayer


def _app(providers: list[DataProvider]) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.deps = _StubDeps(data_layer=_StubDataLayer(providers))
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
async def test_sentiment_returns_unavailable_when_provider_missing() -> None:
    # No SENTIMENT provider registered → endpoint must NOT 500.
    app = _app([])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/sentiment/NVDA")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert any("adanos provider 未配置" in w for w in body["warnings"])


@pytest.mark.asyncio
async def test_sentiment_returns_unavailable_when_provider_raises() -> None:
    app = _app([_AdanosLike(raise_for="rate limited by adanos")])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/sentiment/NVDA")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert any("调用失败" in w for w in body["warnings"])


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
