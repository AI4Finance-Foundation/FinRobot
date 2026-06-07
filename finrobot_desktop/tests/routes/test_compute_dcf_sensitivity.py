"""Tests for POST /api/compute/dcf-sensitivity.

The endpoint runs a synchronous O(W×G×N) nested loop. Two guarantees matter:

- The grid is BOUNDED: wacc_range / tg_range each cap at 25 entries
  (build_sensitivity_ranges produces ≤5/axis, so 25/axis fits every legit UI
  call). An oversized range (e.g. 5000×5000 = 25M cells) that would block the
  asyncio event loop must be rejected at validation with 422 — never executed.
- The happy path still returns a correctly-shaped grid, and the compute is
  offloaded to a thread so it can't stall other in-flight HTTP / SSE polling.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from finrobot.engine.models.financial import DCFInputs
from finrobot.routes.compute import DcfSensitivityRequest, router as compute_router


def _inputs() -> DCFInputs:
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


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(compute_router)
    return TestClient(app)


def test_happy_path_returns_grid(client: TestClient) -> None:
    wacc_range = [0.08, 0.09, 0.10, 0.11, 0.12]
    tg_range = [0.015, 0.020, 0.025, 0.030, 0.035]
    resp = client.post(
        "/api/compute/dcf-sensitivity",
        json={
            "inputs": _inputs().model_dump(mode="json"),
            "wacc_range": wacc_range,
            "tg_range": tg_range,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["wacc_values"] == pytest.approx(wacc_range)
    assert body["tg_values"] == pytest.approx(tg_range)
    # One row per WACC, one column per terminal-growth.
    assert len(body["implied_prices"]) == len(wacc_range)
    assert all(len(row) == len(tg_range) for row in body["implied_prices"])


def test_max_25_per_axis_is_accepted(client: TestClient) -> None:
    # 25 is the hard cap — the largest legit grid must still pass validation.
    rng = [0.05 + i * 0.001 for i in range(25)]
    resp = client.post(
        "/api/compute/dcf-sensitivity",
        json={
            "inputs": _inputs().model_dump(mode="json"),
            "wacc_range": rng,
            "tg_range": rng,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["implied_prices"]) == 25
    assert all(len(row) == 25 for row in body["implied_prices"])


def test_oversized_wacc_range_is_rejected(client: TestClient) -> None:
    # 26 > 25 → reject at validation; the 25M-cell event-loop stall never runs.
    rng = [0.05 + i * 0.0001 for i in range(26)]
    resp = client.post(
        "/api/compute/dcf-sensitivity",
        json={
            "inputs": _inputs().model_dump(mode="json"),
            "wacc_range": rng,
            "tg_range": [0.02, 0.025],
        },
    )
    assert resp.status_code == 422, resp.text


def test_oversized_tg_range_is_rejected(client: TestClient) -> None:
    rng = [0.01 + i * 0.0001 for i in range(26)]
    resp = client.post(
        "/api/compute/dcf-sensitivity",
        json={
            "inputs": _inputs().model_dump(mode="json"),
            "wacc_range": [0.09, 0.10],
            "tg_range": rng,
        },
    )
    assert resp.status_code == 422, resp.text


def test_empty_range_is_rejected(client: TestClient) -> None:
    # min_length=1 still holds — an empty axis is meaningless.
    resp = client.post(
        "/api/compute/dcf-sensitivity",
        json={
            "inputs": _inputs().model_dump(mode="json"),
            "wacc_range": [],
            "tg_range": [0.02],
        },
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize(
    ("wacc_range", "tg_range"),
    [
        ([float("nan")], [0.02]),
        ([float("inf")], [0.02]),
        ([0.09], [float("-inf")]),
        ([0.09], [float("nan")]),
    ],
)
def test_nonfinite_axis_values_are_rejected(wacc_range: list[float], tg_range: list[float]) -> None:
    with pytest.raises(ValueError):
        DcfSensitivityRequest(inputs=_inputs(), wacc_range=wacc_range, tg_range=tg_range)


@pytest.mark.parametrize(
    ("wacc_range", "tg_range"),
    [
        ([-0.01], [0.02]),
        ([0.51], [0.02]),
        ([0.09], [-0.06]),
        ([0.09], [0.11]),
    ],
)
def test_axis_values_outside_contract_are_rejected(
    client: TestClient, wacc_range: list[float], tg_range: list[float]
) -> None:
    resp = client.post(
        "/api/compute/dcf-sensitivity",
        json={
            "inputs": _inputs().model_dump(mode="json"),
            "wacc_range": wacc_range,
            "tg_range": tg_range,
        },
    )
    assert resp.status_code == 422, resp.text
