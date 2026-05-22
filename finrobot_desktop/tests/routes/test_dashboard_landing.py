"""Integration tests for /api/dashboard/hit-rate + /api/dashboard/recent-research.

yfinance is monkey-patched so the tests don't hit the network. ArtifactStore
runs against a real on-disk temp dir so we exercise the actual summary
indexing path.
"""

from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from finagent.artifact.models import (
    Artifact,
    ArtifactAssumptions,
    ArtifactComputeVersion,
    ArtifactInputs,
    ArtifactMeta,
    ArtifactOutputs,
)
from finagent.artifact.store import ArtifactStore
from finagent.routes.dashboard import router as dashboard_router

# Clear module-level caches between tests; otherwise the first run's 60s
# TTL bleeds into subsequent runs and they see stale data.
from finagent.routes import dashboard as dashboard_mod

UTC = timezone.utc
NOW = datetime(2026, 5, 22, 12, 0, 0, tzinfo=UTC)


def _stub_yfinance(monkeypatch: pytest.MonkeyPatch, prices: dict[str, float]) -> None:
    fake = types.ModuleType("yfinance")

    class _Info:
        def __init__(self, p: float | None) -> None:
            self.last_price = p

    class _Ticker:
        def __init__(self, sym: str) -> None:
            self.fast_info = _Info(prices.get(sym.upper()))

    class _Tickers:
        def __init__(self, joined: str) -> None:
            self.tickers = {s.upper(): _Ticker(s) for s in joined.split()}

    fake.Ticker = _Ticker  # type: ignore[attr-defined]
    fake.Tickers = _Tickers  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", fake)


def _make_artifact(
    *,
    artifact_id: str,
    ticker: str,
    entry_price: float,
    target_price: float,
    verdict: str,
    days_ago: int,
) -> Artifact:
    ts = NOW - timedelta(days=days_ago)
    return Artifact(
        id=artifact_id,
        ticker=ticker,
        type="equity_research",
        inputs=ArtifactInputs(
            data_source="yfinance",
            data_fetched_at=ts,
            raw_data={"market": {"current_price": entry_price}},
        ),
        assumptions=ArtifactAssumptions(parameters={}),
        compute_version=ArtifactComputeVersion(
            version="0.1.0", git_commit="abcd1234", formula_id="equity_v1"
        ),
        outputs=ArtifactOutputs(
            structured={
                "thesis": {
                    "price_target": target_price,
                    "recommendation": verdict,
                }
            },
            summary_text=f"{verdict} thesis on {ticker}",
            warnings=[],
        ),
        meta=ArtifactMeta(
            created_at=ts,
            source="pipeline:equity_research",
            user_id="local",
        ),
    )


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(dashboard_router)
    store = ArtifactStore(base_dir=tmp_path / "artifacts")
    app.state.deps = SimpleNamespace(artifact_store=store)
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def store(app: FastAPI) -> ArtifactStore:
    return app.state.deps.artifact_store  # type: ignore[return-value]


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    dashboard_mod._HIT_RATE_CACHE.clear()
    dashboard_mod._RECENT_CACHE.clear()


def _save(store: ArtifactStore, art: Artifact) -> None:
    """Sync wrapper for ArtifactStore.save inside test bodies.

    Uses a fresh event loop per call so that earlier pipeline tests
    closing their own loop (or installing a custom policy) don't leak
    state into the dashboard route assertions.
    """
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(store.save(art))
    finally:
        loop.close()


def test_hit_rate_empty_store_returns_null_hit_rate(client: TestClient) -> None:
    resp = client.get("/api/dashboard/hit-rate")
    assert resp.status_code == 200
    data = resp.json()
    assert data["window"] == "all"
    assert data["overall"]["n_total"] == 0
    assert data["overall"]["hit_rate"] is None
    assert set(data["by_verdict"].keys()) == {"BUY", "HOLD", "SELL"}


def test_hit_rate_rejects_bad_window(client: TestClient) -> None:
    resp = client.get("/api/dashboard/hit-rate?window=7d")
    assert resp.status_code == 400


def test_hit_rate_rejects_bad_verdict_filter(client: TestClient) -> None:
    resp = client.get("/api/dashboard/hit-rate?verdict_filter=UNCLEAR")
    assert resp.status_code == 400


def test_hit_rate_aggregates_real_artifacts(
    client: TestClient,
    store: ArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_yfinance(monkeypatch, {"AAPL": 128.0, "MSFT": 60.0})
    _save(
        store,
        _make_artifact(
            artifact_id="art_hit_AAPL",
            ticker="AAPL",
            entry_price=100.0,
            target_price=130.0,
            verdict="BUY",
            days_ago=30,
        ),
    )
    _save(
        store,
        _make_artifact(
            artifact_id="art_fail_MSFT",
            ticker="MSFT",
            entry_price=100.0,
            target_price=130.0,
            verdict="BUY",
            days_ago=30,
        ),
    )
    resp = client.get("/api/dashboard/hit-rate")
    assert resp.status_code == 200
    data = resp.json()
    assert data["overall"]["n_total"] == 2
    assert data["overall"]["n_closed"] == 2
    assert data["overall"]["n_hit"] == 1
    assert data["overall"]["hit_rate"] == 0.5
    assert data["by_verdict"]["BUY"]["hit_rate"] == 0.5
    assert data["by_verdict"]["HOLD"]["hit_rate"] is None


def test_hit_rate_verdict_filter_narrows_overall(
    client: TestClient,
    store: ArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_yfinance(monkeypatch, {"AAPL": 128.0, "MSFT": 128.0})
    _save(
        store,
        _make_artifact(
            artifact_id="art_BUY_AAPL",
            ticker="AAPL",
            entry_price=100.0,
            target_price=130.0,
            verdict="BUY",
            days_ago=30,
        ),
    )
    _save(
        store,
        _make_artifact(
            artifact_id="art_HOLD_MSFT",
            ticker="MSFT",
            entry_price=100.0,
            target_price=130.0,
            verdict="HOLD",
            days_ago=30,
        ),
    )
    resp = client.get("/api/dashboard/hit-rate?verdict_filter=BUY")
    assert resp.status_code == 200
    data = resp.json()
    assert data["overall"]["n_total"] == 1
    assert data["by_verdict"]["BUY"]["n_total"] == 1
    assert data["by_verdict"]["HOLD"]["n_total"] == 0


def test_recent_research_empty_store(client: TestClient) -> None:
    resp = client.get("/api/dashboard/recent-research")
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total_in_store"] == 0


def test_recent_research_rejects_bad_limit(client: TestClient) -> None:
    assert client.get("/api/dashboard/recent-research?limit=0").status_code == 400
    assert client.get("/api/dashboard/recent-research?limit=21").status_code == 400


def test_recent_research_returns_top_n_by_date(
    client: TestClient,
    store: ArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_yfinance(monkeypatch, {"AAPL": 115.0})
    for i, days in enumerate([1, 5, 10]):
        _save(
            store,
            _make_artifact(
                artifact_id=f"art_AAPL_{i}",
                ticker="AAPL",
                entry_price=100.0,
                target_price=130.0,
                verdict="BUY",
                days_ago=days,
            ),
        )
    resp = client.get("/api/dashboard/recent-research?limit=2")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    assert items[0]["artifact_id"] == "art_AAPL_0"  # most recent
    assert items[0]["signal"] in ("hit", "watching")
    assert items[0]["delta_to_target_pct"] == pytest.approx(0.5)
    assert "ago" in items[0]["age_label"] or items[0]["age_label"] == "just now"
