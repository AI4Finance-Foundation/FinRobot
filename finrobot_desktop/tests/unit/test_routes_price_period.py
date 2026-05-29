"""Tests for GET /api/data/{ticker}/price and /performance.

Verifies the routes correctly thread through the period parameter and call
the underlying service. /price now sits behind ``cached_fetch`` so the
mock targets the service function (not the cache wrapper) — first call
exercises the fetcher path; cache state is isolated per-test via the
DataCache fixture in conftest.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock

from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.types import DataType
from finrobot.routes.data import _compute_session_state


@pytest.mark.asyncio
async def test_price_endpoint_accepts_period_param(app_with_deps):
    """GET /api/data/{ticker}/price?period=3mo invokes the DataLayer-backed fetcher.

    After 门一 Step 4, ``period`` scopes only the route cache key — the fetcher
    pulls the provider's ~1y PRICE window (DataLayer.fetch_price), so it's called
    with (data_layer, ticker), not the period string.
    """
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
    mock_fetch.assert_called_once_with(app.state.deps.data_layer, "AAPL")


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
async def test_price_endpoint_reuses_provider_price_cache_for_default_period(app_with_deps):
    """Default 1y route can reuse provider-layer price cache."""
    app = app_with_deps
    cache = app.state.deps.data_layer.cache
    await cache.set(
        DataType.PRICE,
        "NVDA",
        DataResult(
            data={
                "current_price": 212.6,
                "price_history": [
                    {"date": "2026-05-26", "close": 200.0},
                    {"date": "2026-05-27", "close": 212.6},
                ],
                "exchange": "NasdaqGS",
            },
            provider="yfinance",
            ticker="NVDA",
            data_type=DataType.PRICE,
            timestamp=datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc),
        ),
    )

    with patch(
        "finrobot.routes.data.fetch_price_history",
        new=AsyncMock(side_effect=AssertionError("route should not hit yfinance")),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/data/NVDA/price")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["current_price"] == pytest.approx(212.6)
    assert payload["history"][1]["close"] == pytest.approx(212.6)
    assert payload["change"] == pytest.approx(12.6)
    assert payload["change_pct"] == pytest.approx(6.3)
    assert payload["data_source"] == "yfinance:provider-cache"


@pytest.mark.asyncio
async def test_price_endpoint_enriches_cached_payload_from_financials_cache(app_with_deps):
    """Price chart metadata should not stay blank when financials cache has it."""
    app = app_with_deps
    cache = app.state.deps.data_layer.cache
    await cache.set(
        DataType.PRICE,
        "AAPL:1y",
        DataResult(
            data={
                "ticker": "AAPL",
                "current_price": 310.85,
                "market_cap": None,
                "company_name": None,
                "history": [],
                "fetched_at": "2026-05-27T12:00:00+00:00",
                "data_source": "yfinance",
                "warnings": [],
            },
            provider="yfinance",
            ticker="AAPL:1y",
            data_type=DataType.PRICE,
            timestamp=datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc),
        ),
    )
    await cache.set(
        DataType.FINANCIALS,
        "AAPL",
        DataResult(
            data={
                "period_basis": "ttm",
                "company_name": "Apple Inc.",
                "market_cap": 4_565_564_612_600.0,
            },
            provider="fmp",
            ticker="AAPL",
            data_type=DataType.FINANCIALS,
            timestamp=datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc),
        ),
    )

    with patch(
        "finrobot.routes.data.fetch_price_history",
        new=AsyncMock(side_effect=AssertionError("route cache should serve this response")),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/data/AAPL/price")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["market_cap"] == pytest.approx(4_565_564_612_600.0)
    assert payload["company_name"] == "Apple Inc."


@pytest.mark.asyncio
async def test_price_endpoint_returns_stale_provider_cache_when_yfinance_is_rate_limited(
    app_with_deps,
):
    """A stale provider cache is better than a blank workspace during 429s."""
    from finrobot.engine.data.interface import ProviderError

    app = app_with_deps
    cache = app.state.deps.data_layer.cache
    await cache.set(
        DataType.PRICE,
        "NVDA",
        DataResult(
            data={
                "current_price": 212.6,
                "price_history": [
                    {"date": "2026-05-26", "close": 200.0},
                    {"date": "2026-05-27", "close": 212.6},
                ],
            },
            provider="yfinance",
            ticker="NVDA",
            data_type=DataType.PRICE,
            timestamp=datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc),
        ),
    )

    conn = await cache._ensure_connection()
    await conn.execute(
        """
        UPDATE cache
        SET cached_at = '2026-05-27T00:00:00+00:00'
        WHERE data_type = 'price' AND ticker = 'NVDA'
        """
    )
    await conn.commit()

    with patch(
        "finrobot.routes.data.fetch_price_history",
        new=AsyncMock(side_effect=ProviderError("yfinance service down: 429")),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/data/NVDA/price")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["current_price"] == pytest.approx(212.6)
    assert payload["warnings"][0].startswith("数据源请求失败")


@pytest.mark.asyncio
async def test_price_endpoint_different_periods_dont_share_cache(app_with_deps):
    """1y and 5d are different payloads — cache key must include period."""
    app = app_with_deps

    with patch(
        "finrobot.routes.data.fetch_price_history",
        new=AsyncMock(
            return_value={
                "current_price": 1.0,
                "history": [],
                "fetched_at": "2026-05-27T12:00:00+00:00",
                "data_source": "yfinance",
                "warnings": [],
            }
        ),
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


# ── Session-state classification ───────────────────────────────────────────
#
# Regression for the cross-timezone freshness bug: the pill must NOT derive
# session state from the viewer's local date. _compute_session_state decides
# live-vs-closed in America/New_York so a viewer east of ET (e.g. China, UTC+8)
# can't see a live US quote mislabeled "收盘" once the session runs past their
# local midnight (ET 12:00–16:00 = CN 00:00–04:00).

_ET = ZoneInfo("America/New_York")


def test_session_live_during_regular_hours_with_today_bar():
    # Wed 2026-05-27 13:00 ET — regular session, today's bar present.
    now = datetime(2026, 5, 27, 13, 0, tzinfo=_ET)
    assert _compute_session_state("2026-05-27", now_et=now) == "live"


def test_session_live_at_china_midnight_window_is_not_mislabeled_closed():
    # The exact bug: ET 13:00 Wed == CN 01:00 Thu. Viewer-local date is already
    # "tomorrow" but the US session is live → backend must say live.
    now = datetime(2026, 5, 27, 13, 0, tzinfo=_ET)
    assert _compute_session_state("2026-05-27", now_et=now) == "live"


def test_session_closed_before_open():
    now = datetime(2026, 5, 27, 9, 0, tzinfo=_ET)
    assert _compute_session_state("2026-05-26", now_et=now) == "closed"


def test_session_closed_after_close():
    now = datetime(2026, 5, 27, 16, 30, tzinfo=_ET)
    assert _compute_session_state("2026-05-27", now_et=now) == "closed"


def test_session_closed_on_weekend():
    # Sat 2026-05-30 13:00 ET — within clock window but not a trading day.
    now = datetime(2026, 5, 30, 13, 0, tzinfo=_ET)
    assert _compute_session_state("2026-05-29", now_et=now) == "closed"


def test_session_closed_on_holiday_via_missing_today_bar():
    # Clock is inside regular hours, but no bar for today (holiday) → as_of is a
    # prior day → closed. No holiday calendar needed.
    now = datetime(2026, 5, 27, 13, 0, tzinfo=_ET)
    assert _compute_session_state("2026-05-25", now_et=now) == "closed"


def test_session_closed_at_exact_close_boundary():
    now = datetime(2026, 5, 27, 16, 0, tzinfo=_ET)
    assert _compute_session_state("2026-05-27", now_et=now) == "closed"


def test_session_closed_when_as_of_missing_or_garbage():
    now = datetime(2026, 5, 27, 13, 0, tzinfo=_ET)
    assert _compute_session_state(None, now_et=now) == "closed"
    assert _compute_session_state("not-a-date", now_et=now) == "closed"


def test_session_state_accepts_timestamp_as_of():
    # Defensive: if as_of ever carries a time component, only the date counts.
    now = datetime(2026, 5, 27, 13, 0, tzinfo=_ET)
    assert _compute_session_state("2026-05-27T00:00:00Z", now_et=now) == "live"
