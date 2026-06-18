"""Tests for /api/health/quotes-warmed.

The endpoint exposes the lifespan QuoteCache warmup state so the
landing-page frontend can render a skeleton instead of triggering a
cold dashboard fetch during the ~2s warmup window.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from finrobot.routes.health import router as health_router


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(health_router)
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_warmed_defaults_false_when_state_unset(client: TestClient) -> None:
    """Before the lifespan task initializes state, getattr default applies."""
    resp = client.get("/api/health/quotes-warmed")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "warmed": False,
        "studied_ticker_count": 0,
        "engine_ready": True,
        "agents_ready": True,
    }


def test_warmed_reflects_app_state(app: FastAPI, client: TestClient) -> None:
    """Once the lifespan task sets `warmed=True`, the endpoint reflects it."""
    app.state.quotes_warmed = True
    app.state.quotes_warmed_ticker_count = 7
    resp = client.get("/api/health/quotes-warmed")
    assert resp.status_code == 200
    assert resp.json() == {
        "warmed": True,
        "studied_ticker_count": 7,
        "engine_ready": True,
        "agents_ready": True,
    }


def test_warmed_after_empty_studied_set(app: FastAPI, client: TestClient) -> None:
    """First-install case: no studied tickers → warmup is instant + still
    reports warmed=True with count=0 so the frontend stops polling."""
    app.state.quotes_warmed = True
    app.state.quotes_warmed_ticker_count = 0
    resp = client.get("/api/health/quotes-warmed")
    assert resp.json() == {
        "warmed": True,
        "studied_ticker_count": 0,
        "engine_ready": True,
        "agents_ready": True,
    }


def test_readiness_flags_reflect_warming_state(app: FastAPI, client: TestClient) -> None:
    """Cold-start window: engine/agents flags read False so the frontend shows
    'starting engine' and treats live-data 503s as pending, not errors."""
    app.state.quotes_warmed = False
    app.state.quotes_warmed_ticker_count = 0
    app.state.engine_ready = False
    app.state.agents_ready = False
    body = client.get("/api/health/quotes-warmed").json()
    assert body["engine_ready"] is False
    assert body["agents_ready"] is False
