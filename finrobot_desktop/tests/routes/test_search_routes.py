"""Tests for GET /api/search/symbols (ticker autocomplete).

The global symbol index is seeded directly (monkeypatch) so these run with zero
network. Behaviour is pinned to the acceptance baseline in
``specs/research/股票搜索-typeahead自动补全-设计-2026-06-16.md`` §8.2.
"""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from finrobot.engine.data import symbol_index as si
from finrobot.routes.search import router as search_router

_FAKE_SEC = {
    "0": {"cik_str": 1, "ticker": "NVDA", "title": "NVIDIA CORP"},
    "1": {"cik_str": 2, "ticker": "AAPL", "title": "Apple Inc."},
    "2": {"cik_str": 3, "ticker": "AMAT", "title": "Applied Materials Inc"},
    "3": {"cik_str": 4, "ticker": "MSFT", "title": "MICROSOFT CORP"},
    "4": {"cik_str": 5, "ticker": "APP", "title": "AppLovin Corp"},
}


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setattr(si, "_INDEX", si.build_index_from_payload(_FAKE_SEC))
    app = FastAPI()
    app.include_router(search_router)
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _symbols(resp) -> list[str]:
    return [r["symbol"] for r in resp.json()["results"]]


def test_prefix_returns_megacap_first(client: TestClient) -> None:
    resp = client.get("/api/search/symbols", params={"q": "ap"})
    assert resp.status_code == 200
    assert _symbols(resp)[0] == "AAPL"


def test_exact_symbol(client: TestClient) -> None:
    resp = client.get("/api/search/symbols", params={"q": "AAPL"})
    assert _symbols(resp) == ["AAPL"]


def test_response_shape(client: TestClient) -> None:
    resp = client.get("/api/search/symbols", params={"q": "nvda"})
    body = resp.json()
    assert body["query"] == "nvda"
    assert body["results"] == [{"symbol": "NVDA", "name": "NVIDIA CORP"}]


def test_limit_param(client: TestClient) -> None:
    resp = client.get("/api/search/symbols", params={"q": "a", "limit": 2})
    assert len(resp.json()["results"]) == 2


def test_empty_query_returns_empty(client: TestClient) -> None:
    resp = client.get("/api/search/symbols", params={"q": ""})
    assert resp.status_code == 200
    assert resp.json()["results"] == []


def test_no_query_param_ok(client: TestClient) -> None:
    resp = client.get("/api/search/symbols")
    assert resp.status_code == 200
    assert resp.json() == {"query": "", "results": []}


@pytest.mark.parametrize("q", ["'; --", "苹果", "zzzz", "A" * 50])
def test_dirty_query_safe_empty_not_error(client: TestClient, q: str) -> None:
    resp = client.get("/api/search/symbols", params={"q": q})
    assert resp.status_code == 200  # never an error, just no matches
    assert resp.json()["results"] == []


def test_index_unavailable_degrades_to_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty / unwarmed index returns 200 + [] (the homepage box still works
    without suggestions) — never an error."""
    monkeypatch.setattr(si, "_INDEX", si.SymbolIndex([]))
    monkeypatch.setattr(si, "_next_retry_at", time.monotonic() + 1e6)  # in backoff: no refetch
    app = FastAPI()
    app.include_router(search_router)
    resp = TestClient(app).get("/api/search/symbols", params={"q": "ap"})
    assert resp.status_code == 200
    assert resp.json()["results"] == []
