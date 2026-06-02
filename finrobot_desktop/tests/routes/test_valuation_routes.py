"""End-to-end test for GET /api/valuation/aggregate/{ticker} (v5 PR2)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, ConfigDict

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
from finrobot.engine.data.types import DataType
from finrobot.engine.models.financial import (
    CompanyFinancials,
    DCFInputs,
    DCFResult,
    LBOInputs,
    LBOResult,
    LBOYear,
    PeerComps,
)
from finrobot.routes.valuation import router

UTC = timezone.utc
NOW = datetime(2026, 5, 21, tzinfo=UTC)


class _StubDataLayer:
    """Returns a PRICE-shaped payload for everything except FORWARD_ESTIMATES,
    which returns the injected analyst-estimate rows (or empty when None)."""

    def __init__(self, forward_rows: list[dict] | None = None) -> None:
        self._forward_rows = forward_rows

    async def fetch(self, data_type: DataType | str, ticker: str, **_: object) -> DataResult:
        if DataType(data_type) == DataType.FORWARD_ESTIMATES:
            return DataResult(
                data={"rows": self._forward_rows or []},
                provider="stub",
                ticker=ticker,
                data_type=DataType.FORWARD_ESTIMATES,
                timestamp=NOW,
            )
        return DataResult(
            data={"current_price": 876.42, "price_history": []},
            provider="stub",
            ticker=ticker,
            data_type=DataType.PRICE,
            timestamp=NOW,
        )


class _StubDeps(BaseModel):
    """Mimics FinRobotDeps just enough that routes/valuation can read .data_layer."""

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


def _comps_artifact() -> Artifact:
    """A comps artifact whose peer_analysis carries a median P/E, so the
    aggregator's comps_pe row activates and consumes forward EPS when present."""
    target = CompanyFinancials(
        ticker="NVDA",
        revenue=60e9,
        ebitda=37e9,
        net_income=30e9,
        market_cap=2.1e12,
        gross_margin=0.75,
        operating_margin=0.62,
    )
    peer = CompanyFinancials(
        ticker="AMD",
        revenue=23e9,
        ebitda=5e9,
        net_income=1e9,
        market_cap=2.5e11,
        gross_margin=0.50,
        operating_margin=0.20,
    )
    comps = PeerComps(target=target, peers=[peer], median_pe=20.0, warnings=[])
    return Artifact(
        id="art_2026-05-18T00:00:00_NVDA_comps",
        ticker="NVDA",
        cross_tickers=[],
        type="comps",
        inputs=ArtifactInputs(data_source="yfinance", data_fetched_at=NOW, raw_data={}),
        assumptions=ArtifactAssumptions(parameters={}),
        compute_version=ArtifactComputeVersion(version="0.1.0", formula_id="comps"),
        outputs=ArtifactOutputs(structured={"peer_analysis": comps.model_dump(mode="json")}),
        meta=ArtifactMeta(created_at=NOW, source="pipeline:comps"),
    )


async def _app_with_artifacts(
    tmp_dir: Path, *artifacts: Artifact, forward_rows: list[dict] | None = None
) -> FastAPI:
    store = ArtifactStore(base_dir=tmp_dir)
    for art in artifacts:
        await store.save(art)
    app = FastAPI()
    app.include_router(router)
    app.state.artifact_store = store
    app.state.deps = _StubDeps(data_layer=_StubDataLayer(forward_rows))
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
async def test_aggregate_endpoint_uses_forward_eps_when_estimates_available(
    tmp_path: Path,
) -> None:
    # FMP-style rows: farthest-future first. The route must pick FY1 (nearest
    # upcoming FYE = 2030-09-30, EPS 8.6), NOT rows[0] (2031, EPS 9.5).
    forward_rows = [
        {"date": "2031-09-30", "estimatedEpsAvg": 9.5},
        {"date": "2030-09-30", "estimatedEpsAvg": 8.6},
    ]
    app = await _app_with_artifacts(tmp_path, _comps_artifact(), forward_rows=forward_rows)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/valuation/aggregate/NVDA")
    assert r.status_code == 200
    body = r.json()
    comps = next(m for m in body["methods"] if m["method"] == "comps_pe")
    # Forward EPS flowed through — source proves it, and 20 × 8.6 = 172 proves
    # FY1 selection (20 × 9.5 = 190 would mean the farthest row leaked in). The
    # source also discloses the as-reported peer-P/E口径 (BUG-029).
    assert comps["source"].startswith("peer_median_pe × forward_eps")
    assert "as-reported" in comps["source"]
    assert abs(comps["mid"] - 172.0) < 0.01


@pytest.mark.asyncio
async def test_aggregate_endpoint_degrades_to_trailing_without_estimates(
    tmp_path: Path,
) -> None:
    # No forward rows (e.g. no FMP key) → comps_pe falls back to trailing EPS
    # with a warning, never invents a forward number. DCF artifact supplies the
    # shares the trailing EPS = net_income / shares path needs.
    app = await _app_with_artifacts(tmp_path, _comps_artifact(), _dcf_artifact())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/valuation/aggregate/NVDA")
    assert r.status_code == 200
    body = r.json()
    comps = next(m for m in body["methods"] if m["method"] == "comps_pe")
    # comps_pe is labeled trailing (not a forward multiple passed off as valid),
    # and the forward EV/EBITDA + P/FCF rows drop out with explicit warnings.
    assert "trailing" in comps["source"]
    assert "forward 不可得" in comps["source"]
    assert any("forward EBITDA" in w for w in body["warnings"])


@pytest.mark.asyncio
async def test_aggregate_endpoint_503_when_artifact_store_missing(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(router)
    # no artifact_store on state — should 503
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/valuation/aggregate/NVDA")
    assert r.status_code == 503
