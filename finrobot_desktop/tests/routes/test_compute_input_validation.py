from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from finrobot.routes.compute import (
    DcfEquivalenceLineRequest,
    DcfSeedRequest,
    LboSeedRequest,
    router as compute_router,
)


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(compute_router)
    return TestClient(app)


def _dcf_payload() -> dict[str, object]:
    return {
        "revenue_base": 1_000_000_000,
        "revenue_growth_rates": [0.05, 0.04, 0.03, 0.03, 0.02],
        "ebitda_margin": 0.30,
        "capex_pct_revenue": 0.04,
        "nwc_pct_revenue": 0.02,
        "da_pct_revenue": 0.03,
        "tax_rate": 0.21,
        "risk_free_rate": 0.04,
        "beta": 1.1,
        "equity_risk_premium": 0.055,
        "cost_of_debt": 0.05,
        "debt_ratio": 0.20,
        "terminal_growth_rate": 0.025,
        "shares_outstanding": 100_000_000,
        "net_debt": 50_000_000,
    }


def test_compute_dcf_maps_gordon_model_value_error_to_422(client: TestClient) -> None:
    payload = _dcf_payload()
    payload.update(
        {
            "risk_free_rate": 0.0,
            "beta": 0.0,
            "equity_risk_premium": 0.0,
            "cost_of_debt": 0.0,
            "debt_ratio": 0.0,
            "terminal_growth_rate": 0.05,
        }
    )

    resp = client.post("/api/compute/dcf", json=payload)

    assert resp.status_code == 422, resp.text
    assert "Terminal growth rate" in resp.json()["detail"]


def test_dcf_seed_request_normalizes_ticker() -> None:
    assert DcfSeedRequest(ticker=" nvda ").ticker == "NVDA"


@pytest.mark.parametrize("ticker", ["苹果", "AAPL;DROP", "$"])
def test_dcf_seed_rejects_invalid_ticker(client: TestClient, ticker: str) -> None:
    resp = client.post("/api/compute/dcf-seed", json={"ticker": ticker})
    assert resp.status_code == 422, resp.text


def test_lbo_seed_request_normalizes_ticker() -> None:
    assert LboSeedRequest(ticker=" nvda ").ticker == "NVDA"


@pytest.mark.parametrize("ticker", ["苹果", "AAPL;DROP", "$"])
def test_lbo_seed_rejects_invalid_ticker(client: TestClient, ticker: str) -> None:
    resp = client.post("/api/compute/lbo-seed", json={"ticker": ticker})
    assert resp.status_code == 422, resp.text


def test_dcf_equivalence_line_request_normalizes_ticker() -> None:
    assert DcfEquivalenceLineRequest(ticker=" nvda ").ticker == "NVDA"


def test_compute_ticker_requests_accept_twelve_character_symbols() -> None:
    ticker = "ABCDEFGHIJKL"
    assert DcfSeedRequest(ticker=ticker).ticker == ticker
    assert LboSeedRequest(ticker=ticker).ticker == ticker
    assert DcfEquivalenceLineRequest(ticker=ticker).ticker == ticker


def test_dcf_equivalence_line_rejects_flat_growth_range() -> None:
    with pytest.raises(ValueError, match="growth_hi"):
        DcfEquivalenceLineRequest(ticker="NVDA", growth_lo=0.2, growth_hi=0.2)


def test_dcf_equivalence_line_rejects_reversed_growth_range(client: TestClient) -> None:
    resp = client.post(
        "/api/compute/dcf-equivalence-line",
        json={"ticker": "NVDA", "growth_lo": 0.5, "growth_hi": 0.2},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize("ticker", ["苹果", "AAPL;DROP", "$"])
def test_dcf_equivalence_line_rejects_invalid_ticker(client: TestClient, ticker: str) -> None:
    resp = client.post("/api/compute/dcf-equivalence-line", json={"ticker": ticker})
    assert resp.status_code == 422, resp.text
