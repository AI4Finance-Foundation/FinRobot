"""Route tests for /api/market endpoints.

Coverage:
- GET /api/market/indices — returns list of MarketIndex dicts
- GET /api/market/sectors — returns list of sector ETF dicts
- GET /api/market/earnings-calendar — returns list (empty when no FMP key)

Mock discipline: unit-level route tests mock the compute layer functions
(fetch_market_indices, fetch_sector_etfs, fetch_earnings_calendar) at the
routes module import level, so no real network calls are made.
These are NOT integration tests — real yfinance calls are tested separately
under @pytest.mark.integration.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from finagent.routes.market import router as market_router
from finagent.engine.compute.market import EarningsEvent, MarketIndex


# ---------------------------------------------------------------------------
# Shared sample data
# ---------------------------------------------------------------------------

_SAMPLE_INDICES = [
    MarketIndex(symbol="^GSPC", name="S&P 500", price=5230.0, change=12.5, change_pct=0.24),
    MarketIndex(symbol="^IXIC", name="NASDAQ", price=16400.0, change=-20.0, change_pct=-0.12),
]

_SAMPLE_SECTORS = [
    MarketIndex(symbol="XLK", name="Tech", price=220.0, change=1.5, change_pct=0.68),
    MarketIndex(symbol="XLF", name="Financials", price=42.0, change=-0.3, change_pct=-0.71),
]

_SAMPLE_EARNINGS = [
    EarningsEvent(
        date="2026-05-16",
        ticker="AAPL",
        company_name="Apple Inc.",
        time="BMO",
        eps_estimate=1.45,
    ),
]


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def app() -> FastAPI:
    test_app = FastAPI()

    # Minimal deps stub for the earnings-calendar request.app.state.deps path
    class _FakeDeps:
        class settings:
            fmp_api_key = None

    test_app.state.deps = _FakeDeps()
    test_app.include_router(market_router)
    return test_app


@pytest.fixture()
def client(app: FastAPI) -> Any:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# GET /api/market/indices
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_indices_returns_list(client: Any) -> None:
    """GET /api/market/indices returns a list of MarketIndex dicts."""
    with patch(
        "finagent.engine.compute.market.fetch_market_indices",
        new=AsyncMock(return_value=_SAMPLE_INDICES),
    ):
        async with client as c:
            resp = await c.get("/api/market/indices")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["symbol"] == "^GSPC"
    assert data[0]["price"] == pytest.approx(5230.0)


@pytest.mark.asyncio
async def test_get_indices_empty_when_provider_fails(client: Any) -> None:
    """When fetch_market_indices returns [], the route returns empty list (not 500)."""
    with patch(
        "finagent.engine.compute.market.fetch_market_indices",
        new=AsyncMock(return_value=[]),
    ):
        async with client as c:
            resp = await c.get("/api/market/indices")

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_indices_response_fields(client: Any) -> None:
    """Each MarketIndex has symbol, name, price, change, change_pct fields."""
    with patch(
        "finagent.engine.compute.market.fetch_market_indices",
        new=AsyncMock(return_value=_SAMPLE_INDICES),
    ):
        async with client as c:
            resp = await c.get("/api/market/indices")

    item = resp.json()[0]
    assert set(item.keys()) >= {"symbol", "name", "price", "change", "change_pct"}


# ---------------------------------------------------------------------------
# GET /api/market/sectors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_sectors_returns_list(client: Any) -> None:
    """GET /api/market/sectors returns a list of sector ETF dicts."""
    with patch(
        "finagent.engine.compute.market.fetch_sector_etfs",
        new=AsyncMock(return_value=_SAMPLE_SECTORS),
    ):
        async with client as c:
            resp = await c.get("/api/market/sectors")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["symbol"] == "XLK"


@pytest.mark.asyncio
async def test_get_sectors_empty_graceful(client: Any) -> None:
    """Empty sector list is a valid response — frontend handles it."""
    with patch(
        "finagent.engine.compute.market.fetch_sector_etfs",
        new=AsyncMock(return_value=[]),
    ):
        async with client as c:
            resp = await c.get("/api/market/sectors")

    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# GET /api/market/earnings-calendar
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_earnings_calendar_no_fmp_key_returns_empty(client: Any) -> None:
    """Earnings calendar returns empty list when no FMP key is configured.

    The route passes fmp_key=None to fetch_earnings_calendar, which returns [].
    No error should be raised.
    """
    with patch(
        "finagent.engine.compute.market.fetch_earnings_calendar",
        new=AsyncMock(return_value=[]),
    ) as mock_fn:
        async with client as c:
            resp = await c.get("/api/market/earnings-calendar")

    assert resp.status_code == 200
    assert resp.json() == []
    mock_fn.assert_called_once_with(None)


@pytest.mark.asyncio
async def test_get_earnings_calendar_with_events(client: Any) -> None:
    """Earnings calendar returns event list when FMP key present."""
    with patch(
        "finagent.engine.compute.market.fetch_earnings_calendar",
        new=AsyncMock(return_value=_SAMPLE_EARNINGS),
    ):
        async with client as c:
            resp = await c.get("/api/market/earnings-calendar")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["ticker"] == "AAPL"
    assert data[0]["time"] == "BMO"
    assert data[0]["eps_estimate"] == pytest.approx(1.45)


@pytest.mark.asyncio
async def test_get_earnings_calendar_event_fields(client: Any) -> None:
    """Each EarningsEvent has date, ticker, company_name, time, eps_estimate."""
    with patch(
        "finagent.engine.compute.market.fetch_earnings_calendar",
        new=AsyncMock(return_value=_SAMPLE_EARNINGS),
    ):
        async with client as c:
            resp = await c.get("/api/market/earnings-calendar")

    item = resp.json()[0]
    assert set(item.keys()) >= {"date", "ticker", "company_name", "time", "eps_estimate"}
