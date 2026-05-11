import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_price_endpoint_accepts_period_param():
    """GET /api/data/{ticker}/price?period=3mo should work."""
    from finagent.server import app

    with patch("finagent.routes.data.fetch_price_with_period") as mock_fetch:
        mock_fetch.return_value = {"current_price": 190.0, "history": [], "data_source": "yfinance", "warnings": []}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/data/AAPL/price?period=3mo")
    assert resp.status_code == 200
    mock_fetch.assert_called_once_with("AAPL", "3mo")


@pytest.mark.asyncio
async def test_performance_endpoint_returns_series():
    """GET /api/data/performance returns normalized multi-ticker series."""
    from finagent.server import app

    mock_result = {
        "series": [
            {"ticker": "AAPL", "label": "AAPL", "data": [{"date": "2025-05-01", "value": 100.0}]},
            {"ticker": "SPY", "label": "S&P 500", "data": [{"date": "2025-05-01", "value": 100.0}]},
        ]
    }
    with patch("finagent.routes.data.fetch_performance_data") as mock_fn:
        mock_fn.return_value = mock_result
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/data/performance?tickers=AAPL&benchmark=SPY&period=1y")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["series"]) == 2
    assert data["series"][0]["ticker"] == "AAPL"
    assert data["series"][1]["label"] == "S&P 500"
