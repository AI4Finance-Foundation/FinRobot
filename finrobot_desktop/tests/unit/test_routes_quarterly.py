import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch


@pytest.mark.asyncio
async def test_quarterly_endpoint_returns_data():
    """GET /api/data/{ticker}/quarterly returns quarterly financial data."""
    from finagent.server import app

    mock_quarters = {
        "ticker": "AAPL",
        "quarters": [
            {
                "quarter": "2024-Q4",
                "revenue": 94_836_000_000,
                "operating_income": 29_200_000_000,
                "net_income": 23_640_000_000,
                "operating_cash_flow": 28_900_000_000,
            },
            {
                "quarter": "2024-Q3",
                "revenue": 85_777_000_000,
                "operating_income": 25_300_000_000,
                "net_income": 21_450_000_000,
                "operating_cash_flow": 26_800_000_000,
            },
        ],
    }

    with patch("finagent.routes.data.fetch_quarterly_data") as mock_fn:
        mock_fn.return_value = mock_quarters
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/data/AAPL/quarterly")

    assert resp.status_code == 200
    data = resp.json()
    assert data["ticker"] == "AAPL"
    assert len(data["quarters"]) == 2
    assert data["quarters"][0]["quarter"] == "2024-Q4"
    assert "operating_income" in data["quarters"][0]
    # EBITDA is intentionally NOT included (not reliable from yfinance quarterly)
    assert "ebitda" not in data["quarters"][0]
