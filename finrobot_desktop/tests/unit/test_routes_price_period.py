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
        "data_source": "yfinance",
        "warnings": [],
    }
    with patch(
        "finagent.routes.data.fetch_price_history",
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
        "data_source": "yfinance",
        "warnings": [],
    }
    with patch(
        "finagent.routes.data.fetch_price_history",
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
        "finagent.routes.data.fetch_price_history",
        new=AsyncMock(return_value={"current_price": 1.0, "history": [], "data_source": "yfinance", "warnings": []}),
    ) as mock_fetch:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/api/data/AAPL/price?period=1y")
            await client.get("/api/data/AAPL/price?period=5d")

    # Two distinct cache slots → both calls hit the fetcher
    assert mock_fetch.call_count == 2


@pytest.mark.asyncio
async def test_performance_endpoint_returns_series(app_with_deps):
    """GET /api/data/performance returns normalized multi-ticker series."""
    app = app_with_deps

    mock_result = {
        "series": [
            {"ticker": "AAPL", "label": "AAPL", "data": [{"date": "2025-05-01", "value": 100.0}]},
            {"ticker": "SPY", "label": "S&P 500", "data": [{"date": "2025-05-01", "value": 100.0}]},
        ]
    }
    with patch(
        "finagent.routes.data.fetch_performance_data",
        new=AsyncMock(return_value=mock_result),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/data/performance?tickers=AAPL&benchmark=SPY&period=1y")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["series"]) == 2
    assert data["series"][0]["ticker"] == "AAPL"
    assert data["series"][1]["label"] == "S&P 500"
