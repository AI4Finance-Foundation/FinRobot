"""Integration tests for /api/dashboard/hit-rate + /api/dashboard/recent-research.

Hit-rate cold-fetches quotes through a fake ``deps.data_layer.fetch_quote``
(门一 Step 3) so the tests don't hit the network. The recent-research strip is
cache-only — it reads pre-warmed L2 rows seeded by ``_warm_quote_cache`` and
never fans out to a provider. ArtifactStore runs against a real on-disk temp
dir so we exercise the actual summary indexing path.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

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
from finrobot.engine.data.interface import DataResult, ProviderError
from finrobot.engine.data.types import DataType
from finrobot.routes.dashboard import router as dashboard_router

# Clear module-level caches between tests; otherwise the first run's 60s
# TTL bleeds into subsequent runs and they see stale data.
from finrobot.routes import dashboard as dashboard_mod

UTC = timezone.utc
NOW = datetime(2026, 5, 22, 12, 0, 0, tzinfo=UTC)

# Per-test quote prices the fake DataLayer serves; set via _set_quotes, cleared
# by the autouse _clear_caches fixture.
_QUOTE_PRICES: dict[str, float] = {}


def _set_quotes(prices: dict[str, float]) -> None:
    """Set the prices the fake ``DataLayer.fetch_quote`` returns this test.

    Only the hit-rate endpoint cold-fetches through this fake; the
    recent-research strip is cache-only and reads pre-warmed L2 rows via
    :func:`_warm_quote_cache` instead.
    """
    _QUOTE_PRICES.clear()
    _QUOTE_PRICES.update({k.upper(): v for k, v in prices.items()})


def _warm_quote_cache(db_path: Path, prices: dict[str, float]) -> None:
    """Seed fresh L2 QuoteCache rows so the cache-only recent-research endpoint
    can light its signal lamps.

    Mirrors the production post-warmup state: the strip endpoint never
    cold-fetches, so a fresh row here is the only way a lamp resolves. Written
    synchronously via sqlite3 (no asyncio) to dodge cross-event-loop entangle-
    ment with the QuoteCache aiosqlite worker. Must run AFTER ``_clear_caches``
    has rebound ``paths.QUOTES_DB`` to this ``db_path``.
    """
    import sqlite3
    import time

    from finrobot.engine.data.quote_cache import _CREATE_TABLE

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_CREATE_TABLE)
        now = time.time()
        conn.executemany(
            "INSERT OR REPLACE INTO quotes_cache(ticker, last_price, fetched_at) VALUES (?, ?, ?)",
            [(k.upper(), v, now) for k, v in prices.items()],
        )
        conn.commit()
    finally:
        conn.close()


class _FakeQuoteLayer:
    """Minimal DataLayer stand-in exposing only ``fetch_quote``."""

    async def fetch_quote(self, ticker: str) -> DataResult:
        price = _QUOTE_PRICES.get(ticker.upper())
        if price is None:
            raise ProviderError(f"no quote for {ticker}")
        return DataResult(
            data={"price": price},
            provider="fake",
            ticker=ticker,
            data_type=DataType.QUOTE,
            timestamp=datetime.now(tz=UTC),
        )


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
    app.state.deps = SimpleNamespace(artifact_store=store, data_layer=_FakeQuoteLayer())
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
    _QUOTE_PRICES.clear()
    # Isolate the QuoteCache L1/L2 per-test so the singleton does not bleed
    # quotes from previous tests' fixtures into the next assertion.
    from finrobot import paths
    from finrobot.engine.data import quote_batch

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
    _set_quotes({"AAPL": 128.0, "MSFT": 60.0})
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


def test_hit_rate_scopes_to_group_tickers(
    client: TestClient,
    store: ArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """?tickers=… scopes the track record to a coverage group (BUG-055): a
    3-name group must not fold in every historical ticker. Empty value → the
    empty set → null buckets, NOT the global stats."""
    _set_quotes({"AAPL": 128.0, "MSFT": 60.0})
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
    _save(
        store,
        _make_artifact(
            artifact_id="art_MSFT",
            ticker="MSFT",
            entry_price=100.0,
            target_price=130.0,
            verdict="BUY",
            days_ago=30,
        ),
    )
    # Scoped to AAPL only → its single (hit) sample, not the global 0.5.
    scoped = client.get("/api/dashboard/hit-rate?tickers=AAPL").json()
    assert scoped["overall"]["n_total"] == 1
    assert scoped["overall"]["hit_rate"] == 1.0
    # Empty group → empty set → null, distinct from global.
    empty = client.get("/api/dashboard/hit-rate?tickers=").json()
    assert empty["overall"]["n_total"] == 0
    assert empty["overall"]["hit_rate"] is None


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
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three AAPL artifacts collapse into one card with 3 runs newest-first."""
    # Cache-only endpoint: pre-warm L2 so the latest run's signal lamp resolves
    # (entry=100, target=130, current=115 → "watching").
    _warm_quote_cache(tmp_path / "quotes.db", {"AAPL": 115.0})
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
    # No quote pre-warm needed: this asserts row structure, not the lamp.
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
        "art_AAPL_0",
        "art_AAPL_1",
        "art_AAPL_2",
        "art_AAPL_3",
        "art_AAPL_4",
    ]


def test_recent_research_top_n_distinct_tickers(
    client: TestClient,
    store: ArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three different tickers, limit=2 returns two most recently touched."""
    # No quote pre-warm needed: this asserts top-N ordering, not the lamp.
    _save(
        store,
        _make_artifact(
            artifact_id="art_AAPL",
            ticker="AAPL",
            entry_price=100.0,
            target_price=130.0,
            verdict="BUY",
            days_ago=15,
        ),
    )
    _save(
        store,
        _make_artifact(
            artifact_id="art_NVDA",
            ticker="NVDA",
            entry_price=100.0,
            target_price=130.0,
            verdict="BUY",
            days_ago=5,
        ),
    )
    _save(
        store,
        _make_artifact(
            artifact_id="art_MSFT",
            ticker="MSFT",
            entry_price=100.0,
            target_price=130.0,
            verdict="BUY",
            days_ago=1,
        ),
    )
    resp = client.get("/api/dashboard/recent-research?limit=2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["distinct_ticker_count"] == 3
    assert [c["ticker"] for c in data["items"]] == ["MSFT", "NVDA"]


# ─────────────────────────────────────────────────────────────────────────────
# Honest totals past the 500 sample cap (BUG-20260602-031)
# ─────────────────────────────────────────────────────────────────────────────


def test_store_count_aggregates_are_uncapped(
    store: ArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``count`` / ``distinct_ticker_count`` return true totals, not a 500 page.

    Seeds 501 artifacts across 2 tickers and asserts the aggregate queries see
    all 501 / 2 — the value the dashboard header must report.
    """
    import asyncio

    async def seed_and_count() -> tuple[int, int, int]:
        for i in range(501):
            await store.save(
                _make_artifact(
                    artifact_id=f"art_{i:04d}",
                    ticker="AAPL" if i % 2 == 0 else "MSFT",
                    entry_price=100.0,
                    target_price=130.0,
                    verdict="BUY",
                    days_ago=i % 90,
                )
            )
        capped = await store.list_by_ticker(ticker=None, include_archived=False, limit=500)
        total = await store.count(include_archived=False)
        distinct = await store.distinct_ticker_count(include_archived=False)
        return len(capped), total, distinct

    loop = asyncio.new_event_loop()
    try:
        capped_len, total, distinct = loop.run_until_complete(seed_and_count())
    finally:
        loop.close()

    assert capped_len == 500  # the page is capped …
    assert total == 501  # … but the aggregate is honest
    assert distinct == 2


def test_recent_research_total_reflects_true_store_past_cap(
    client: TestClient,
    store: ArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """recent-research header reports the real store totals, not len(summaries).

    A 500-row page would silently cap ``total_in_store`` at 500 once the store
    grows; monkeypatch the aggregate queries to a >500 store and assert the
    response carries the true numbers through.
    """
    # One real artifact so the strip has a card to render.
    _save(
        store,
        _make_artifact(
            artifact_id="art_AAPL",
            ticker="AAPL",
            entry_price=100.0,
            target_price=130.0,
            verdict="BUY",
            days_ago=1,
        ),
    )

    async def fake_count(
        *,
        include_archived: bool = False,
        tickers: set[str] | None = None,
        created_after: object | None = None,
    ) -> int:
        return 1234

    async def fake_distinct(*, include_archived: bool = False) -> int:
        return 87

    monkeypatch.setattr(store, "count", fake_count)
    monkeypatch.setattr(store, "distinct_ticker_count", fake_distinct)

    resp = client.get("/api/dashboard/recent-research?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_in_store"] == 1234
    assert data["distinct_ticker_count"] == 87


def test_hit_rate_discloses_sampling_past_cap(
    client: TestClient,
    store: ArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``is_sampled`` flips True once the IN-SCOPE/IN-WINDOW count exceeds the cap."""
    _set_quotes({"AAPL": 128.0})
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

    # Below the cap: not sampled.
    not_sampled = client.get("/api/dashboard/hit-rate").json()
    assert not_sampled["is_sampled"] is False
    assert not_sampled["sample_size"] == dashboard_mod._HIT_RATE_SAMPLE_CAP

    # Bust the cache, then simulate a scoped+windowed population beyond the cap.
    dashboard_mod._HIT_RATE_CACHE.clear()

    async def fake_count(
        *,
        include_archived: bool = False,
        tickers: set[str] | None = None,
        created_after: object | None = None,
    ) -> int:
        return dashboard_mod._HIT_RATE_SAMPLE_CAP + 1

    monkeypatch.setattr(store, "count", fake_count)

    sampled = client.get("/api/dashboard/hit-rate").json()
    assert sampled["is_sampled"] is True
    assert sampled["sample_size"] == dashboard_mod._HIT_RATE_SAMPLE_CAP


def test_hit_rate_is_sampled_uses_scoped_windowed_count_not_global(
    client: TestClient,
    store: ArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BUG-039: a fully-captured window/scope must NOT be labeled sampled even
    when the GLOBAL store dwarfs the cap.

    The honesty flag answers "did the cap drop in-scope/in-window data?" — so it
    must compare against the SAME population the buckets describe (scoped to the
    requested tickers AND cut to the window), not the all-time global COUNT(*).
    A 30d window with 40 in-window artifacts out of 700 in store is fully
    captured → is_sampled=False.
    """
    _set_quotes({"AAPL": 128.0})
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

    seen: list[dict[str, object]] = []

    async def fake_count(
        *,
        include_archived: bool = False,
        tickers: set[str] | None = None,
        created_after: object | None = None,
    ) -> int:
        seen.append({"tickers": tickers, "created_after": created_after})
        # Global all-time (no scope, no window) is huge; the scoped+windowed
        # population is well under the cap. The OLD code read the global count
        # and would wrongly report is_sampled=True.
        if tickers is None and created_after is None:
            return dashboard_mod._HIT_RATE_SAMPLE_CAP + 200
        return 40

    monkeypatch.setattr(store, "count", fake_count)

    # 30d window scoped to a group: fully captured → honest is_sampled=False.
    scoped_windowed = client.get("/api/dashboard/hit-rate?window=30d&tickers=AAPL").json()
    assert scoped_windowed["is_sampled"] is False
    # The route must have asked count() the scoped+windowed question.
    assert seen, "store.count was never called"
    last = seen[-1]
    assert last["tickers"] == {"AAPL"}
    assert last["created_after"] is not None  # 30d → a cutoff was applied


def test_hit_rate_count_signature_threads_window_and_scope(
    store: ArtifactStore,
) -> None:
    """BUG-039: ``ArtifactStore.count`` honors ``tickers`` + ``created_after`` so
    the route can ask for the scoped+windowed population. Empty ticker set → 0.
    """
    import asyncio

    _save(
        store,
        _make_artifact(
            artifact_id="art_old_AAPL",
            ticker="AAPL",
            entry_price=100.0,
            target_price=130.0,
            verdict="BUY",
            days_ago=120,
        ),
    )
    _save(
        store,
        _make_artifact(
            artifact_id="art_new_MSFT",
            ticker="MSFT",
            entry_price=100.0,
            target_price=130.0,
            verdict="BUY",
            days_ago=2,
        ),
    )

    async def checks() -> None:
        # Unscoped, no window → both rows.
        assert await store.count(include_archived=False) == 2
        # Ticker scope → only MSFT.
        assert await store.count(include_archived=False, tickers={"MSFT"}) == 1
        # Empty scope → 0 (an empty group has no track record).
        assert await store.count(include_archived=False, tickers=set()) == 0
        # created_after cutoff between the two rows → only the recent one.
        cutoff = NOW - timedelta(days=30)
        assert await store.count(include_archived=False, created_after=cutoff) == 1
        # Scope + window together → MSFT is recent, AAPL is old → MSFT only.
        assert (
            await store.count(
                include_archived=False, tickers={"AAPL", "MSFT"}, created_after=cutoff
            )
            == 1
        )

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(checks())
    finally:
        loop.close()


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
    _set_quotes({"AAPL": 128.0, "MSFT": 60.0})
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
    _set_quotes({"AAPL": 128.0})
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

    async def explode(_tickers, _data_layer):  # type: ignore[no-untyped-def]
        raise RuntimeError("aiosqlite worker thread died")

    # The route imports fetch_quotes_batch_cached *inside* the handler, so
    # the only patch that lands is on the source module.
    monkeypatch.setattr("finrobot.engine.data.quote_batch.fetch_quotes_batch_cached", explode)

    resp = client.get("/api/dashboard/hit-rate")
    # Key guarantee: no 500. Without live prices the aggregator can't
    # classify any signal, so all buckets degrade to zeros + null hit-rate.
    # UI already handles that branch ("样本不足" hint) — much better than a
    # red error screen.
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["overall"]["hit_rate"] is None
    assert set(data["by_verdict"].keys()) == {"BUY", "HOLD", "SELL"}


def test_recent_research_does_not_500_when_quote_read_explodes(
    client: TestClient,
    store: ArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wedged QuoteCache read must not take the recent-research drawer down.

    The strip is cache-only now, so the failure mode is the L1/L2 read itself
    exploding — it must degrade to None lamps (200), never 500.
    """
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

    # The route imports fetch_quotes_cache_only *inside* the handler, so the
    # patch must land on the source module.
    monkeypatch.setattr("finrobot.engine.data.quote_batch.fetch_quotes_cache_only", explode)

    resp = client.get("/api/dashboard/recent-research?limit=5")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["distinct_ticker_count"] == 1
    assert len(data["items"]) == 1
    # Lamp degrades to None rather than crashing the card.
    assert data["items"][0]["latest_signal"] is None


def test_recent_research_lamp_pending_when_cache_cold(
    client: TestClient,
    store: ArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cards render instantly with a null lamp when quotes are not warm yet.

    The whole point of the cache-only switch: the DB-backed card never waits
    on a quote round-trip. Without a pre-warm, the lamp is null (the frontend
    shows a pending dot and refetches once warmup populates the cache) — but
    the card content is fully present.
    """
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

    # Guard: a cold cache-only read must NOT fan out to the provider chain.
    # If it did, the fake DataLayer would serve a price and the lamp would
    # resolve — proving we regressed back to a blocking cold fetch.
    _set_quotes({"AAPL": 128.0})

    resp = client.get("/api/dashboard/recent-research?limit=5")
    assert resp.status_code == 200, resp.text
    card = resp.json()["items"][0]
    assert card["ticker"] == "AAPL"
    assert card["run_count"] == 1
    assert card["latest_signal"] is None, (
        "cache-only endpoint must not cold-fetch quotes — lamp should stay "
        "pending until the cache is warm"
    )


def test_recent_research_does_not_read_full_artifact_for_verdict(
    client: TestClient,
    store: ArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same guarantee for the recent-research drawer endpoint."""
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


# ─────────────────────────────────────────────────────────────────────────────
# Lifecycle cache invalidation (BUG-20260602-030)
#
# The landing endpoints cache for _LANDING_CACHE_TTL_S (60s). Without explicit
# invalidation, a report saved right after a GET stays invisible for up to a
# minute. invalidate_dashboard_caches() — called by the run-completion and
# artifact delete/view lifecycle paths — must make the change show up on the
# next GET with no TTL wait. These tests assert that WITHOUT sleeping on the
# real TTL.
# ─────────────────────────────────────────────────────────────────────────────


def test_invalidate_dashboard_caches_clears_both_caches() -> None:
    """The invalidation primitive drops both module-level TTL caches."""
    dashboard_mod._HIT_RATE_CACHE["all"] = (1.0, object())  # type: ignore[assignment]
    dashboard_mod._RECENT_CACHE[(5, False)] = (1.0, object())  # type: ignore[assignment]

    dashboard_mod.invalidate_dashboard_caches()

    assert dashboard_mod._HIT_RATE_CACHE == {}
    assert dashboard_mod._RECENT_CACHE == {}


def test_hit_rate_cache_is_bounded_evicts_expired_then_oldest() -> None:
    """The hit-rate cache key embeds the caller's ``tickers`` string verbatim,
    so without a cap every distinct comma-list grows the dict forever (TTL only
    stops reuse, not growth). Inserts past the cap must evict expired entries
    first, then the oldest live one — never exceed _HIT_RATE_CACHE_MAX."""
    dashboard_mod.invalidate_dashboard_caches()
    cap = dashboard_mod._HIT_RATE_CACHE_MAX
    base_ts = 1_000_000.0
    try:
        # Fill to cap with live entries (strictly increasing timestamps,
        # 0.5s apart so the whole span stays inside the 60s TTL — nothing
        # is expired, forcing the oldest-live eviction branch).
        for i in range(cap):
            dashboard_mod._hit_rate_cache_put(
                f"all|T{i}",
                (base_ts + i * 0.5, object()),  # type: ignore[arg-type]
            )
        assert len(dashboard_mod._HIT_RATE_CACHE) == cap

        new_ts = base_ts + cap * 0.5
        dashboard_mod._hit_rate_cache_put("all|FRESH", (new_ts, object()))  # type: ignore[arg-type]
        assert len(dashboard_mod._HIT_RATE_CACHE) <= cap
        assert "all|FRESH" in dashboard_mod._HIT_RATE_CACHE
        assert "all|T0" not in dashboard_mod._HIT_RATE_CACHE  # oldest gone

        # Expired entries are swept before any live eviction.
        dashboard_mod.invalidate_dashboard_caches()
        for i in range(cap):
            dashboard_mod._hit_rate_cache_put(
                f"all|OLD{i}",
                (base_ts, object()),  # type: ignore[arg-type]
            )
        far_future = base_ts + dashboard_mod._LANDING_CACHE_TTL_S + 1
        dashboard_mod._hit_rate_cache_put("all|NEW", (far_future, object()))  # type: ignore[arg-type]
        assert set(dashboard_mod._HIT_RATE_CACHE) == {"all|NEW"}

        # Updating an existing key never triggers eviction churn.
        dashboard_mod._hit_rate_cache_put("all|NEW", (far_future + 1, object()))  # type: ignore[arg-type]
        assert set(dashboard_mod._HIT_RATE_CACHE) == {"all|NEW"}
    finally:
        dashboard_mod.invalidate_dashboard_caches()


def test_recent_research_shows_new_artifact_after_invalidation(
    client: TestClient,
    store: ArtifactStore,
) -> None:
    """Prime the strip cache, save a new ticker, invalidate → it appears now.

    Without the invalidation call the second GET would serve the cached
    (single-card) response for up to 60s. We never touch the real clock — the
    explicit invalidation is the whole point.
    """
    _save(
        store,
        _make_artifact(
            artifact_id="art_AAPL",
            ticker="AAPL",
            entry_price=100.0,
            target_price=130.0,
            verdict="BUY",
            days_ago=10,
        ),
    )
    # Prime the cache: one card (AAPL).
    first = client.get("/api/dashboard/recent-research?limit=5").json()
    assert [c["ticker"] for c in first["items"]] == ["AAPL"]
    assert first["total_in_store"] == 1

    # A new report lands AFTER the cache was primed.
    _save(
        store,
        _make_artifact(
            artifact_id="art_NVDA",
            ticker="NVDA",
            entry_price=100.0,
            target_price=130.0,
            verdict="BUY",
            days_ago=1,
        ),
    )

    # Stale cache still served (proves the TTL window would have hidden NVDA).
    stale = client.get("/api/dashboard/recent-research?limit=5").json()
    assert [c["ticker"] for c in stale["items"]] == ["AAPL"]

    # Lifecycle invalidation (what run-completion fires) → NVDA shows up now.
    dashboard_mod.invalidate_dashboard_caches()
    fresh = client.get("/api/dashboard/recent-research?limit=5").json()
    assert [c["ticker"] for c in fresh["items"]] == ["NVDA", "AAPL"]
    assert fresh["total_in_store"] == 2


@pytest.fixture
def lifecycle_app(tmp_path: Path) -> FastAPI:
    """App mounting BOTH the dashboard and artifacts routers over one store.

    The artifacts route reads ``app.state.artifact_store`` while the dashboard
    route reads ``app.state.deps.artifact_store`` — point both at the same
    store so a mutation through the artifacts route is visible to the dashboard
    endpoints (mirrors the real server wiring).
    """
    from finrobot.routes.artifacts import router as artifacts_router

    app = FastAPI()
    app.include_router(dashboard_router)
    app.include_router(artifacts_router)
    store = ArtifactStore(base_dir=tmp_path / "artifacts")
    app.state.artifact_store = store
    app.state.deps = SimpleNamespace(artifact_store=store, data_layer=_FakeQuoteLayer())
    return app


def test_delete_endpoint_invalidates_dashboard_cache(lifecycle_app: FastAPI) -> None:
    """DELETE /api/artifacts/{id} drops the artifact off the strip immediately."""
    store: ArtifactStore = lifecycle_app.state.artifact_store
    _save(
        store,
        _make_artifact(
            artifact_id="art_AAPL",
            ticker="AAPL",
            entry_price=100.0,
            target_price=130.0,
            verdict="BUY",
            days_ago=1,
        ),
    )
    client = TestClient(lifecycle_app)

    # Prime the strip cache: AAPL present.
    primed = client.get("/api/dashboard/recent-research?limit=5").json()
    assert [c["ticker"] for c in primed["items"]] == ["AAPL"]

    # Delete it through the real lifecycle endpoint.
    assert client.delete("/api/artifacts/art_AAPL").status_code == 200

    # No TTL wait: the strip recomputes and AAPL is gone.
    after = client.get("/api/dashboard/recent-research?limit=5").json()
    assert after["items"] == []
    assert after["total_in_store"] == 0


def test_view_endpoint_invalidates_when_unarchiving(lifecycle_app: FastAPI) -> None:
    """POST /{id}/view un-archives a stale report → it reappears on the strip.

    ``mark_viewed`` sets ``archived=False``. An archived artifact is hidden by
    the strip's ``include_archived=False`` query; viewing it must bring it back
    on the next GET with no TTL wait.
    """
    store: ArtifactStore = lifecycle_app.state.artifact_store
    art = _make_artifact(
        artifact_id="art_AAPL",
        ticker="AAPL",
        entry_price=100.0,
        target_price=130.0,
        verdict="BUY",
        days_ago=1,
    )
    art.meta.archived = True
    _save(store, art)
    client = TestClient(lifecycle_app)

    # Prime the strip cache: archived artifact is hidden.
    primed = client.get("/api/dashboard/recent-research?limit=5").json()
    assert primed["items"] == []

    # Viewing un-archives it (lifecycle path) and busts the cache.
    assert client.post("/api/artifacts/art_AAPL/view").status_code == 200

    after = client.get("/api/dashboard/recent-research?limit=5").json()
    assert [c["ticker"] for c in after["items"]] == ["AAPL"]
