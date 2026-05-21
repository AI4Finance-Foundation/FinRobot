"""End-to-end test for GET /api/valuation/aggregate/{ticker} (v5 PR2)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, ConfigDict

from finagent.artifact.models import (
    Artifact,
    ArtifactAssumptions,
    ArtifactComputeVersion,
    ArtifactInputs,
    ArtifactMeta,
    ArtifactOutputs,
)
from finagent.artifact.store import ArtifactStore
from finagent.engine.data.interface import DataResult
from finagent.engine.data.types import DataType
from finagent.engine.models.financial import (
    DCFInputs,
    DCFResult,
    LBOInputs,
    LBOResult,
    LBOYear,
)
from finagent.routes.valuation import router

UTC = timezone.utc
NOW = datetime(2026, 5, 21, tzinfo=UTC)


class _StubDataLayer:
    async def fetch(self, data_type: DataType | str, ticker: str, **_: object) -> DataResult:
        return DataResult(
            data={"current_price": 876.42, "price_history": []},
            provider="stub",
            ticker=ticker,
            data_type=DataType.PRICE,
            timestamp=NOW,
        )


class _StubDeps(BaseModel):
    """Mimics FinAgentDeps just enough that routes/valuation can read .data_layer."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    data_layer: _StubDataLayer


def _dcf_artifact() -> Artifact:
    dcf = DCFResult(
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
        implied_price=920.0,
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
    return Artifact(
        id="art_2026-05-20T00:00:00_NVDA_dcf",
        ticker="NVDA",
        cross_tickers=[],
        type="dcf",
        inputs=ArtifactInputs(data_source="yfinance", data_fetched_at=NOW, raw_data={}),
        assumptions=ArtifactAssumptions(parameters={}),
        compute_version=ArtifactComputeVersion(version="0.1.0", formula_id="dcf"),
        outputs=ArtifactOutputs(structured={"dcf_calc": dcf.model_dump(mode="json")}),
        meta=ArtifactMeta(created_at=NOW, source="pipeline:dcf"),
    )


def _lbo_artifact() -> Artifact:
    schedule = [
        LBOYear(
            year=i,
            revenue=100,
            ebitda=30,
            da=4,
            ebit=26,
            interest_expense=8,
            ebt=18,
            taxes=4,
            net_income=14,
            capex=4,
            delta_nwc=1,
            fcf=15,
            mandatory_amort=2,
            cash_sweep_amount=10,
            total_debt_paydown=12,
            ending_debt=max(0, 150 - 12 * i),
        )
        for i in range(1, 6)
    ]
    lbo = LBOResult(
        entry_ev=300,
        entry_debt=150,
        entry_equity=150,
        schedule=schedule,
        exit_ebitda=40,
        exit_ev=480,
        exit_equity=400,
        moic=2.67,
        irr=0.21,
        sensitivity={
            "entry_multiples": [9.0, 10.0, 11.0],
            "exit_multiples": [10.0, 11.0, 12.0],
            "irr_grid": [[0.2]] * 3,
            "moic_grid": [[2.5]] * 3,
        },
        irr_formula_warning=None,
    )
    return Artifact(
        id="art_2026-05-19T00:00:00_NVDA_lbo",
        ticker="NVDA",
        cross_tickers=[],
        type="lbo",
        inputs=ArtifactInputs(data_source="yfinance", data_fetched_at=NOW, raw_data={}),
        assumptions=ArtifactAssumptions(
            parameters=LBOInputs(
                ticker="NVDA",
                ltm_ebitda=30,
                entry_ev_ebitda=10,
                exit_ev_ebitda=11,
                holding_period_years=5,
                revenue_base=100,
                revenue_growth_rate=0.05,
                ebitda_margin=0.3,
            ).model_dump(mode="json"),
        ),
        compute_version=ArtifactComputeVersion(version="0.1.0", formula_id="lbo"),
        outputs=ArtifactOutputs(structured={"lbo_calculation": lbo.model_dump(mode="json")}),
        meta=ArtifactMeta(created_at=NOW, source="pipeline:lbo"),
    )


async def _app_with_artifacts(tmp_dir: Path, *artifacts: Artifact) -> FastAPI:
    store = ArtifactStore(base_dir=tmp_dir)
    for art in artifacts:
        await store.save(art)
    app = FastAPI()
    app.include_router(router)
    app.state.artifact_store = store
    app.state.deps = _StubDeps(data_layer=_StubDataLayer())
    return app


@pytest.mark.asyncio
async def test_aggregate_endpoint_returns_dcf_and_lbo_methods(tmp_path: Path) -> None:
    app = await _app_with_artifacts(tmp_path, _dcf_artifact(), _lbo_artifact())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/valuation/aggregate/NVDA")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "NVDA"
    assert body["current_price"] == 876.42
    method_names = {m["method"] for m in body["methods"]}
    assert "dcf" in method_names
    assert "lbo" in method_names
    # method_type label required on every emitted row
    for row in body["methods"]:
        assert row["method_type"] in ("valuation", "multiple")


@pytest.mark.asyncio
async def test_aggregate_endpoint_with_no_artifacts_returns_warnings_only(
    tmp_path: Path,
) -> None:
    app = await _app_with_artifacts(tmp_path)  # no artifacts saved
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/valuation/aggregate/NVDA")
    assert r.status_code == 200
    body = r.json()
    assert body["methods"] == []
    assert len(body["warnings"]) >= 4


@pytest.mark.asyncio
async def test_aggregate_endpoint_503_when_artifact_store_missing(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(router)
    # no artifact_store on state — should 503
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/valuation/aggregate/NVDA")
    assert r.status_code == 503
