"""End-to-end tests for GET /api/valuation/historical-bands/{ticker} (v5 PR3)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, ConfigDict

from finrobot.engine.data.cache import DataCache
from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.normalize.contracts import NormalizedPrice, PriceBar, Provenance
from finrobot.engine.data.types import DataType
from finrobot.routes.valuation import router

UTC = timezone.utc
NOW = datetime(2026, 5, 21, tzinfo=UTC)


def _yearly_results(years: list[int]) -> list[DataResult]:
    return [
        DataResult(
            data={
                "fiscal_year": f"{y}-12-31",
                "ebitda": 25_000_000_000.0 + y * 100,
                "operating_cash_flow": 18_000_000_000.0,
                "capital_expenditure": -2_000_000_000.0,
                "total_debt": 11_000_000_000.0,
                "total_cash": 8_000_000_000.0,
                "shares_outstanding": 2.4e9,
            },
            provider="stub",
            ticker="NVDA",
            data_type=DataType.FINANCIALS,
            timestamp=NOW,
        )
        for y in years
    ]


def _price_result(num_days: int = 30) -> DataResult:
    history = [
        {"date": f"2026-{((i // 28) + 1):02d}-{((i % 28) + 1):02d}", "close": 800 + i}
        for i in range(num_days)
    ]
    return DataResult(
        data={"current_price": 800.0 + num_days - 1, "price_history": history},
        provider="stub",
        ticker="NVDA",
        data_type=DataType.PRICE,
        timestamp=NOW,
    )


class _StubDataLayer:
    """Minimal DataLayer that satisfies the route's fetch surface."""

    def __init__(self, cache_db: str) -> None:
        self._cache = DataCache(db_path=cache_db)
        self.fetch_calls: list[tuple[str, str]] = []
        self.fetch_historical_calls: list[tuple[str, str, int]] = []
        self.fetch_price_range_calls: list[tuple[str, str, str]] = []

    @property
    def cache(self) -> DataCache:
        return self._cache

    async def fetch(self, data_type: DataType | str, ticker: str, **_: object) -> DataResult:
        self.fetch_calls.append((str(data_type), ticker))
        if data_type == DataType.PRICE:
            return _price_result(60)
        return DataResult(
            data={}, provider="stub", ticker=ticker, data_type=DataType(data_type), timestamp=NOW
        )

    async def fetch_canonical(
        self, data_type: DataType | str, ticker: str, **_: object
    ) -> NormalizedPrice:
        if DataType(data_type) != DataType.PRICE:
            raise ValueError(f"unsupported canonical type: {data_type}")
        raw = await self.fetch(DataType.PRICE, ticker)
        bars = [
            PriceBar(date=date.fromisoformat(str(row["date"])), close=float(row["close"]))
            for row in raw.data["price_history"]
        ]
        return NormalizedPrice(
            ticker=ticker,
            current_price=float(raw.data["current_price"]),
            bars=bars,
            provenance=Provenance(provider="stub", as_of=NOW, fetched_at=NOW),
        )

    async def fetch_price_range(self, ticker: str, start: str, end: str) -> list[PriceBar]:
        self.fetch_price_range_calls.append((ticker, start, end))
        return [
            PriceBar(date=date.fromisoformat(str(row["date"])), close=float(row["close"]))
            for row in _price_result(60).data["price_history"]
        ]

    async def fetch_historical(
        self, data_type: DataType | str, ticker: str, years: int = 5, **_: object
    ) -> list[DataResult]:
        self.fetch_historical_calls.append((str(data_type), ticker, years))
        return _yearly_results([2022, 2023, 2024, 2025])


class _StubDeps(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    data_layer: _StubDataLayer


def _app(tmp_path: Path) -> tuple[FastAPI, _StubDataLayer]:
    layer = _StubDataLayer(cache_db=str(tmp_path / "cache.db"))
    app = FastAPI()
    app.include_router(router)
    app.state.deps = _StubDeps(data_layer=layer)
    return app, layer


@pytest.mark.asyncio
async def test_historical_bands_endpoint_ev_ebitda_returns_quantiles(tmp_path: Path) -> None:
    app, layer = _app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/valuation/historical-bands/NVDA?metric=ev_ebitda&years=3")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ticker"] == "NVDA"
    assert body["metric"] == "ev_ebitda"
    assert body["sample_count"] > 0
    assert body["current"] is not None
    assert body["median"] is not None
    assert body["classification"] in ("expensive", "fair", "cheap", "unknown")


@pytest.mark.asyncio
async def test_historical_bands_endpoint_cached_so_second_call_skips_fetch(tmp_path: Path) -> None:
    app, layer = _app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        await client.get("/api/valuation/historical-bands/NVDA?metric=ev_ebitda&years=3")
        first_history = len(layer.fetch_historical_calls)
        first_price = len(layer.fetch_price_range_calls)
        await client.get("/api/valuation/historical-bands/NVDA?metric=ev_ebitda&years=3")
    # Second call must NOT trigger fetch_historical or fetch — cache hit.
    assert len(layer.fetch_historical_calls) == first_history
    assert len(layer.fetch_price_range_calls) == first_price


class _EmptyBandDataLayer(_StubDataLayer):
    """Steady-state provider outage: the loaders return empty → an empty band
    (sample_count 0, all-None percentiles), but the route still returns 200."""

    async def fetch_price_range(self, ticker: str, start: str, end: str) -> list[PriceBar]:
        self.fetch_price_range_calls.append((ticker, start, end))
        return []

    async def fetch_historical(
        self, data_type: DataType | str, ticker: str, years: int = 5, **_: object
    ) -> list[DataResult]:
        self.fetch_historical_calls.append((str(data_type), ticker, years))
        return []


@pytest.mark.asyncio
async def test_historical_bands_empty_band_not_cached_self_heals(tmp_path: Path) -> None:
    """Bug-4 (2026-06-24): a transient empty band (steady-state provider outage →
    sample_count 0) must NOT be written to the 12h cache, so a second request after the
    outage clears re-fetches and self-heals instead of serving the empty band for 12h.
    The empty band is still a 200 (not a 500) — _build returns it, never raises."""
    layer = _EmptyBandDataLayer(cache_db=str(tmp_path / "cache.db"))
    app = FastAPI()
    app.include_router(router)
    app.state.deps = _StubDeps(data_layer=layer)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r1 = await client.get("/api/valuation/historical-bands/NVDA?metric=ev_ebitda&years=3")
        assert r1.status_code == 200, r1.text
        assert r1.json()["sample_count"] == 0
        first_history = len(layer.fetch_historical_calls)
        r2 = await client.get("/api/valuation/historical-bands/NVDA?metric=ev_ebitda&years=3")
    # Empty band was NOT cached → the second call re-fetches (self-heals after outage).
    assert len(layer.fetch_historical_calls) > first_history
    assert r2.status_code == 200
    assert r2.json()["sample_count"] == 0


@pytest.mark.asyncio
async def test_historical_bands_endpoint_503_when_data_layer_missing(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/valuation/historical-bands/NVDA")
    assert r.status_code == 503


class _FinancialsStubDataLayer(_StubDataLayer):
    """Adds a canonical FINANCIALS (TTM) snapshot so the route can compute the
    current_override. TTM EBITDA (40e9) deliberately differs from the annual
    ebitda (~25e9) the bands samples use, so the override-vs-fallback paths
    yield distinguishable 'current' values."""

    async def fetch_canonical(self, data_type: DataType | str, ticker: str, **kw: object) -> object:
        if DataType(data_type) == DataType.FINANCIALS:
            from finrobot.engine.data.normalize.financials import normalize_financials

            # fetch_canonical(FINANCIALS) returns a raw-provider-shaped
            # NormalizedFinancials (NOT a pre-extracted FinancialData) — the route
            # projects it through extract_financial_data. Build it with the SAME
            # normaliser production uses so this exercises the real path (the old
            # FinancialData fixture was a shape fetch_canonical never returns, which
            # is exactly why the inert isinstance override stayed green here while
            # being dead in production). market_cap is kept consistent with
            # shares × current_price so extract's live-price mark-to is a no-op.
            raw = DataResult(
                data={
                    "revenue": 100e9,
                    "ebitda": 40e9,  # TTM, deliberately ≠ the annual band samples
                    "net_income": 30e9,
                    "gross_margin": 0.6,
                    "operating_margin": 0.4,
                    "market_cap": 2.4e9 * 859.0,
                    "shares_outstanding": 2.4e9,
                    "current_price": 859.0,
                    "total_debt": 11e9,
                    "total_cash": 8e9,
                },
                provider="stub",
                ticker=ticker,
                data_type=DataType.FINANCIALS,
                timestamp=NOW,
            )
            return normalize_financials(raw)
        return await super().fetch_canonical(data_type, ticker, **kw)


@pytest.mark.asyncio
async def test_historical_bands_current_uses_canonical_ttm_override(tmp_path: Path) -> None:
    """W1-C2: the standalone band's 'current' must be the canonical TTM
    EV/EBITDA (the same口径 the report's comps/technical chapters report), NOT
    the trailing-annual samples[-1]. Otherwise this route flips a ticker's
    贵/合理/便宜 verdict against the report on the same metric."""
    layer = _FinancialsStubDataLayer(cache_db=str(tmp_path / "cache.db"))
    app = FastAPI()
    app.include_router(router)
    app.state.deps = _StubDeps(data_layer=layer)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/valuation/historical-bands/NVDA?metric=ev_ebitda&years=3")
    assert r.status_code == 200, r.text
    body = r.json()
    # TTM override = (market_cap (2.4e9×859=2061.6e9) + net_debt (11e9 − 8e9)) /
    # EBITDA 40e9 = 51.615x — the canonical TTM multiple, NOT the trailing-annual
    # samples[-1] (~25e9 EBITDA would read far higher), proving the override path
    # is live rather than inert.
    assert body["current"] == pytest.approx(51.615, rel=1e-4)
    assert any("TTM" in w for w in body["warnings"]), body["warnings"]


class _BankFinancialsStubDataLayer(_StubDataLayer):
    """Canonical FINANCIALS tagging the issuer as a deposit-funded bank → its
    EV/EBITDA band is a category error and must be suppressed by the route."""

    async def fetch_canonical(self, data_type: DataType | str, ticker: str, **kw: object) -> object:
        if DataType(data_type) == DataType.FINANCIALS:
            from finrobot.engine.data.normalize.financials import normalize_financials

            raw = DataResult(
                data={
                    "revenue": 100e9,
                    "ebitda": 40e9,
                    "net_income": 30e9,
                    "gross_margin": 0.6,
                    "operating_margin": 0.4,
                    "market_cap": 2.4e9 * 859.0,
                    "shares_outstanding": 2.4e9,
                    "current_price": 859.0,
                    "total_debt": 11e9,
                    "total_cash": 8e9,
                    "industry": "Banks - Diversified",
                    "sector": "Financial Services",
                },
                provider="stub",
                ticker=ticker,
                data_type=DataType.FINANCIALS,
                timestamp=NOW,
            )
            return normalize_financials(raw)
        return await super().fetch_canonical(data_type, ticker, **kw)


@pytest.mark.asyncio
async def test_historical_bands_ev_ebitda_suppressed_for_bank(tmp_path: Path) -> None:
    """A bank's EV/EBITDA band is a category error (EV nets deposits as if they were
    capital structure; there is no clean above-the-line EBITDA), so the route must
    return an empty band — the frontend card then hides instead of classifying the
    bank 'expensive' on a meaningless 3.3× multiple. Only ev_ebitda is suppressed;
    a p_fcf band still computes for the same bank. (2026-06-26)"""
    layer = _BankFinancialsStubDataLayer(cache_db=str(tmp_path / "cache.db"))
    app = FastAPI()
    app.include_router(router)
    app.state.deps = _StubDeps(data_layer=layer)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/valuation/historical-bands/JPM?metric=ev_ebitda&years=3")
        r_pfcf = await client.get("/api/valuation/historical-bands/JPM?metric=p_fcf&years=2")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["current"] is None
    assert body["median"] is None
    assert body["sample_count"] == 0
    # The EV/EBITDA fan-out must be short-circuited — never reached the loaders.
    assert layer.fetch_historical_calls == [] or all(
        "p_fcf" not in str(c) for c in layer.fetch_historical_calls
    )
    # p_fcf is NOT an EV-based multiple → still computes for a bank.
    assert r_pfcf.status_code == 200
    assert r_pfcf.json()["sample_count"] > 0


@pytest.mark.asyncio
async def test_historical_bands_endpoint_p_fcf_metric(tmp_path: Path) -> None:
    app, _ = _app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/valuation/historical-bands/NVDA?metric=p_fcf&years=2")
    assert r.status_code == 200
    body = r.json()
    assert body["metric"] == "p_fcf"
    assert body["sample_count"] > 0


# Suppress unused-import warning for the date import (used in fixtures).
_ = date
