"""Tests for /api/sec-holdings status + manual refresh.

The 13F reverse-index cache is OFF by default and only populates via a
manual refresh or the auto-refresh flag. These endpoints back the desktop
Settings page that lets the user see cache state and trigger the build.

Scope here = ROUTE logic + refresh guards. The aiosqlite cache layer is
covered by tests/unit/test_sec_holdings_cache.py, so we stub ``cache_status``
to keep these tests off the DB (and off the network — a real refresh would
download a quarter of 13F-HR filings).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from finrobot.engine.data import sec_holdings_sync
from finrobot.routes import sec_holdings as sec_holdings_route
from finrobot.routes.sec_holdings import router as sec_holdings_router

_EMPTY_CACHE = {
    "populated": False,
    "row_count": 0,
    "latest_period_end": None,
    "distinct_tickers": 0,
    "expected_period_end": "2026-03-31",
    "stale": False,
}
_POPULATED_CACHE = {
    "populated": True,
    "row_count": 412_000,
    "latest_period_end": "2026-03-31",
    "distinct_tickers": 8_900,
    "expected_period_end": "2026-03-31",
    "stale": False,
}
_STALE_CACHE = {
    "populated": True,
    "row_count": 412_000,
    "latest_period_end": "2025-09-30",
    "distinct_tickers": 8_900,
    "expected_period_end": "2026-03-31",
    "stale": True,
}


@pytest.fixture(autouse=True)
def _reset_refresh_state():
    """Refresh state is a process-wide singleton — reset around each test."""
    sec_holdings_sync.reset_state_for_test()
    yield
    sec_holdings_sync.reset_state_for_test()


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(sec_holdings_router)
    app.state.background_tasks = []
    # Routes read the live runtime settings off app.state.deps.settings (kept
    # current by PUT /api/settings), mirroring the real server wiring.
    app.state.deps = SimpleNamespace(
        settings=SimpleNamespace(
            sec_user_agent="FinRobot admin@example.com", sec_holdings_auto_refresh=False
        )
    )
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _patch(
    app: FastAPI, monkeypatch, *, identity: str, auto_refresh: bool, cache: dict | None = None
) -> None:
    app.state.deps.settings = SimpleNamespace(
        sec_user_agent=identity, sec_holdings_auto_refresh=auto_refresh
    )

    async def _cache_status() -> dict:
        return cache if cache is not None else _EMPTY_CACHE

    monkeypatch.setattr(sec_holdings_route, "cache_status", _cache_status)


def test_status_empty_cache_reports_unpopulated(
    app: FastAPI, client: TestClient, monkeypatch
) -> None:
    _patch(app, monkeypatch, identity="Acme Research analyst@example.com", auto_refresh=False)
    resp = client.get("/api/sec-holdings/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["populated"] is False
    assert body["row_count"] == 0
    assert body["latest_period_end"] is None
    assert body["identity_configured"] is True
    assert body["auto_refresh"] is False
    assert body["refresh"]["status"] == "idle"


def test_status_populated_cache(app: FastAPI, client: TestClient, monkeypatch) -> None:
    _patch(
        app,
        monkeypatch,
        identity="Acme Research analyst@example.com",
        auto_refresh=True,
        cache=_POPULATED_CACHE,
    )
    body = client.get("/api/sec-holdings/status").json()
    assert body["populated"] is True
    assert body["row_count"] == 412_000
    assert body["latest_period_end"] == "2026-03-31"
    assert body["distinct_tickers"] == 8_900
    assert body["auto_refresh"] is True
    assert body["stale"] is False
    assert body["expected_period_end"] == "2026-03-31"


def test_status_surfaces_stale_cache(app: FastAPI, client: TestClient, monkeypatch) -> None:
    """A cache lagging behind the 13F filing deadline must read stale=True so
    the Settings page can warn instead of presenting an old quarter as current."""
    _patch(
        app,
        monkeypatch,
        identity="Acme Research analyst@example.com",
        auto_refresh=False,
        cache=_STALE_CACHE,
    )
    body = client.get("/api/sec-holdings/status").json()
    assert body["stale"] is True
    assert body["latest_period_end"] == "2025-09-30"
    assert body["expected_period_end"] == "2026-03-31"


def test_status_reports_identity_not_configured_for_placeholder(
    app: FastAPI, client: TestClient, monkeypatch
) -> None:
    """The config.py placeholder must read as identity_configured=False so the
    UI greys out the 立即同步 button instead of letting a doomed run start."""
    _patch(app, monkeypatch, identity="FinRobot admin@example.com", auto_refresh=False)
    body = client.get("/api/sec-holdings/status").json()
    assert body["identity_configured"] is False


def test_refresh_without_identity_returns_identity_missing(
    app: FastAPI, client: TestClient, monkeypatch
) -> None:
    """No valid SEC identity → refresh records the error code and spawns no
    work (no background task, no EDGAR call)."""
    _patch(app, monkeypatch, identity="FinRobot admin@example.com", auto_refresh=False)
    resp = client.post("/api/sec-holdings/refresh")
    assert resp.status_code == 200
    body = resp.json()
    assert body["refresh"]["status"] == "error"
    assert body["refresh"]["error"] == "identity_missing"


def test_refresh_idempotent_while_running(app: FastAPI, client: TestClient, monkeypatch) -> None:
    """A second refresh while one is in flight must not start a second parse."""
    _patch(app, monkeypatch, identity="Acme Research analyst@example.com", auto_refresh=False)
    # Simulate an in-flight run without touching the network.
    sec_holdings_sync._STATE.status = "running"
    sec_holdings_sync._STATE.period_end = "2026-03-31"
    resp = client.post("/api/sec-holdings/refresh")
    body = resp.json()
    assert body["refresh"]["status"] == "running"
    assert body["refresh"]["period_end"] == "2026-03-31"
