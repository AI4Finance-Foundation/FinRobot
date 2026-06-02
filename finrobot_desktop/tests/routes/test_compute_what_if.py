"""Tests for POST /api/compute/artifacts/{id}/what-if/dcf.

The What-if slider on a SAVED report must replay the artifact's FROZEN DCF
inputs and override ONLY the slider field — never re-fetch live financials /
price / Damodaran fallback. These tests prove:

- BASE returned == the artifact's persisted implied_price (byte-for-byte).
- NEW with a wacc_override == the pure ``calculate_dcf`` of the SAME frozen
  inputs with that override — so the delta is attributable solely to the slider.
- The endpoint reads the artifact store and does NOT touch the data layer
  (no ``fetch_canonical`` / ``seed_dcf_inputs`` reseed path).
- Works for equity_research, dcf, and ic_memo artifact shapes.
- 404 on missing artifact; 422 when the artifact carries no replayable DCF.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from finrobot.artifact.models import (
    Artifact,
    ArtifactAssumptions,
    ArtifactComputeVersion,
    ArtifactInputs,
    ArtifactMeta,
    ArtifactOutputs,
)
from finrobot.artifact.store import ArtifactStore
from finrobot.engine.compute.dcf import calculate_dcf
from finrobot.engine.models.financial import DCFInputs
from finrobot.routes.compute import router as compute_router

_TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _frozen_inputs() -> DCFInputs:
    """A deterministic DCFInputs whose every field is fixed at generation time."""
    return DCFInputs(
        revenue_base=391_035_000_000.0,
        revenue_growth_rates=[0.08, 0.06, 0.05, 0.04, 0.03],
        ebitda_margin=0.33,
        capex_pct_revenue=0.03,
        nwc_pct_revenue=0.02,
        da_pct_revenue=0.03,
        tax_rate=0.21,
        risk_free_rate=0.042,
        beta=1.25,
        equity_risk_premium=0.05,
        cost_of_debt=0.045,
        debt_ratio=0.10,
        terminal_growth_rate=0.025,
        shares_outstanding=15_115_000_000.0,
        net_debt=41_458_000_000.0,
    )


def _make_dcf_artifact(
    *,
    artifact_id: str,
    type_: str,
    structured: dict[str, Any],
) -> Artifact:
    return Artifact(
        id=artifact_id,
        ticker="AAPL",
        type=type_,  # type: ignore[arg-type]
        inputs=ArtifactInputs(data_source="yfinance", data_fetched_at=_TS, raw_data={}),
        assumptions=ArtifactAssumptions(parameters={}),
        compute_version=ArtifactComputeVersion(version="0.1.0", formula_id="dcf_test"),
        outputs=ArtifactOutputs(structured=structured),
        meta=ArtifactMeta(created_at=_TS, source="test"),
    )


class _ExplodingDataLayer:
    """Any attribute access is a test failure — proves the endpoint never
    reaches for live data."""

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        raise AssertionError(
            f"What-if endpoint touched the data layer ({name}) — it must replay "
            "the frozen artifact, not re-fetch live financials."
        )


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(compute_router)
    app.state.artifact_store = ArtifactStore(base_dir=tmp_path / "artifacts")

    # If the endpoint ever calls request.app.state.deps.data_layer, blow up.
    class _Deps:
        data_layer = _ExplodingDataLayer()

    app.state.deps = _Deps()
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def store(app: FastAPI) -> ArtifactStore:
    return app.state.artifact_store  # type: ignore[return-value]


def _save(store: ArtifactStore, artifact: Artifact) -> None:
    asyncio.get_event_loop().run_until_complete(store.save(artifact))


def test_base_equals_persisted_implied_price(client: TestClient, store: ArtifactStore) -> None:
    inputs = _frozen_inputs()
    frozen = calculate_dcf(inputs)
    artifact = _make_dcf_artifact(
        artifact_id="art_eq",
        type_="equity_research",
        structured={"financial_modeling": frozen.model_dump(mode="json")},
    )
    _save(store, artifact)

    resp = client.post("/api/compute/artifacts/art_eq/what-if/dcf", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # BASE is the persisted number, exactly.
    assert body["base_implied_price"] == pytest.approx(frozen.implied_price)
    # No override ⇒ NEW replays the same frozen inputs ⇒ identical price.
    assert body["result"]["implied_price"] == pytest.approx(frozen.implied_price)


def test_wacc_override_matches_pure_calculate_dcf_on_frozen_inputs(
    client: TestClient, store: ArtifactStore
) -> None:
    inputs = _frozen_inputs()
    frozen = calculate_dcf(inputs)
    _save(
        store,
        _make_dcf_artifact(
            artifact_id="art_eq",
            type_="equity_research",
            structured={"financial_modeling": frozen.model_dump(mode="json")},
        ),
    )

    resp = client.post("/api/compute/artifacts/art_eq/what-if/dcf", json={"wacc_override": 0.12})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # The NEW price must equal the pure replay of the FROZEN inputs with only
    # WACC overridden — delta is attributable solely to the slider.
    expected = calculate_dcf(inputs, wacc_override=0.12)
    assert body["result"]["implied_price"] == pytest.approx(expected.implied_price)
    assert body["result"]["wacc"] == pytest.approx(0.12)
    # BASE is unchanged by the override.
    assert body["base_implied_price"] == pytest.approx(frozen.implied_price)
    # And it actually moved vs base (sanity: WACC up ⇒ value down).
    assert body["result"]["implied_price"] < body["base_implied_price"]


def test_growth_scale_override_matches_scaled_inputs(
    client: TestClient, store: ArtifactStore
) -> None:
    inputs = _frozen_inputs()
    frozen = calculate_dcf(inputs)
    _save(
        store,
        _make_dcf_artifact(
            artifact_id="art_eq",
            type_="equity_research",
            structured={"financial_modeling": frozen.model_dump(mode="json")},
        ),
    )

    resp = client.post(
        "/api/compute/artifacts/art_eq/what-if/dcf",
        json={"growth_scale_override": 0.1},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    scaled = inputs.model_copy(
        update={"revenue_growth_rates": [g * 1.1 for g in inputs.revenue_growth_rates]}
    )
    expected = calculate_dcf(scaled)
    assert body["result"]["implied_price"] == pytest.approx(expected.implied_price)
    assert body["result"]["implied_price"] > body["base_implied_price"]


def test_dcf_artifact_shape_is_replayable(client: TestClient, store: ArtifactStore) -> None:
    inputs = _frozen_inputs()
    frozen = calculate_dcf(inputs)
    # type="dcf" stores the DCFResult dump directly as structured.
    _save(
        store,
        _make_dcf_artifact(
            artifact_id="art_dcf",
            type_="dcf",
            structured=frozen.model_dump(mode="json"),
        ),
    )

    resp = client.post("/api/compute/artifacts/art_dcf/what-if/dcf", json={})
    assert resp.status_code == 200, resp.text
    assert resp.json()["base_implied_price"] == pytest.approx(frozen.implied_price)


def test_ic_memo_artifact_shape_is_replayable(client: TestClient, store: ArtifactStore) -> None:
    inputs = _frozen_inputs()
    frozen = calculate_dcf(inputs)
    # type="ic_memo" nests the DCFResult under structured["dcf_result"].
    _save(
        store,
        _make_dcf_artifact(
            artifact_id="art_ic",
            type_="ic_memo",
            structured={"dcf_result": frozen.model_dump(mode="json")},
        ),
    )

    resp = client.post("/api/compute/artifacts/art_ic/what-if/dcf", json={"tg_override": 0.02})
    assert resp.status_code == 200, resp.text
    expected = calculate_dcf(inputs, tg_override=0.02)
    assert resp.json()["result"]["implied_price"] == pytest.approx(expected.implied_price)


def test_missing_artifact_returns_404(client: TestClient) -> None:
    resp = client.post("/api/compute/artifacts/nope/what-if/dcf", json={})
    assert resp.status_code == 404


def test_artifact_without_dcf_returns_422(client: TestClient, store: ArtifactStore) -> None:
    # A comps-shaped artifact carries no DCFResult — not replayable.
    _save(
        store,
        _make_dcf_artifact(
            artifact_id="art_comps",
            type_="comps",
            structured={"peers": ["MSFT", "GOOGL"]},
        ),
    )
    resp = client.post("/api/compute/artifacts/art_comps/what-if/dcf", json={})
    assert resp.status_code == 422
