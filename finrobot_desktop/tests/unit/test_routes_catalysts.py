"""Tests for GET /api/data/{ticker}/catalysts endpoint.

The endpoint's pipeline is fetch_news → classify_news (LLM) → extract → rank.
The classify step is a slow (~11–18s) LLM round-trip, so the route caches the
assembled list (DataType.CATALYST, keyed by min_importance). These tests pin:

- 200 with ranked CatalystEvents; sub-threshold news is filtered out.
- Cache hit: a second call for the same (ticker, min_importance) does NOT
  re-run classify_news (the expensive step).
- min_importance keys the cache slot — a different threshold re-runs classify.
- Empty news → 200 [] without ever calling classify.
- classify_news RuntimeError → 500 AND is not cached (a retry re-runs it).
- fetch_news ProviderError → 502 (not a default 500).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock

from finrobot.engine.compute.coordinators.news import NewsItem, RawNewsItem
from finrobot.engine.data.interface import ProviderError


def _raw() -> list[RawNewsItem]:
    return [
        RawNewsItem(
            title="Apple Q4 beats",
            source="Reuters",
            published=datetime(2026, 6, 4, tzinfo=timezone.utc),
            url="https://example.com/a",
        )
    ]


def _classified() -> list[NewsItem]:
    """One catalyst-worthy item (importance 4) + one sub-threshold (importance 2)."""
    return [
        NewsItem(
            title="Apple Q4 beats",
            source="Reuters",
            published=datetime(2026, 6, 4, tzinfo=timezone.utc),
            url="https://example.com/a",
            category="earnings",
            sentiment="positive",
            importance=4,
            summary="Revenue and EPS above consensus.",
        ),
        NewsItem(
            title="Minor supplier note",
            source="Blog",
            published=datetime(2026, 6, 3, tzinfo=timezone.utc),
            url="https://example.com/b",
            category="other",
            sentiment="neutral",
            importance=2,
            summary="Low-signal commentary.",
        ),
    ]


@pytest.mark.asyncio
async def test_catalysts_returns_ranked_events_filtering_sub_threshold(app_with_deps):
    """200 with the importance≥3 item; the importance-2 item is filtered out."""
    app = app_with_deps
    with (
        patch("finrobot.routes.data.fetch_news", new=AsyncMock(return_value=_raw())),
        patch(
            "finrobot.engine.analysis.news_classifier.classify_news",
            new=AsyncMock(return_value=_classified()),
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/data/AAPL/catalysts")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["headline"] == "Apple Q4 beats"
    assert body[0]["impact_score"] == 4


def _dup_classified() -> list[NewsItem]:
    """Two near-duplicate variants of ONE story (same category, same day, high
    title overlap) — the 'Apple raises prices' x4 inflation the live calendar showed."""
    return [
        NewsItem(
            title="Apple raises iPhone prices across the lineup",
            source="Reuters",
            published=datetime(2026, 6, 4, tzinfo=timezone.utc),
            url="https://reuters.com/a",
            category="product",
            sentiment="negative",
            importance=5,
            summary="Across-the-board price increase.",
        ),
        NewsItem(
            title="Apple raises iPhone prices on the new lineup",
            source="Bloomberg",
            published=datetime(2026, 6, 4, tzinfo=timezone.utc),
            url="https://bloomberg.com/b",
            category="product",
            sentiment="negative",
            importance=5,
            summary="Price hike on the latest models.",
        ),
    ]


@pytest.mark.asyncio
async def test_catalysts_route_clusters_near_duplicates(app_with_deps):
    """A① wiring: the live calendar route must run cluster_near_duplicates (like the
    research pipeline), so N variants of one story collapse to a single event
    carrying source_count = cluster size — not N rows each at impact 5."""
    app = app_with_deps
    with (
        patch("finrobot.routes.data.fetch_news", new=AsyncMock(return_value=_raw())),
        patch(
            "finrobot.engine.analysis.news_classifier.classify_news",
            new=AsyncMock(return_value=_dup_classified()),
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/data/AAPL/catalysts")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1  # the two variants merged, not two separate 5/5 rows
    assert body[0]["source_count"] == 2


@pytest.mark.asyncio
async def test_catalysts_cache_hit_skips_llm(app_with_deps):
    """Second call for the same (ticker, min_importance) reuses the cache — no re-classify."""
    app = app_with_deps
    classify = AsyncMock(return_value=_classified())
    with (
        patch("finrobot.routes.data.fetch_news", new=AsyncMock(return_value=_raw())),
        patch("finrobot.engine.analysis.news_classifier.classify_news", new=classify),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.get("/api/data/AAPL/catalysts")
            second = await client.get("/api/data/AAPL/catalysts")

    assert first.status_code == 200
    assert second.json() == first.json()
    classify.assert_awaited_once()  # the expensive LLM step ran exactly once


@pytest.mark.asyncio
async def test_catalysts_min_importance_keys_cache(app_with_deps):
    """A different min_importance is a different cache slot → classify runs again."""
    app = app_with_deps
    classify = AsyncMock(return_value=_classified())
    with (
        patch("finrobot.routes.data.fetch_news", new=AsyncMock(return_value=_raw())),
        patch("finrobot.engine.analysis.news_classifier.classify_news", new=classify),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            high = await client.get("/api/data/AAPL/catalysts?min_importance=3")
            low = await client.get("/api/data/AAPL/catalysts?min_importance=1")

    assert classify.await_count == 2
    # min_importance=1 keeps the importance-2 item too.
    assert len(high.json()) == 1
    assert len(low.json()) == 2


@pytest.mark.asyncio
async def test_catalysts_min_importance_bounded_at_edge(app_with_deps):
    """min_importance is documented 1-5 AND keys a cache slot — an unbounded
    int would mint unbounded cache rows. Out-of-range → 422 before any fetch."""
    app = app_with_deps
    classify = AsyncMock(return_value=_classified())
    with (
        patch("finrobot.routes.data.fetch_news", new=AsyncMock(return_value=_raw())),
        patch("finrobot.engine.analysis.news_classifier.classify_news", new=classify),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for bad in (0, 6, -1, 100000):
                resp = await client.get(f"/api/data/AAPL/catalysts?min_importance={bad}")
                assert resp.status_code == 422, bad
    classify.assert_not_awaited()


@pytest.mark.asyncio
async def test_catalysts_empty_news_returns_empty_without_classify(app_with_deps):
    """No news → 200 [] and classify_news is never called."""
    app = app_with_deps
    classify = AsyncMock(return_value=_classified())
    with (
        patch("finrobot.routes.data.fetch_news", new=AsyncMock(return_value=[])),
        patch("finrobot.engine.analysis.news_classifier.classify_news", new=classify),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/data/NONEWS/catalysts")

    assert resp.status_code == 200
    assert resp.json() == []
    classify.assert_not_awaited()


@pytest.mark.asyncio
async def test_catalysts_classification_failure_500_not_cached(app_with_deps):
    """classify_news RuntimeError → 500, and the failure is NOT cached: a retry re-runs."""
    app = app_with_deps
    classify = AsyncMock(side_effect=RuntimeError("LLM provider 503"))
    with (
        patch("finrobot.routes.data.fetch_news", new=AsyncMock(return_value=_raw())),
        patch("finrobot.engine.analysis.news_classifier.classify_news", new=classify),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            failed = await client.get("/api/data/AAPL/catalysts")
            assert failed.status_code == 500
            # detail is a plain string (every backend HTTPException uses string
            # detail); it must surface the ticker and the underlying LLM cause.
            detail = failed.json()["detail"]
            assert isinstance(detail, str)
            assert "AAPL" in detail
            assert "LLM provider 503" in detail

            # Now the LLM recovers — because the 500 wasn't cached, this re-runs
            # the pipeline and succeeds rather than serving a poisoned empty slot.
            classify.side_effect = None
            classify.return_value = _classified()
            recovered = await client.get("/api/data/AAPL/catalysts")

    assert recovered.status_code == 200
    assert len(recovered.json()) == 1


@pytest.mark.asyncio
async def test_catalysts_provider_error_returns_502(app_with_deps):
    """fetch_news ProviderError → 502 (upstream down), not a default 500."""
    app = app_with_deps
    with patch(
        "finrobot.routes.data.fetch_news",
        new=AsyncMock(side_effect=ProviderError("news api 429")),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/data/AAPL/catalysts")

    assert resp.status_code == 502
