"""Tests for GET /api/data/{ticker}/price and /performance.

Verifies the routes correctly thread through the period parameter and call
the underlying service. /price now sits behind ``cached_fetch`` so the
mock targets the service function (not the cache wrapper) — first call
exercises the fetcher path; cache state is isolated per-test via the
DataCache fixture in conftest.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_price_endpoint_accepts_period_param(app_with_deps):
    """GET /api/data/{ticker}/price?period=3mo forwards period to the fetcher."""
    app = app_with_deps

    mock_payload = {
        "current_price": 190.0,
        "history": [],
        "fetched_at": "2026-05-27T12:00:00+00:00",
        "data_source": "yfinance",
        "warnings": [],
    }
    with patch(
        "finrobot.routes.data.fetch_price_history",
        new=AsyncMock(return_value=mock_payload),
    ) as mock_fetch:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/data/AAPL/price?period=3mo")

    assert resp.status_code == 200
    mock_fetch.assert_called_once_with("AAPL", "3mo")


@pytest.mark.asyncio
async def test_price_endpoint_uses_cache_on_second_call(app_with_deps):
    """Second call within TTL must hit the cache — fetcher called only once."""
    app = app_with_deps

    mock_payload = {
        "current_price": 190.0,
        "history": [],
        "fetched_at": "2026-05-27T12:00:00+00:00",
        "data_source": "yfinance",
        "warnings": [],
    }
    with patch(
        "finrobot.routes.data.fetch_price_history",
        new=AsyncMock(return_value=mock_payload),
    ) as mock_fetch:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r1 = await client.get("/api/data/AAPL/price?period=1y")
            r2 = await client.get("/api/data/AAPL/price?period=1y")

    assert r1.status_code == 200
    assert r2.status_code == 200
    # Cache hit on second call — fetcher invoked exactly once
    assert mock_fetch.call_count == 1


@pytest.mark.asyncio
async def test_price_endpoint_different_periods_dont_share_cache(app_with_deps):
    """1y and 5d are different payloads — cache key must include period."""
    app = app_with_deps

    with patch(
        "finrobot.routes.data.fetch_price_history",
        new=AsyncMock(return_value={"current_price": 1.0, "history": [], "fetched_at": "2026-05-27T12:00:00+00:00", "data_source": "yfinance", "warnings": []}),
    ) as mock_fetch:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/api/data/AAPL/price?period=1y")
            await client.get("/api/data/AAPL/price?period=5d")

    # Two distinct cache slots → both calls hit the fetcher
    assert mock_fetch.call_count == 2


@pytest.mark.asyncio
async def test_price_endpoint_invalid_ticker_returns_422(app_with_deps):
    """fetch_price_history raises ValueError → /price returns 422."""
    app = app_with_deps

    with patch(
        "finrobot.routes.data.fetch_price_history",
        new=AsyncMock(side_effect=ValueError("未知 ticker 'INVALID'")),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/data/INVALID/price?period=1y")

    assert resp.status_code == 422
    assert "INVALID" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_price_endpoint_provider_error_returns_502(app_with_deps):
    """fetch_price_history raises ProviderError → /price returns 502 (not default 500)."""
    from finrobot.engine.data.interface import ProviderError

    app = app_with_deps

    with patch(
        "finrobot.routes.data.fetch_price_history",
        new=AsyncMock(side_effect=ProviderError("yfinance service down: 429")),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/data/AAPL/price?period=1y")

    assert resp.status_code == 502
    assert "数据源" in resp.json()["detail"] or "暂不可用" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_price_endpoint_returns_fetched_at(app_with_deps):
    """Route forwards fetched_at field from service."""
    app = app_with_deps

    mock_payload = {
        "current_price": 190.0,
        "history": [],
        "fetched_at": "2026-05-27T12:00:00+00:00",
        "data_source": "yfinance",
        "warnings": [],
    }
    with patch(
        "finrobot.routes.data.fetch_price_history",
        new=AsyncMock(return_value=mock_payload),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/data/AAPL/price?period=1y")

    assert resp.status_code == 200
    assert resp.json()["fetched_at"] == "2026-05-27T12:00:00+00:00"
