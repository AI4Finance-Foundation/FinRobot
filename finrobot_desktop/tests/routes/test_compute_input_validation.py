from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from finrobot.routes.compute import DcfSeedRequest, LboSeedRequest, router as compute_router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(compute_router)
    return TestClient(app)


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
