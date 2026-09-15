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
from finrobot.engine.data.normalize.contracts import (
    NormalizedFinancials,
    NormalizedForwardEstimates,
    NormalizedPrice,
    PriceBar,
    Provenance,
)
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
    """Serves canonical PRICE / FINANCIALS / FORWARD_ESTIMATES stubs.

    ``fetch_canonical(FORWARD_ESTIMATES)`` returns the injected analyst-estimate
    rows (or empty when None) — the hard single-source slot the route now reads.
    ``fetch_canonical(FINANCIALS)`` returns a NormalizedFinancials carrying the
    configured ``reporting_currency`` so the BUG-006 forward-EPS FX conversion
    in ``routes/valuation._forward_to_usd`` can resolve the issuer's currency."""

    def __init__(
        self,
        forward_rows: list[dict] | None = None,
        *,
        reporting_currency: str = "USD",
        price_quote_currency: str = "USD",
    ) -> None:
        self._forward_rows = forward_rows
        self._reporting_currency = reporting_currency
        self._price_quote_currency = price_quote_currency

    async def fetch(self, data_type: DataType | str, ticker: str, **_: object) -> DataResult:
        return DataResult(
            data={"current_price": 876.42, "price_history": []},
            provider="stub",
            ticker=ticker,
            data_type=DataType.PRICE,
            timestamp=NOW,
        )

    async def fetch_canonical(
        self, data_type: DataType | str, ticker: str, **_: object
    ) -> NormalizedFinancials | NormalizedPrice | NormalizedForwardEstimates:
        if DataType(data_type) == DataType.FORWARD_ESTIMATES:
            return NormalizedForwardEstimates(
                ticker=ticker,
                rows=self._forward_rows or [],
                provenance=Provenance(provider="stub", as_of=NOW, fetched_at=NOW),
            )
        if DataType(data_type) == DataType.PRICE:
            return NormalizedPrice(
                ticker=ticker,
                current_price=876.42,
                quote_currency=self._price_quote_currency,
                bars=[PriceBar(date=NOW.date(), close=876.42)],
                provenance=Provenance(provider="stub", as_of=NOW, fetched_at=NOW),
            )
        return NormalizedFinancials(
            ticker=ticker,
            reporting_currency=self._reporting_currency,
            as_of=NOW,
            provenance=Provenance(provider="stub", as_of=NOW, fetched_at=NOW),
        )


class _StubSettings(BaseModel):
    fmp_api_key: str = ""


class _StubDeps(BaseModel):
    """Mimics FinRobotDeps just enough that routes/valuation can read
    .data_layer and .settings.fmp_api_key."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    data_layer: _StubDataLayer
    settings: _StubSettings = _StubSettings()


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
        # build_dcf_artifact dumps DCFResult FLAT at the top of structured (no
        # `dcf_calc` nest — that key only named the pipeline step).
        outputs=ArtifactOutputs(structured=dcf.model_dump(mode="json")),
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
        # build_lbo_artifact dumps LBOResult FLAT at the top of structured, not
        # under lbo_calculation. The route must parse the real artifact shape.
        outputs=ArtifactOutputs(structured=lbo.model_dump(mode="json")),
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
    tmp_dir: Path,
    *artifacts: Artifact,
    forward_rows: list[dict] | None = None,
    reporting_currency: str = "USD",
    price_quote_currency: str = "USD",
) -> FastAPI:
    store = ArtifactStore(base_dir=tmp_dir)
    for art in artifacts:
        await store.save(art)
    app = FastAPI()
    app.include_router(router)
    app.state.artifact_store = store
    app.state.deps = _StubDeps(
        data_layer=_StubDataLayer(
            forward_rows,
            reporting_currency=reporting_currency,
            price_quote_currency=price_quote_currency,
        )
    )
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
        {"date": "2031-09-30", "epsAvg": 9.5},
        {"date": "2030-09-30", "epsAvg": 8.6},
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
async def test_aggregate_endpoint_converts_reporting_ccy_forward_eps_to_usd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BUG-006: an ADR's FMP forward EPS is in the reporting currency (TWD).
    The aggregator multiplies it by a USD-normalized peer P/E, so the route MUST
    convert forward EPS → USD first. With reporting_currency=TWD and a mocked
    TWD→USD rate of 0.0313, EPS 98.89 (TWD) → ≈ $3.095 (USD), so the comps_pe
    mid is 20 × 3.095 ≈ $61.9 — NOT 20 × 98.89 ≈ $1,978 (the un-converted bug)."""
    twd_usd = 0.0313

    async def _fake_fx(from_ccy: str, *, fmp_api_key: str | None = None) -> float:
        assert from_ccy.upper() == "TWD"
        return twd_usd

    # Patch the FX source: routes/valuation lazy-imports fetch_fx_rate_to_usd
    # locally (sidecar cold-start fix), so the canonical source is the patch point.
    monkeypatch.setattr("finrobot.engine.data.providers.fx.fetch_fx_rate_to_usd", _fake_fx)

    forward_rows = [{"date": "2030-09-30", "epsAvg": 98.89}]  # TWD per share
    app = await _app_with_artifacts(
        tmp_path, _comps_artifact(), forward_rows=forward_rows, reporting_currency="TWD"
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/valuation/aggregate/NVDA")
    assert r.status_code == 200
    body = r.json()
    comps = next(m for m in body["methods"] if m["method"] == "comps_pe")
    expected = 20.0 * (98.89 * twd_usd)  # ≈ 61.9
    assert abs(comps["mid"] - expected) < 0.05
    # The un-converted TWD result would have been ~1,978 — prove we're nowhere near it.
    assert comps["mid"] < 200


@pytest.mark.asyncio
async def test_aggregate_endpoint_converts_foreign_quote_price_to_usd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The PRICE canonical is NEVER FX-normalized (it stays in the quote currency).
    For a foreign LOCAL listing (quote=TWD) the football field would compare a TWD
    live price against USD valuation methods — the aggregate current_price MUST be
    converted to USD first, mirroring the forward-EPS fix (_forward_to_usd)."""
    twd_usd = 0.0313

    async def _fake_fx(from_ccy: str, *, fmp_api_key: str | None = None) -> float:
        assert from_ccy.upper() == "TWD"
        return twd_usd

    monkeypatch.setattr("finrobot.engine.data.providers.fx.fetch_fx_rate_to_usd", _fake_fx)

    app = await _app_with_artifacts(
        tmp_path, _dcf_artifact(), reporting_currency="TWD", price_quote_currency="TWD"
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/valuation/aggregate/NVDA")
    assert r.status_code == 200
    body = r.json()
    # 876.42 TWD → 876.42 × 0.0313 ≈ $27.43 USD — NOT the raw 876.42.
    assert body["current_price"] == pytest.approx(876.42 * twd_usd, abs=0.01)


@pytest.mark.asyncio
async def test_aggregate_endpoint_usd_price_no_fx(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """US / pure-ADR (quote==USD): the FX path is a strict no-op — the live price
    flows through unchanged and the FX provider is never consulted."""

    async def _boom_fx(*_a: object, **_k: object) -> float:
        raise AssertionError("USD price must not consult the FX provider")

    monkeypatch.setattr("finrobot.engine.data.providers.fx.fetch_fx_rate_to_usd", _boom_fx)

    app = await _app_with_artifacts(tmp_path, _dcf_artifact())  # quote defaults to USD
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/valuation/aggregate/NVDA")
    assert r.status_code == 200
    assert r.json()["current_price"] == 876.42


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
    # comps_pe is labeled trailing (not a forward multiple passed off as valid), and the
    # EV/EBITDA + P/FCF rows drop out with explicit warnings (no historical band in this
    # fixture; batch2 also decoupled ev_ebitda from forward estimates → its warning now
    # names the TTM denominator, not the forward one).
    assert "trailing" in comps["source"]
    assert "forward unavailable" in comps["source"]
    assert any("TTM EBITDA" in w for w in body["warnings"])


@pytest.mark.asyncio
async def test_aggregate_endpoint_exposes_forward_provenance_fields(tmp_path: Path) -> None:
    """forward_fiscal_period / forward_confidence / forward_source must be present
    in the response so the frontend can show which FY drives the forward rows
    and where the estimates came from — the whole fix for BACKLOG issue 3."""
    forward_rows = [{"date": "2026-09-30", "epsAvg": 8.6, "ebitdaAvg": 45e9}]
    app = await _app_with_artifacts(tmp_path, _comps_artifact(), forward_rows=forward_rows)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/valuation/aggregate/NVDA")
    assert r.status_code == 200
    body = r.json()
    assert body["forward_fiscal_period"] == "2026-09-30"
    assert body["forward_confidence"] == "high"  # EPS + EBITDA both present → high
    assert body["forward_source"] == "FMP stable/analyst-estimates consensus"


@pytest.mark.asyncio
async def test_aggregate_endpoint_forward_provenance_none_when_unavailable(tmp_path: Path) -> None:
    """When no forward data is available all three provenance fields stay None."""
    app = await _app_with_artifacts(tmp_path, _comps_artifact(), forward_rows=[])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/valuation/aggregate/NVDA")
    assert r.status_code == 200
    body = r.json()
    assert body["forward_fiscal_period"] is None
    assert body["forward_confidence"] is not None  # "unavailable" string, not None
    assert body["forward_source"] is not None  # describes why it failed


@pytest.mark.asyncio
async def test_aggregate_endpoint_503_when_artifact_store_missing(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(router)
    # no artifact_store on state — should 503
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get("/api/valuation/aggregate/NVDA")
    assert r.status_code == 503
