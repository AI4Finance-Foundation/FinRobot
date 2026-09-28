"""Tests for GET /api/data/{ticker}/historical endpoint.

Verifies:
- 200 response with correct HistoricalMetrics JSON structure
- fetch_historical_metrics is called exactly once with the uppercased ticker
- Key fields (ticker, years, operating_cash_flow) are present in response
- ValueError → 422 (invalid ticker / no data)
- ProviderError → 502 (upstream service down), not default 500
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock

from finrobot.engine.models.financial import HistoricalMetrics


@pytest.mark.asyncio
async def test_historical_endpoint_returns_metrics(app_with_deps):
    """GET /api/data/{ticker}/historical returns HistoricalMetrics."""
    app = app_with_deps

    mock_metrics = HistoricalMetrics(
        years=[2022, 2023, 2024],
        revenue=[100e9, 110e9, 120e9],
        revenue_growth_yoy=[None, 0.10, 0.09],
        cogs=[60e9, 65e9, 70e9],
        gross_profit=[40e9, 45e9, 50e9],
        gross_margin=[0.40, 0.409, 0.417],
        sga=[15e9, 16e9, 17e9],
        sga_ratio=[0.15, 0.145, 0.142],
        ebitda=[30e9, 33e9, 36e9],
        ebitda_margin=[0.30, 0.30, 0.30],
        operating_income=[25e9, 28e9, 31e9],
        operating_margin=[0.25, 0.255, 0.258],
        net_income=[20e9, 22e9, 24e9],
        eps=[6.5, 7.2, 7.9],
        pe_ratio=[25.0, 27.0, 24.0],
        operating_cash_flow=[28e9, 30e9, 33e9],
        investing_cash_flow=[-10e9, -12e9, -11e9],
        financing_cash_flow=[-15e9, -14e9, -16e9],
        cagr_revenue=0.095,
        ticker="AAPL",
        price_data_available=True,
    )

    with patch(
        "finrobot.routes.data.fetch_historical_metrics",
        new=AsyncMock(return_value=mock_metrics),
    ) as mock_fn:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/data/AAPL/historical")

    assert resp.status_code == 200
    data = resp.json()
    assert data["ticker"] == "AAPL"
    assert len(data["years"]) == 3
    assert "operating_cash_flow" in data
    # Now invoked with the injected DataLayer + uppercased ticker (门一收口).
    mock_fn.assert_called_once_with(app.state.deps.data_layer, "AAPL")


@pytest.mark.asyncio
async def test_historical_endpoint_invalid_ticker_returns_422(app_with_deps):
    """fetch_historical_metrics raises ValueError → /historical returns 422."""
    app = app_with_deps

    with patch(
        "finrobot.routes.data.fetch_historical_metrics",
        new=AsyncMock(side_effect=ValueError("unknown ticker 'INVALID'")),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/data/INVALID/historical")

    assert resp.status_code == 422
    assert "INVALID" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_historical_endpoint_provider_error_returns_502(app_with_deps):
    """fetch_historical_metrics raises ProviderError → /historical returns 502 (not 500)."""
    from finrobot.engine.data.interface import ProviderError

    app = app_with_deps

    with patch(
        "finrobot.routes.data.fetch_historical_metrics",
        new=AsyncMock(side_effect=ProviderError("yfinance service down: 429")),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/data/AAPL/historical")

    assert resp.status_code == 502
    assert (
        "Data source" in resp.json()["detail"] or "temporarily unavailable" in resp.json()["detail"]
    )
