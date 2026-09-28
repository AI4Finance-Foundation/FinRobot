"""Inbound rate-limit guard on the cost-bearing endpoints (BUG-043).

Three endpoints spend real LLM money: POST /chat, POST /api/runs, and POST
/api/coverage/groups/{id}/runs. A shared in-process token bucket
(``RunRateLimiter`` on ``app.state.run_rate_limiter``) caps how many runs / chats
can be STARTED per minute — defense-in-depth orthogonal to the concurrency cap
(run_semaphore, BUG-017) and the host-header allowlist (BUG-004).

These tests prove: a burst over the limit gets 429; traffic under the limit is
admitted; a coverage batch is charged its ticker count atomically (never half a
batch); the bucket refills over (mocked) time. spawn_run is stubbed so no real
pipeline / LLM is touched.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from finrobot.ratelimit import RunRateLimiter
from finrobot.run_store import RunRecord


# ── Unit: the token bucket itself ────────────────────────────────────────────


class _FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def test_runs_burst_over_capacity_is_rejected() -> None:
    clock = _FakeClock()
    limiter = RunRateLimiter(runs_per_minute=10.0, chat_per_minute=10.0, time_fn=clock)
    # Capacity == per-minute budget == 10 starts full. First 10 admitted...
    assert all(limiter.allow_runs(1) for _ in range(10))
    # ...the 11th (no time elapsed → no refill) is rejected.
    assert limiter.allow_runs(1) is False


def test_runs_under_capacity_all_admitted() -> None:
    clock = _FakeClock()
    limiter = RunRateLimiter(runs_per_minute=120.0, chat_per_minute=60.0, time_fn=clock)
    # A normal 10-ticker coverage batch worth of single runs sails through.
    assert all(limiter.allow_runs(1) for _ in range(10))


def test_batch_charged_atomically_never_half() -> None:
    clock = _FakeClock()
    limiter = RunRateLimiter(runs_per_minute=10.0, chat_per_minute=10.0, time_fn=clock)
    # 6 tokens already spent → only 4 left; a batch of 5 must be rejected WHOLE,
    # not partially admitted, and must not consume any tokens.
    assert limiter.allow_runs(6) is True
    assert limiter.allow_runs(5) is False
    # The 4 leftover tokens are intact: a batch of 4 still fits.
    assert limiter.allow_runs(4) is True


def test_bucket_refills_over_time() -> None:
    clock = _FakeClock()
    limiter = RunRateLimiter(runs_per_minute=60.0, chat_per_minute=60.0, time_fn=clock)
    # Drain the bucket.
    assert limiter.allow_runs(60) is True
    assert limiter.allow_runs(1) is False
    # 60/min == 1/sec refill; after 5s, 5 tokens are back.
    clock.advance(5.0)
    assert all(limiter.allow_runs(1) for _ in range(5))
    assert limiter.allow_runs(1) is False
    # Refill never exceeds capacity even after a long idle.
    clock.advance(10_000.0)
    assert limiter.allow_runs(60) is True
    assert limiter.allow_runs(1) is False


def test_chat_bucket_independent_of_runs() -> None:
    clock = _FakeClock()
    limiter = RunRateLimiter(runs_per_minute=1.0, chat_per_minute=2.0, time_fn=clock)
    # Draining runs does not touch chat and vice-versa.
    assert limiter.allow_runs(1) is True
    assert limiter.allow_runs(1) is False
    assert limiter.allow_chat() is True
    assert limiter.allow_chat() is True
    assert limiter.allow_chat() is False


# ── Route: POST /api/runs burst → 429 ────────────────────────────────────────


@pytest.fixture
async def runs_client(monkeypatch: pytest.MonkeyPatch):
    """App with the runs router and a stubbed spawn_run (no real pipeline)."""
    from finrobot.routes import runs as runs_module

    app = FastAPI()
    app.include_router(runs_module.router)
    app.state.startup_error = None
    # Small bucket so the test can exercise the limit without firing 120 calls.
    app.state.run_rate_limiter = RunRateLimiter(runs_per_minute=3.0, chat_per_minute=3.0)

    _counter = {"n": 0}

    async def _fake_spawn(request, pipeline_type, ticker, **kwargs):  # noqa: ANN001, ANN003
        _counter["n"] += 1
        return RunRecord(
            run_id=f"run_{_counter['n']}",
            pipeline_type=pipeline_type,
            ticker=ticker.upper(),
            status="created",
            created_at="2026-06-04T00:00:00+00:00",
        )

    monkeypatch.setattr(runs_module, "spawn_run", _fake_spawn)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_runs_burst_over_limit_returns_429(runs_client: AsyncClient) -> None:
    payload = {"pipeline_type": "research", "ticker": "AAPL"}
    # Bucket holds 3 tokens → first 3 OK.
    for _ in range(3):
        r = await runs_client.post("/api/runs", json=payload)
        assert r.status_code == 200, r.text
    # 4th exceeds the per-minute budget → 429.
    r = await runs_client.post("/api/runs", json=payload)
    assert r.status_code == 429
    assert "Rate limit" in r.json()["detail"]


async def test_runs_under_limit_all_ok(runs_client: AsyncClient) -> None:
    payload = {"pipeline_type": "research", "ticker": "AAPL"}
    for _ in range(3):
        r = await runs_client.post("/api/runs", json=payload)
        assert r.status_code == 200, r.text


# ── Route: coverage batch burst → 429, batch charged atomically ──────────────


@pytest.fixture
async def coverage_client(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """App with the coverage router + a real group, stubbed spawn_run."""
    from finrobot.coverage.sqlite_store import CoverageStore
    from finrobot.routes import runs as runs_module
    from finrobot.routes.coverage import _OVERVIEW_CACHE
    from finrobot.routes.coverage import router as coverage_router

    _OVERVIEW_CACHE.clear()
    app = FastAPI()
    app.include_router(coverage_router)
    app.state.startup_error = None
    store = CoverageStore(db_path=tmp_path / "coverage.db")
    # Coverage Desk has no create-group route — the single Studied Tickers
    # workspace is the only group. Seed it directly so the batch-run tests have
    # a target gid (they exercise the rate limiter, not group creation).
    group = await store.get_or_create_system_group("Studied Tickers")
    app.state.coverage_store = store
    app.state.run_store = SimpleNamespace()
    app.state.run_tasks = {}
    app.state.run_rate_limiter = RunRateLimiter(runs_per_minute=5.0, chat_per_minute=5.0)

    _counter = {"n": 0}

    async def _fake_spawn(request, pipeline_type, ticker, **kwargs):  # noqa: ANN001, ANN003
        _counter["n"] += 1
        return RunRecord(
            run_id=f"run_{_counter['n']}",
            pipeline_type=pipeline_type,
            ticker=ticker.upper(),
            status="created",
            created_at="2026-06-04T00:00:00+00:00",
        )

    # Coverage imports spawn_run lazily from runs_module → patch there.
    monkeypatch.setattr(runs_module, "spawn_run", _fake_spawn)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac._app = app  # type: ignore[attr-defined]
        ac._gid = group.id  # type: ignore[attr-defined]  # seeded Studied Tickers group
        yield ac
    await store.close()


async def test_coverage_batch_over_budget_returns_429(coverage_client: AsyncClient) -> None:
    gid = coverage_client._gid  # type: ignore[attr-defined]
    # Bucket = 5 tokens; a 6-ticker batch is charged 6 atomically → 429, and
    # because the charge is atomic NO run is spawned.
    r = await coverage_client.post(
        f"/api/coverage/groups/{gid}/runs",
        json={"pipeline_type": "research", "tickers": ["A", "B", "C", "D", "E", "F"]},
    )
    assert r.status_code == 429
    assert "Rate limit" in r.json()["detail"]


async def test_coverage_batch_within_budget_runs(coverage_client: AsyncClient) -> None:
    gid = coverage_client._gid  # type: ignore[attr-defined]
    # A 5-ticker batch exactly fits the 5-token bucket → all spawned.
    r = await coverage_client.post(
        f"/api/coverage/groups/{gid}/runs",
        json={"pipeline_type": "research", "tickers": ["A", "B", "C", "D", "E"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["runs"]) == 5
    assert body["skipped"] == []
    # The bucket is now empty → a follow-up single ticker is throttled.
    r2 = await coverage_client.post(
        f"/api/coverage/groups/{gid}/runs",
        json={"pipeline_type": "research", "tickers": ["G"]},
    )
    assert r2.status_code == 429


# ── Live-data GET bucket (P2 audit 2026-06-10) ───────────────────────────────
# Read-only GETs spend no LLM money but each cache miss burns provider quota
# (FMP free tier is a daily budget). The live_data bucket is independent of
# runs/chat and guards /api/data/* + /api/sentiment/* via
# enforce_live_data_limit.


def test_live_data_bucket_independent_and_bounded() -> None:
    clock = _FakeClock()
    limiter = RunRateLimiter(
        runs_per_minute=10.0,
        chat_per_minute=10.0,
        live_data_per_minute=5.0,
        time_fn=clock,
    )
    assert all(limiter.allow_live_data() for _ in range(5))
    assert not limiter.allow_live_data()  # drained
    # Draining live-data must not touch the runs/chat buckets.
    assert limiter.allow_runs(1)
    assert limiter.allow_chat()
    # Refills at the per-minute rate.
    clock.advance(60.0)
    assert all(limiter.allow_live_data() for _ in range(5))


@pytest.mark.asyncio
async def test_data_get_over_limit_returns_429() -> None:
    """Every provider-backed GET in routes/data.py + the sentiment GET runs
    through enforce_live_data_limit — a drained bucket means 429, and an app
    without a limiter configured (bare test apps) is never throttled."""
    from finrobot.routes.data import router as data_router
    from finrobot.routes.sentiment import router as sentiment_router

    clock = _FakeClock()
    app = FastAPI()
    app.include_router(data_router)
    app.include_router(sentiment_router)
    app.state.deps = SimpleNamespace(data_layer=SimpleNamespace(_providers=[]))
    app.state.run_rate_limiter = RunRateLimiter(live_data_per_minute=2.0, time_fn=clock)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Two tokens: the first two GETs pass the limiter (then fail later in
        # the handler for unrelated reasons — 503 no transcript provider).
        assert (await client.get("/api/data/AAPL/earnings-calls")).status_code == 503
        assert (await client.get("/api/data/AAPL/earnings-calls")).status_code == 503
        # Bucket drained → 429 before any handler work, on every guarded route.
        assert (await client.get("/api/data/AAPL/earnings-calls")).status_code == 429
        assert (await client.get("/api/sentiment/AAPL")).status_code == 429

        clock.advance(60.0)
        assert (await client.get("/api/data/AAPL/earnings-calls")).status_code == 503

    # No limiter configured → guard is a no-op (bare apps in older tests).
    app2 = FastAPI()
    app2.include_router(data_router)
    app2.state.deps = SimpleNamespace(data_layer=SimpleNamespace(_providers=[]))
    transport2 = ASGITransport(app=app2)
    async with AsyncClient(transport=transport2, base_url="http://test") as client2:
        assert (await client2.get("/api/data/AAPL/earnings-calls")).status_code == 503
