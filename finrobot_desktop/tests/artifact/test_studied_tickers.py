"""Unit tests for GET /api/artifacts/studied-tickers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from finagent.artifact.models import Artifact
from finagent.artifact.store import ArtifactStore
from finagent.routes.artifacts import router as artifacts_router
from tests.artifact.conftest import _make_artifact

UTC = timezone.utc


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(artifacts_router)
    store = ArtifactStore(base_dir=tmp_path / "artifacts")
    app.state.artifact_store = store
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def store(app: FastAPI) -> ArtifactStore:
    return app.state.artifact_store  # type: ignore[return-value]


def _save(store: ArtifactStore, artifact: Artifact) -> None:
    """Sync save using a fresh event loop — survives pytest-asyncio ordering."""
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(store.save(artifact))
    finally:
        loop.close()


def test_studied_tickers_empty_store_returns_empty_list(client: TestClient) -> None:
    resp = client.get("/api/artifacts/studied-tickers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []


def test_studied_tickers_groups_multiple_runs_per_ticker(
    client: TestClient, store: ArtifactStore
) -> None:
    """3 AAPL runs + 1 MSFT run → 2 rows, AAPL run_count=3."""
    base = datetime(2026, 5, 1, tzinfo=UTC)
    _save(store, _make_artifact(id="art_AAPL_dcf", ticker="AAPL", type="dcf", created_at=base))
    _save(store, _make_artifact(id="art_AAPL_lbo", ticker="AAPL", type="lbo", created_at=base + timedelta(days=1)))
    _save(store, _make_artifact(id="art_AAPL_eq", ticker="AAPL", type="equity_research", created_at=base + timedelta(days=5)))
    _save(store, _make_artifact(id="art_MSFT_eq", ticker="MSFT", type="equity_research", created_at=base + timedelta(days=2)))

    resp = client.get("/api/artifacts/studied-tickers")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2

    aapl = next(i for i in items if i["ticker"] == "AAPL")
    assert aapl["run_count"] == 3
    assert aapl["latest_type"] == "equity_research"  # newest
    assert aapl["latest_artifact_id"] == "art_AAPL_eq"
    assert set(aapl["types"]) == {"dcf", "lbo", "equity_research"}


def test_studied_tickers_sorted_by_latest_activity(
    client: TestClient, store: ArtifactStore
) -> None:
    base = datetime(2026, 5, 1, tzinfo=UTC)
    _save(store, _make_artifact(id="art_AAPL", ticker="AAPL", type="dcf", created_at=base))
    _save(store, _make_artifact(id="art_MSFT", ticker="MSFT", type="dcf", created_at=base + timedelta(days=10)))
    _save(store, _make_artifact(id="art_NVDA", ticker="NVDA", type="dcf", created_at=base + timedelta(days=5)))

    resp = client.get("/api/artifacts/studied-tickers")
    items = resp.json()["items"]
    assert [i["ticker"] for i in items] == ["MSFT", "NVDA", "AAPL"]


def test_studied_tickers_limit_caps_results(
    client: TestClient, store: ArtifactStore
) -> None:
    base = datetime(2026, 5, 1, tzinfo=UTC)
    for i, t in enumerate(["AAPL", "MSFT", "NVDA"]):
        _save(store, _make_artifact(id=f"art_{t}", ticker=t, type="dcf", created_at=base + timedelta(days=i)))

    resp = client.get("/api/artifacts/studied-tickers?limit=2")
    items = resp.json()["items"]
    assert len(items) == 2


def test_studied_tickers_skips_cross_ticker_artifacts(
    client: TestClient, store: ArtifactStore
) -> None:
    """Peer research artifacts have ticker=None — shouldn't crash the grouper."""
    _save(store, _make_artifact(id="art_peer", ticker=None, type="peer_research", created_at=datetime(2026, 5, 5, tzinfo=UTC)))
    _save(store, _make_artifact(id="art_AAPL", ticker="AAPL", type="dcf", created_at=datetime(2026, 5, 6, tzinfo=UTC)))

    resp = client.get("/api/artifacts/studied-tickers")
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["ticker"] == "AAPL"
