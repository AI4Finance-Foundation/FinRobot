"""End-to-end tests for /api/coverage/* (Coverage Desk Phase 1).

Real CoverageStore (tmp db) behind a FastAPI app; artifact store + data layer
are stubbed at their method surface. Canonical market inputs go through the
real ``normalize_*`` path so the overview exercises ``extract_financial_data``.

Coverage Desk is a single ``Studied Tickers`` workspace — there is no
multi-group management HTTP surface (create / rename / delete / generic member
edit were removed). The group is born by opening a ticker
(``POST /studied-tickers/members``); these tests seed it that way and add any
further members straight through the store.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from finrobot.artifact.models import ArtifactSummary
from finrobot.coverage.sqlite_store import CoverageStore
from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.normalize.financials import normalize_financials
from finrobot.engine.data.normalize.price import normalize_price
from finrobot.engine.data.types import DataType
from finrobot.routes.coverage import _OVERVIEW_CACHE, router
from finrobot.run_store import RunRecord, RunStore

UTC = timezone.utc
NOW = datetime(2026, 5, 1, tzinfo=UTC)
ENTRY = NOW - timedelta(days=30)


def _summary(ticker: str, *, artifact_id: str = "art_1") -> ArtifactSummary:
    return ArtifactSummary(
        id=artifact_id,
        ticker=ticker,
        cross_tickers=[],
        type="equity_research",
        created_at=ENTRY,
        headline="x",
        source="pipeline:equity_research",
        archived=False,
        entry_price=180.0,
        target_price=240.0,
        target_date=ENTRY + timedelta(days=365),
        signal=None,
        verdict="BUY",
    )


def _fin(ticker: str):
    return normalize_financials(
        DataResult(
            data=dict(
                revenue=100e9,
                ebitda=35e9,
                net_income=20e9,
                gross_margin=0.47,
                operating_margin=0.28,
                pe_ratio=28.5,
                market_cap=3e12,
                shares_outstanding=15e9,
                current_price=200.0,
                total_debt=50e9,
                total_cash=20e9,
            ),
            provider="yfinance",
            ticker=ticker,
            data_type="financials",
            timestamp=NOW,
        )
    )


def _price(ticker: str):
    return normalize_price(
        DataResult(
            data={
                "current_price": 200.0,
                "price_history": [
                    {"date": "2025-06-01", "close": 180.0},
                    {"date": "2026-03-01", "close": 200.0},
                ],
            },
            provider="yfinance",
            ticker=ticker,
            data_type="price",
            timestamp=NOW,
        )
    )


class _StubArtifactStore:
    def __init__(self, by_ticker: dict[str, list[ArtifactSummary]] | None = None) -> None:
        self._by_ticker = {k.upper(): v for k, v in (by_ticker or {}).items()}

    async def list_by_ticker(self, ticker=None, type=None, include_archived=False, limit=100):  # noqa: A002
        if ticker is None:
            flat = [s for lst in self._by_ticker.values() for s in lst]
        else:
            flat = list(self._by_ticker.get(ticker.upper(), []))
        flat.sort(key=lambda s: s.created_at, reverse=True)
        return flat[:limit]

    async def get(self, artifact_id: str):
        # No artifact bodies in these route tests → the market-implied re-solve
        # finds no DCF and leaves market_implied None (not exercised here).
        return None


class _StubDataLayer:
    async def fetch_canonical(self, data_type, ticker, **_):
        return _price(ticker) if data_type == DataType.PRICE else _fin(ticker)

    async def read_canonical_cached(self, data_type, ticker, **_):
        norm = _price(ticker) if data_type == DataType.PRICE else _fin(ticker)
        return norm, False  # fresh cache snapshot


@pytest.fixture
async def client(tmp_path: Path):
    _OVERVIEW_CACHE.clear()
    app = FastAPI()
    app.include_router(router)
    store = CoverageStore(db_path=tmp_path / "coverage.db")
    run_store = RunStore(db_path=tmp_path / "runs.db")
    app.state.coverage_store = store
    app.state.run_store = run_store
    app.state.run_tasks = {}
    app.state.artifact_store = _StubArtifactStore({"AAPL": [_summary("AAPL")]})
    app.state.deps = SimpleNamespace(data_layer=_StubDataLayer())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac._app = app  # type: ignore[attr-defined]  # test-only handle for store access
        yield ac
    await store.close()
    await run_store.close()


async def _seed_studied_group(client: AsyncClient, *tickers: str) -> str:
    """Create the Studied Tickers workspace (via the only creation route) and
    load it with ``tickers``, returning the group id.

    The first ticker is enrolled through ``POST /studied-tickers/members`` (the
    product path that births the group); any extras go straight through the
    store, since the desk has no batch member-add HTTP surface.
    """
    first, *rest = tickers or ("AAPL",)
    body = (
        await client.post("/api/coverage/studied-tickers/members", json={"ticker": first})
    ).json()
    gid: str = body["id"]
    if rest:
        store: CoverageStore = client._app.state.coverage_store  # type: ignore[attr-defined]
        await store.add_members(gid, list(rest))
    return gid


async def test_state_d_seeds_studied_tickers_on_first_visit(client: AsyncClient) -> None:
    # No groups yet, but the artifact store has AAPL → first list seeds it.
    r = await client.get("/api/coverage/groups")
    assert r.status_code == 200
    groups = r.json()
    assert len(groups) == 1
    assert groups[0]["name"] == "Studied Tickers"
    assert groups[0]["is_system"] is True
    assert groups[0]["member_count"] == 1


async def test_studied_auto_add_creates_and_is_idempotent(client: AsyncClient) -> None:
    # First open of a ticker seeds the Studied Tickers workspace and enrols it.
    r = await client.post("/api/coverage/studied-tickers/members", json={"ticker": "tsla"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Studied Tickers"
    assert body["is_system"] is True
    assert [m["ticker"] for m in body["members"]] == ["TSLA"]  # upper-cased

    # Re-opening is a no-op (no duplicate, still one group).
    r = await client.post("/api/coverage/studied-tickers/members", json={"ticker": "TSLA"})
    assert [m["ticker"] for m in r.json()["members"]] == ["TSLA"]
    groups = (await client.get("/api/coverage/groups")).json()
    assert sum(1 for g in groups if g["is_system"]) == 1


async def test_studied_auto_add_rejects_junk_ticker(client: AsyncClient) -> None:
    r = await client.post("/api/coverage/studied-tickers/members", json={"ticker": "苹果"})
    assert r.status_code == 422


async def test_overview_assembles_rows(client: AsyncClient) -> None:
    gid = await _seed_studied_group(client, "AAPL")

    r = await client.get(f"/api/coverage/groups/{gid}/overview")
    assert r.status_code == 200
    body = r.json()
    assert body["group_id"] == gid
    (row,) = body["rows"]
    assert row["ticker"] == "AAPL"
    assert row["price"] == 200.0
    assert row["market_cap"] == pytest.approx(3e12)
    assert row["revenue_ttm"] == pytest.approx(100e9)
    assert row["latest_verdict"] == "BUY"
    assert row["artifact_count"] == 1
    assert row["research_count"] == 1  # the seeded artifact carries a verdict
    assert row["upside_to_target_live"] == pytest.approx(0.2)
    assert body["partial"] is False


async def test_overview_missing_group_404(client: AsyncClient) -> None:
    assert (await client.get("/api/coverage/groups/cov_nope/overview")).status_code == 404


async def test_overview_surfaces_failed_run(client: AsyncClient) -> None:
    gid = await _seed_studied_group(client, "AAPL")

    run_store: RunStore = client._app.state.run_store  # type: ignore[attr-defined]
    rec = await run_store.create_run("dcf", "AAPL")
    await run_store.update_run(rec.run_id, status="failed", error="provider down")

    body = (await client.get(f"/api/coverage/groups/{gid}/overview?refresh=true")).json()
    (row,) = body["rows"]
    assert row["run_status"] == "failed"
    assert row["run_error"] == "provider down"
    assert any(r["kind"] == "run_failed" for r in row["needs_refresh"])


async def test_batch_run_spawns_per_ticker(client: AsyncClient, monkeypatch) -> None:
    gid = await _seed_studied_group(client, "AAPL")

    calls: list[tuple[str, str]] = []

    async def fake_spawn(request, pipeline_type, ticker, **kw):
        norm = ticker.strip().upper()
        if norm == "BAD":
            raise ValueError(f"Invalid pipeline: {pipeline_type}")
        calls.append((pipeline_type, norm))
        return RunRecord(
            run_id=f"run_{norm}",
            pipeline_type=pipeline_type,
            ticker=norm,
            status="created",
            created_at=NOW.isoformat(),
        )

    monkeypatch.setattr("finrobot.routes.runs.spawn_run", fake_spawn)

    r = await client.post(
        f"/api/coverage/groups/{gid}/runs",
        json={"tickers": ["aapl", "msft", "bad"], "pipeline_type": "dcf"},
    )
    assert r.status_code == 200
    body = r.json()
    assert {item["ticker"] for item in body["runs"]} == {"AAPL", "MSFT"}
    assert body["runs"][0]["run_id"].startswith("run_")
    assert [s["ticker"] for s in body["skipped"]] == ["BAD"]
    assert calls == [("dcf", "AAPL"), ("dcf", "MSFT")]


async def test_batch_run_missing_group_404(client: AsyncClient) -> None:
    r = await client.post("/api/coverage/groups/cov_nope/runs", json={"tickers": ["AAPL"]})
    assert r.status_code == 404


async def test_batch_run_default_pipeline_is_valid_registry_key(
    client: AsyncClient, monkeypatch
) -> None:
    """Coverage's core button posts no pipeline_type; the default must be a real
    pipeline-registry key, not the artifact type 'equity_research' (BUG-049):
    the old default made every ticker skip with a 200/zero-runs response."""
    from finrobot.engine.pipelines.registry import get_pipeline_factories

    gid = await _seed_studied_group(client, "AAPL")

    seen: list[str] = []

    async def fake_spawn(request, pipeline_type, ticker, **kw):
        seen.append(pipeline_type)
        return RunRecord(
            run_id=f"run_{ticker.strip().upper()}",
            pipeline_type=pipeline_type,
            ticker=ticker.strip().upper(),
            status="created",
            created_at=NOW.isoformat(),
        )

    monkeypatch.setattr("finrobot.routes.runs.spawn_run", fake_spawn)

    # No pipeline_type → exercises the request-model default.
    r = await client.post(f"/api/coverage/groups/{gid}/runs", json={"tickers": ["AAPL"]})
    assert r.status_code == 200
    body = r.json()
    assert seen == ["research"]
    assert body["pipeline_type"] == "research"
    assert len(body["runs"]) == 1 and body["skipped"] == []
    # Tie the default to the real source of truth so a key rename can't drift.
    assert "research" in get_pipeline_factories()


async def test_overview_l1_cache_and_refresh_bypass(client: AsyncClient) -> None:
    gid = await _seed_studied_group(client, "AAPL")

    first = (await client.get(f"/api/coverage/groups/{gid}/overview")).json()
    assert len(first["rows"]) == 1

    # Mutate the store directly (bypassing the route's cache invalidation) to
    # prove the next plain GET is served from the L1 cache, stale on purpose.
    store: CoverageStore = client._transport.app.state.coverage_store  # type: ignore[attr-defined]
    await store.add_members(gid, ["MSFT"])

    cached = (await client.get(f"/api/coverage/groups/{gid}/overview")).json()
    assert len(cached["rows"]) == 1  # cache hit — MSFT not yet visible
    assert cached["generated_at"] == first["generated_at"]

    fresh = (await client.get(f"/api/coverage/groups/{gid}/overview?refresh=true")).json()
    assert len(fresh["rows"]) == 2  # bypass → MSFT now present
