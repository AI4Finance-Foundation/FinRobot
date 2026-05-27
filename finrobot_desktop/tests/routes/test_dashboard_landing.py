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
def _clear_caches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dashboard_mod._HIT_RATE_CACHE.clear()
    dashboard_mod._RECENT_CACHE.clear()
    # Isolate the QuoteCache L1/L2 per-test so the singleton does not bleed
    # quotes from previous tests' fixtures into the next assertion.
    from finagent import paths
    from finagent.engine.data import quote_batch

    monkeypatch.setattr(paths, "QUOTES_DB", tmp_path / "quotes.db")
    quote_batch.reset_quote_cache_singleton()


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


def test_recent_research_empty_store(client: TestClient) -> None:
    resp = client.get("/api/dashboard/recent-research")
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total_in_store"] == 0
    assert data["distinct_ticker_count"] == 0


def test_recent_research_rejects_bad_limit(client: TestClient) -> None:
    assert client.get("/api/dashboard/recent-research?limit=0").status_code == 400
    assert client.get("/api/dashboard/recent-research?limit=21").status_code == 400


def test_recent_research_rolls_up_same_ticker_into_one_card(
    client: TestClient,
    store: ArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three AAPL artifacts collapse into one card with 3 runs newest-first."""
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
    resp = client.get("/api/dashboard/recent-research?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_in_store"] == 3
    assert data["distinct_ticker_count"] == 1
    items = data["items"]
    assert len(items) == 1
    card = items[0]
    assert card["ticker"] == "AAPL"
    assert card["run_count"] == 3
    assert card["latest_signal"] in ("hit", "watching")
    # Rows are newest-first, each with its own verdict + artifact_id.
    rows = card["runs"]
    assert len(rows) == 3
    assert [r["artifact_id"] for r in rows] == ["art_AAPL_0", "art_AAPL_1", "art_AAPL_2"]
    assert all(r["verdict"] == "BUY" for r in rows)


def test_recent_research_caps_runs_per_card_and_reports_overflow(
    client: TestClient,
    store: ArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """7 runs for one ticker → 5 rows surfaced, run_count=7 for overflow footer."""
    _stub_yfinance(monkeypatch, {"AAPL": 115.0})
    for i in range(7):
        _save(
            store,
            _make_artifact(
                artifact_id=f"art_AAPL_{i}",
                ticker="AAPL",
                entry_price=100.0,
                target_price=130.0,
                verdict="BUY",
                days_ago=i,
            ),
        )
    resp = client.get("/api/dashboard/recent-research?limit=5")
    assert resp.status_code == 200
    card = resp.json()["items"][0]
    assert card["run_count"] == 7
    assert len(card["runs"]) == 5
    assert [r["artifact_id"] for r in card["runs"]] == [
        "art_AAPL_0", "art_AAPL_1", "art_AAPL_2", "art_AAPL_3", "art_AAPL_4",
    ]


def test_recent_research_top_n_distinct_tickers(
    client: TestClient,
    store: ArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three different tickers, limit=2 returns two most recently touched."""
    _stub_yfinance(monkeypatch, {"AAPL": 115.0, "MSFT": 115.0, "NVDA": 115.0})
    _save(store, _make_artifact(
        artifact_id="art_AAPL", ticker="AAPL",
        entry_price=100.0, target_price=130.0, verdict="BUY", days_ago=15,
    ))
    _save(store, _make_artifact(
        artifact_id="art_NVDA", ticker="NVDA",
        entry_price=100.0, target_price=130.0, verdict="BUY", days_ago=5,
    ))
    _save(store, _make_artifact(
        artifact_id="art_MSFT", ticker="MSFT",
        entry_price=100.0, target_price=130.0, verdict="BUY", days_ago=1,
    ))
    resp = client.get("/api/dashboard/recent-research?limit=2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["distinct_ticker_count"] == 3
    assert [c["ticker"] for c in data["items"]] == ["MSFT", "NVDA"]


# ─────────────────────────────────────────────────────────────────────────────
# Regression guards: routes must not N+1-read the full artifact for verdict
# ─────────────────────────────────────────────────────────────────────────────


def test_hit_rate_does_not_read_full_artifact_for_verdict(
    client: TestClient,
    store: ArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`ArtifactSummary.verdict` is populated at save time, so the hit-rate
    aggregation must use the summary column instead of reloading each full
    artifact JSON. Pre-2026-05-23 the route fanned out ``store.get(s.id)``
    per summary — that was the dominant chunk of landing cold-start.
    """
    _stub_yfinance(monkeypatch, {"AAPL": 128.0, "MSFT": 60.0})
    for tkr in ("AAPL", "MSFT"):
        _save(
            store,
            _make_artifact(
                artifact_id=f"art_{tkr}",
                ticker=tkr,
                entry_price=100.0,
                target_price=130.0,
                verdict="BUY",
                days_ago=30,
            ),
        )
    calls: list[str] = []
    original_get = store._impl.get  # bypass __getattr__ shim

    async def counting_get(artifact_id: str):  # type: ignore[no-untyped-def]
        calls.append(artifact_id)
        return await original_get(artifact_id)

    store._impl.get = counting_get  # type: ignore[assignment]

    resp = client.get("/api/dashboard/hit-rate")
    assert resp.status_code == 200
    assert calls == [], f"hit-rate called store.get {len(calls)} times, expected 0"


def test_hit_rate_does_not_500_when_quote_fetch_explodes(
    client: TestClient,
    store: ArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: a broken QuoteCache must not take the landing banner down.

    Quotes are decorative for hit-rate (n_total still counts, only n_hit
    needs the live price). Any exception from the batch call falls back
    to None prices instead of a 500.
    """
    _stub_yfinance(monkeypatch, {"AAPL": 128.0})
    _save(
        store,
        _make_artifact(
            artifact_id="art_AAPL",
            ticker="AAPL",
            entry_price=100.0,
            target_price=130.0,
            verdict="BUY",
            days_ago=30,
        ),
    )

    async def explode(_tickers):  # type: ignore[no-untyped-def]
        raise RuntimeError("aiosqlite worker thread died")

    # The route imports fetch_quotes_batch_cached *inside* the handler, so
    # the only patch that lands is on the source module.
    monkeypatch.setattr(
        "finagent.engine.data.quote_batch.fetch_quotes_batch_cached", explode
    )

    resp = client.get("/api/dashboard/hit-rate")
    # Key guarantee: no 500. Without live prices the aggregator can't
    # classify any signal, so all buckets degrade to zeros + null hit-rate.
    # UI already handles that branch ("样本不足" hint) — much better than a
    # red error screen.
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["overall"]["hit_rate"] is None
    assert set(data["by_verdict"].keys()) == {"BUY", "HOLD", "SELL"}


def test_recent_research_does_not_500_when_quote_fetch_explodes(
    client: TestClient,
    store: ArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same guarantee for the recent-research drawer endpoint."""
    _stub_yfinance(monkeypatch, {"AAPL": 128.0})
    _save(
        store,
        _make_artifact(
            artifact_id="art_AAPL",
            ticker="AAPL",
            entry_price=100.0,
            target_price=130.0,
            verdict="BUY",
            days_ago=30,
        ),
    )

    async def explode(_tickers):  # type: ignore[no-untyped-def]
        raise RuntimeError("aiosqlite worker thread died")

    monkeypatch.setattr(
        "finagent.engine.data.quote_batch.fetch_quotes_batch_cached", explode
    )

    resp = client.get("/api/dashboard/recent-research?limit=5")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["distinct_ticker_count"] == 1
    assert len(data["items"]) == 1


def test_recent_research_does_not_read_full_artifact_for_verdict(
    client: TestClient,
    store: ArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same guarantee for the recent-research drawer endpoint."""
    _stub_yfinance(monkeypatch, {"AAPL": 115.0})
    for i in range(3):
        _save(
            store,
            _make_artifact(
                artifact_id=f"art_AAPL_{i}",
                ticker="AAPL",
                entry_price=100.0,
                target_price=130.0,
                verdict="BUY",
                days_ago=i,
            ),
        )
    calls: list[str] = []
    original_get = store._impl.get

    async def counting_get(artifact_id: str):  # type: ignore[no-untyped-def]
        calls.append(artifact_id)
        return await original_get(artifact_id)

    store._impl.get = counting_get  # type: ignore[assignment]

    resp = client.get("/api/dashboard/recent-research?limit=5")
    assert resp.status_code == 200
    assert calls == [], f"recent-research called store.get {len(calls)} times, expected 0"
