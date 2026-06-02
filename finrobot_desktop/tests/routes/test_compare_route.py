"""GET /api/compare — assembles comparison from stored DCF artifacts (Phase 2b/H1)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from finrobot.artifact.models import (
    Artifact,
    ArtifactAssumptions,
    ArtifactComputeVersion,
    ArtifactInputs,
    ArtifactMeta,
    ArtifactOutputs,
)
from finrobot.artifact.store import ArtifactStore
from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.normalize.financials import normalize_financials
from finrobot.engine.data.normalize.price import normalize_price
from finrobot.engine.data.types import DataType
from finrobot.engine.models.financial import DCFInputs, DCFResult
from finrobot.routes.compare import router

UTC = timezone.utc
NOW = datetime(2026, 5, 1, tzinfo=UTC)


def _dcf_result(implied: float = 260.0) -> DCFResult:
    return DCFResult(
        cost_of_equity=0.10,
        wacc=0.082,
        projection_years=5,
        projected_revenue=[1000],
        projected_ebitda=[300],
        projected_fcf=[200],
        terminal_value=4000,
        pv_terminal=3000,
        pv_fcf_total=2000,
        enterprise_value=5000,
        equity_value=4800,
        implied_price=implied,
        sensitivity_table=None,
        inputs=DCFInputs(
            revenue_base=1000,
            revenue_growth_rates=[0.10],
            ebitda_margin=0.30,
            capex_pct_revenue=0.04,
            nwc_pct_revenue=0.02,
            da_pct_revenue=0.04,
            tax_rate=0.21,
            risk_free_rate=0.04,
            beta=1.2,
            equity_risk_premium=0.05,
            cost_of_debt=0.05,
            debt_ratio=0.2,
            terminal_growth_rate=0.025,
            shares_outstanding=2.4e9,
            net_debt=30e9,
        ),
    )


def _dcf_artifact(ticker: str) -> Artifact:
    return Artifact(
        id=f"art_{ticker}_dcf",
        ticker=ticker,
        cross_tickers=[],
        type="dcf",
        inputs=ArtifactInputs(data_source="yfinance", data_fetched_at=NOW, raw_data={}),
        assumptions=ArtifactAssumptions(parameters={}),
        compute_version=ArtifactComputeVersion(version="0.1.0", formula_id="dcf"),
        outputs=ArtifactOutputs(structured={"dcf_calc": _dcf_result().model_dump(mode="json")}),
        meta=ArtifactMeta(created_at=NOW, source="pipeline:dcf"),
    )


def _canonical(ticker: str, data_type, current: float = 200.0):
    if data_type == DataType.PRICE:
        return normalize_price(
            DataResult(
                data={
                    "current_price": current,
                    "price_history": [
                        {"date": "2025-06-01", "close": 180.0},
                        {"date": "2026-03-01", "close": current},
                    ],
                },
                provider="yfinance",
                ticker=ticker,
                data_type="price",
                timestamp=NOW,
            )
        )
    return normalize_financials(
        DataResult(
            data=dict(
                revenue=100e9,
                ebitda=35e9,
                net_income=20e9,
                gross_margin=0.47,
                operating_margin=0.28,
                pe_ratio=28.5,
                market_cap=3e12,
                shares_outstanding=15e9,
                current_price=current,
                total_debt=50e9,
                total_cash=20e9,
            ),
            provider="yfinance",
            ticker=ticker,
            data_type="financials",
            timestamp=NOW,
        )
    )


class _StubDataLayer:
    async def fetch_canonical(self, data_type, ticker, **_):
        return _canonical(ticker, data_type)


@pytest.fixture
async def client(tmp_path: Path):
    app = FastAPI()
    app.include_router(router)
    store = ArtifactStore(base_dir=tmp_path)
    await store.save(_dcf_artifact("AAPL"))  # AAPL has a DCF; MSFT does not
    app.state.artifact_store = store
    app.state.deps = SimpleNamespace(data_layer=_StubDataLayer())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await store.close()


async def test_compare_assembles_from_stored_dcf(client: AsyncClient) -> None:
    r = await client.get("/api/compare", params={"tickers": "AAPL,MSFT"})
    assert r.status_code == 200
    companies = {c["ticker"]: c for c in r.json()["companies"]}

    # AAPL has a stored DCF → full valuation with live-price upside
    aapl = companies["AAPL"]
    assert aapl["error"] is None
    assert aapl["implied_price"] == pytest.approx(260.0)
    assert aapl["current_price"] == pytest.approx(200.0)
    assert aapl["upside_pct"] == pytest.approx((260 - 200) / 200 * 100)
    assert aapl["wacc"] == pytest.approx(0.082)
    assert aapl["pe_ratio"] == pytest.approx(28.5)

    # MSFT has no DCF artifact → flagged, not fabricated
    assert companies["MSFT"]["error"] is not None
    assert companies["MSFT"]["implied_price"] is None


async def test_compare_dedupes_and_uppercases(client: AsyncClient) -> None:
    r = await client.get("/api/compare", params={"tickers": "aapl, AAPL , msft"})
    assert r.status_code == 200
    tickers = [c["ticker"] for c in r.json()["companies"]]
    assert tickers == ["AAPL", "MSFT"]  # deduped, order preserved, upper-cased


async def test_compare_rejects_too_few_tickers(client: AsyncClient) -> None:
    assert (await client.get("/api/compare", params={"tickers": "AAPL"})).status_code == 400


async def test_compare_rejects_too_many_tickers(client: AsyncClient) -> None:
    many = ",".join(f"T{i}" for i in range(11))
    assert (await client.get("/api/compare", params={"tickers": many})).status_code == 400
