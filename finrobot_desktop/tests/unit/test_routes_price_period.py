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

from finrobot.engine.data.cache import raw_slot_key
from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.types import DataType
from finrobot.engine.data.normalize.session import compute_session_state


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
            warnings=[
                "Price discrepancy: fmp 212.60 vs yfinance 200.00",
                "FMP quote failed for url 'https://financialmodelingprep.com/api/v3/quote/NVDA?apikey=secret'\nFor more information check: https://developer.mozilla.org/",
            ],
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
    assert any("Price discrepancy" in w for w in payload["warnings"])
    warning_blob = " ".join(payload["warnings"])
    assert "http" not in warning_blob
    assert "apikey" not in warning_blob
    assert "for url" not in warning_blob
    # Regression: the provider-cache fast path bypasses fetch_price_history, so
    # technicals must be backfilled at the _enrich choke point — not only on the
    # fetch path. Two bars is too short for a snapshot, but the key must exist.
    assert payload["technicals"] == {"available": False, "reason": "insufficient_history"}


@pytest.mark.asyncio
async def test_price_endpoint_provider_cache_path_carries_full_technicals(app_with_deps):
    """A rich provider-cache history yields a full technicals snapshot on the
    fast path (not just the fetch_price_history path)."""
    app = app_with_deps
    cache = app.state.deps.data_layer.cache
    history = [
        {"date": f"2025-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}", "close": float(i)}
        for i in range(1, 221)
    ]
    await cache.set(
        DataType.PRICE,
        "MSFT",
        DataResult(
            data={"current_price": 220.0, "price_history": history, "exchange": "NasdaqGS"},
            provider="fmp",
            ticker="MSFT",
            data_type=DataType.PRICE,
            timestamp=datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc),
        ),
    )
    with patch(
        "finrobot.routes.data.fetch_price_history",
        new=AsyncMock(side_effect=AssertionError("route should not hit the fetcher")),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/data/MSFT/price")

    assert resp.status_code == 200
    tech = resp.json()["technicals"]
    assert tech["available"] is True
    assert tech["trend"] == "uptrend"
    assert tech["sma20"] > tech["sma50"] > tech["sma200"]


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
async def test_price_market_cap_marked_to_live_not_grafted_stale(app_with_deps):
    """C1: when the market_cap is filled from the financials cache, it must be
    recomputed as shares × the served live current_price — never the cached
    absolute cap frozen at a prior close. Reproduces the live MU bug (probe
    2026-06-09): financials cap = 1.1277B × 864.01 (prior close) grafted onto a
    payload showing live 949.28 made market_cap/price ≠ shares (−9.0% off)."""
    app = app_with_deps
    cache = app.state.deps.data_layer.cache
    # Route-cache payload: fresh live price, no cap of its own.
    await cache.set(
        DataType.PRICE,
        "MU:1y",
        DataResult(
            data={
                "ticker": "MU",
                "current_price": 949.28,
                "market_cap": None,
                "company_name": None,
                "history": [],
                "fetched_at": "2026-06-09T12:00:00+00:00",
                "data_source": "fmp",
                "warnings": [],
            },
            provider="fmp",
            ticker="MU:1y",
            data_type=DataType.PRICE,
            timestamp=datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc),
        ),
    )
    # Canonical financials (flat NormalizedFinancials shape): cap priced at the
    # prior close 864.01, shares known.
    await cache.set(
        DataType.FINANCIALS,
        "MU",
        DataResult(
            data={
                "period_basis": "ttm",
                "company_name": "Micron Technology",
                "market_cap": 974_369_997_300.0,  # = 864.01 × 1,127,730,000 (stale)
                "shares_outstanding": 1_127_730_000.0,
                "current_price": 864.01,
            },
            provider="fmp",
            ticker="MU",
            data_type=DataType.FINANCIALS,
            timestamp=datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc),
        ),
    )

    with patch(
        "finrobot.routes.data.fetch_price_history",
        new=AsyncMock(side_effect=AssertionError("route cache should serve this response")),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/data/MU/price")

    assert resp.status_code == 200
    payload = resp.json()
    # Marked to the live price, not the stale absolute.
    assert payload["market_cap"] == pytest.approx(1_127_730_000 * 949.28)
    assert payload["market_cap"] != pytest.approx(974_369_997_300.0)
    # Invariant: the served cap is consistent with the served price.
    assert payload["market_cap"] / payload["current_price"] == pytest.approx(1_127_730_000)


@pytest.mark.asyncio
async def test_price_endpoint_surfaces_pre_market_session_from_market_state(app_with_deps):
    """End-to-end: a cached route payload carrying marketState=PRE must surface
    ``session_state == "pre_market"`` through the /price enrich choke point — i.e.
    the new 7-state phase reaches the API response, driven by the provider signal
    rather than the clock fallback."""
    app = app_with_deps
    cache = app.state.deps.data_layer.cache
    await cache.set(
        DataType.PRICE,
        "AAPL:1y",
        DataResult(
            data={
                "ticker": "AAPL",
                "current_price": 310.85,
                "market_state": "PRE",
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

    with patch(
        "finrobot.routes.data.fetch_price_history",
        new=AsyncMock(side_effect=AssertionError("route cache should serve this response")),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/data/AAPL/price")

    assert resp.status_code == 200
    assert resp.json()["session_state"] == "pre_market"


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
        WHERE data_type = ? AND ticker = 'NVDA'
        """,
        (raw_slot_key(DataType.PRICE),),
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
    assert payload["warnings"][0].startswith("Data source request failed")


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
        new=AsyncMock(side_effect=ValueError("unknown ticker 'INVALID'")),
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
        new=AsyncMock(
            side_effect=ProviderError(
                "FMP quote failed for url "
                "'https://financialmodelingprep.com/api/v3/quote/AAPL?apikey=secret'"
                "\nFor more information check: https://developer.mozilla.org/"
            )
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/data/AAPL/price?period=1y")

    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert "Data source" in detail or "temporarily unavailable" in detail
    assert "apikey" not in detail
    assert "for url" not in detail
    assert "financialmodelingprep.com" not in detail


@pytest.mark.asyncio
async def test_price_fetch_path_always_includes_ticker_and_quote_timestamp(app_with_deps):
    """The fetcher path's payload (``fetch_price_history``) omits ``ticker`` and
    ``quote_timestamp``, while the 1y provider-cache fast path sets both — so the
    /price response shape silently differed by which path served it. The frontend
    types ``ticker`` as required; a non-1y / cache-miss response left it undefined.
    Every path flows through the _enrich choke point, which now guarantees both
    keys, so the contract is stable regardless of period or cache state."""
    app = app_with_deps

    # Deliberately omit ticker + quote_timestamp, as the real fetcher does.
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
            resp = await client.get("/api/data/AAPL/price?period=5d")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ticker"] == "AAPL"  # required by the frontend type, was undefined here
    assert "quote_timestamp" in body  # key present (null ok) — parity with the 1y path


@pytest.mark.asyncio
async def test_price_rejects_unknown_period(app_with_deps):
    """An unrecognised period must be rejected with 422 (typed Literal), not
    silently accepted as a new cache slot serving full 1y data."""
    app = app_with_deps

    with patch(
        "finrobot.routes.data.fetch_price_history",
        new=AsyncMock(return_value={"current_price": 1.0, "history": [], "warnings": []}),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/data/AAPL/price?period=not-a-period")

    assert resp.status_code == 422


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
# session state from the viewer's local date. compute_session_state decides
# live-vs-closed in America/New_York so a viewer east of ET (e.g. China, UTC+8)
# can't see a live US quote mislabeled "收盘" once the session runs past their
# local midnight (ET 12:00–16:00 = CN 00:00–04:00).

_ET = ZoneInfo("America/New_York")


def test_session_live_during_regular_hours_with_today_bar():
    # Wed 2026-05-27 13:00 ET — regular session, today's bar present.
    now = datetime(2026, 5, 27, 13, 0, tzinfo=_ET)
    assert compute_session_state("2026-05-27", now=now) == "live"


def test_session_live_at_china_midnight_window_is_not_mislabeled_closed():
    # The exact bug: ET 13:00 Wed == CN 01:00 Thu. Viewer-local date is already
    # "tomorrow" but the US session is live → backend must say live.
    now = datetime(2026, 5, 27, 13, 0, tzinfo=_ET)
    assert compute_session_state("2026-05-27", now=now) == "live"


def test_session_closed_before_open():
    now = datetime(2026, 5, 27, 9, 0, tzinfo=_ET)
    assert compute_session_state("2026-05-26", now=now) == "closed"


def test_session_closed_after_close():
    now = datetime(2026, 5, 27, 16, 30, tzinfo=_ET)
    assert compute_session_state("2026-05-27", now=now) == "closed"


def test_session_closed_on_weekend():
    # Sat 2026-05-30 13:00 ET — within clock window but not a trading day.
    now = datetime(2026, 5, 30, 13, 0, tzinfo=_ET)
    assert compute_session_state("2026-05-29", now=now) == "closed"


def test_session_closed_on_holiday_via_missing_today_bar():
    # Clock is inside regular hours, but no bar for today (holiday) → as_of is a
    # prior day → closed. No holiday calendar needed.
    now = datetime(2026, 5, 27, 13, 0, tzinfo=_ET)
    assert compute_session_state("2026-05-25", now=now) == "closed"


def test_session_closed_at_exact_close_boundary():
    now = datetime(2026, 5, 27, 16, 0, tzinfo=_ET)
    assert compute_session_state("2026-05-27", now=now) == "closed"


def test_session_closed_when_as_of_missing_or_garbage():
    now = datetime(2026, 5, 27, 13, 0, tzinfo=_ET)
    assert compute_session_state(None, now=now) == "closed"
    assert compute_session_state("not-a-date", now=now) == "closed"


def test_session_state_accepts_timestamp_as_of():
    # Defensive: if as_of ever carries a time component, only the date counts.
    now = datetime(2026, 5, 27, 13, 0, tzinfo=_ET)
    assert compute_session_state("2026-05-27T00:00:00Z", now=now) == "live"


# ── BUG-081: market/exchange-aware session state ───────────────────────────
#
# The prior logic hardcoded the US 9:30–16:00 ET window for every ticker, so a
# HK/A-share/JP intraday quote (which falls in ET overnight) was always stamped
# "closed" and the freshness pill showed a real-time quote as a prior-day close.
# Session state must resolve the exchange from the yfinance ticker suffix.

_HKT = ZoneInfo("Asia/Hong_Kong")
_CST = ZoneInfo("Asia/Shanghai")
_JST = ZoneInfo("Asia/Tokyo")


def test_session_us_path_unchanged_for_suffixless_ticker():
    # Regression guard: AAPL (no suffix) still resolves to the US session.
    now = datetime(2026, 5, 27, 13, 0, tzinfo=_ET)
    assert compute_session_state("2026-05-27", ticker="AAPL", now=now) == "live"


def test_session_hk_intraday_is_live_not_closed():
    # 0700.HK at 10:00 HKT Wed == 22:00 ET Tue — the exact bug window. Must be
    # "live" in HK local time, not "closed" from a US-ET lens.
    now = datetime(2026, 5, 27, 10, 0, tzinfo=_HKT)
    assert compute_session_state("2026-05-27", ticker="0700.HK", now=now) == "live"
    # Same instant, computed against the US default, would (wrongly) be "closed".
    assert compute_session_state("2026-05-27", ticker="AAPL", now=now) == "closed"


def test_session_ashare_intraday_is_live():
    # 600519.SS at 14:00 CST — within the 09:30–15:00 Shanghai session.
    now = datetime(2026, 5, 27, 14, 0, tzinfo=_CST)
    assert compute_session_state("2026-05-27", ticker="600519.SS", now=now) == "live"
    # After the 15:00 Shanghai close → closed.
    after = datetime(2026, 5, 27, 15, 30, tzinfo=_CST)
    assert compute_session_state("2026-05-27", ticker="600519.SZ", now=after) == "closed"


def test_session_japan_intraday_is_live():
    # 7203.T at 11:00 JST — within the 09:00–15:00 Tokyo session.
    now = datetime(2026, 5, 27, 11, 0, tzinfo=_JST)
    assert compute_session_state("2026-05-27", ticker="7203.T", now=now) == "live"


def test_session_unknown_for_unmapped_suffix():
    # An exchange suffix we don't map must NOT be faked as US "closed" — return
    # "unknown" so the UI can't lie about a foreign quote.
    now = datetime(2026, 5, 27, 13, 0, tzinfo=_ET)
    assert compute_session_state("2026-05-27", ticker="ABC.XYZ", now=now) == "unknown"


def test_session_unknown_for_unrecognized_nonus_exchange_without_suffix():
    # Suffix-less ticker but provider reports a non-US exchange code → unknown,
    # not a fabricated US session.
    now = datetime(2026, 5, 27, 13, 0, tzinfo=_ET)
    assert compute_session_state("2026-05-27", ticker="FOO", exchange="XETRA", now=now) == "unknown"


def test_session_us_exchange_code_resolves_to_us():
    # Suffix-less ticker carrying a known US exchange code → US session.
    now = datetime(2026, 5, 27, 13, 0, tzinfo=_ET)
    assert compute_session_state("2026-05-27", ticker="MSFT", exchange="NMS", now=now) == "live"
