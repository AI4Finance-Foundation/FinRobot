"""Tests for GET /api/data/{ticker}/earnings-calls.

BUG-080 regression: FMP serves annual/special calls (and pre-backfill rows)
with a missing/zero/null ``quarter``, but ``EarningsCallTranscript`` requires
``quarter ∈ 1..4``. The construction loop used to sit OUTSIDE the try/except, so
a single malformed item raised a ValidationError that escaped as a bare 500.
The fix constructs each transcript inside try/except and skips the bad item
(with a warning) instead of crashing the whole endpoint.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import AsyncClient, ASGITransport

from finrobot.engine.data.types import DataType


class _FakeProvider:
    def capabilities(self) -> set[DataType]:
        return {DataType.EARNINGS_TRANSCRIPT}


def _install_transcript_data_layer(app, transcripts: list[dict]) -> None:
    """Wire a data_layer that reports transcript capability and returns ``transcripts``."""

    async def _fetch(*_args, **_kwargs):
        return SimpleNamespace(data={"transcripts": transcripts})

    app.state.deps.data_layer = SimpleNamespace(
        _providers=[_FakeProvider()],
        fetch=_fetch,
    )


@pytest.mark.asyncio
async def test_earnings_calls_skips_malformed_quarter_instead_of_500(app_with_deps):
    """A zero/null/out-of-range quarter must be skipped, not crash the endpoint."""
    app = app_with_deps
    _install_transcript_data_layer(
        app,
        [
            # Valid quarterly call.
            {
                "ticker": "AAPL",
                "quarter": 3,
                "year": 2025,
                "date": "2025-07-31",
                "content": "Q3 call.",
            },
            # Annual/special call — FMP sends quarter=0 (the model rejects it).
            {
                "ticker": "AAPL",
                "quarter": 0,
                "year": 2025,
                "date": "2025-12-15",
                "content": "Annual meeting.",
            },
            # Null quarter (provider omitted it).
            {
                "ticker": "AAPL",
                "quarter": None,
                "year": 2025,
                "date": "2025-09-01",
                "content": "Special call.",
            },
            # Out-of-range quarter.
            {
                "ticker": "AAPL",
                "quarter": 7,
                "year": 2025,
                "date": "2025-10-01",
                "content": "Bad quarter.",
            },
        ],
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/data/AAPL/earnings-calls")

    assert resp.status_code == 200
    body = resp.json()
    # Only the one valid transcript survives; the three bad items are skipped.
    assert len(body["transcripts"]) == 1
    assert body["transcripts"][0]["quarter"] == 3
    assert body["transcripts"][0]["year"] == 2025
    assert body["ticker"] == "AAPL"


@pytest.mark.asyncio
async def test_earnings_calls_all_valid_pass_through(app_with_deps):
    """Sanity: a fully valid payload returns every transcript."""
    app = app_with_deps
    _install_transcript_data_layer(
        app,
        [
            {"ticker": "AAPL", "quarter": 4, "year": 2025, "content": "Q4."},
            {"ticker": "AAPL", "quarter": 3, "year": 2025, "content": "Q3."},
        ],
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/data/AAPL/earnings-calls")

    assert resp.status_code == 200
    assert len(resp.json()["transcripts"]) == 2


@pytest.mark.asyncio
async def test_earnings_calls_canonicalizes_share_class_ticker(app_with_deps):
    """A data route must funnel its path-param through the validate_ticker
    chokepoint, so a dotted US share class (BRK.B — which yfinance cannot resolve)
    is canonicalized to the hyphen form BRK-B the providers accept, sharing ONE
    cache/coverage slot with the pipeline instead of splitting (the bare
    ticker.upper() this replaces did neither)."""
    app = app_with_deps
    seen: dict[str, str] = {}

    async def _fetch(data_type, ticker, **_kwargs):
        seen["ticker"] = ticker
        return SimpleNamespace(data={"transcripts": []})

    app.state.deps.data_layer = SimpleNamespace(_providers=[_FakeProvider()], fetch=_fetch)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/data/BRK.B/earnings-calls")

    assert resp.status_code == 200
    assert seen["ticker"] == "BRK-B"  # provider queried with the canonical form
    assert resp.json()["ticker"] == "BRK-B"  # response reflects the canonical form


@pytest.mark.asyncio
async def test_earnings_calls_rejects_junk_ticker(app_with_deps):
    """The chokepoint also rejects junk at the route (CJK / injection), which the
    bare .upper() let through to be cached + re-fanned to providers forever."""
    app = app_with_deps
    _install_transcript_data_layer(app, [])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/data/AAPL;DROP/earnings-calls")

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_earnings_calls_params_bounded_at_edge(app_with_deps):
    """``limit``/``quarter``/``year`` are bounded query params (mirroring the
    sentiment route's ``days`` cap): they flow into the FMP request and the
    cache key, so unbounded values hammer the quota and mint unbounded cache
    rows. Out-of-range → 422 before any fetch."""
    app = app_with_deps
    _install_transcript_data_layer(app, [])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for params in (
            {"limit": 0},
            {"limit": 13},
            {"limit": 100000},
            {"quarter": 0},
            {"quarter": 5},
            {"year": 1899},
            {"year": 2101},
        ):
            resp = await client.get("/api/data/AAPL/earnings-calls", params=params)
            assert resp.status_code == 422, params

        # In-range values still pass through.
        resp = await client.get(
            "/api/data/AAPL/earnings-calls",
            params={"limit": 12, "quarter": 4, "year": 2025},
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_earnings_calls_all_malformed_returns_empty_not_500(app_with_deps):
    """If every item is malformed, the endpoint returns an empty list, not a 500."""
    app = app_with_deps
    _install_transcript_data_layer(
        app,
        [
            {"ticker": "AAPL", "quarter": 0, "year": 2025, "content": "Annual."},
            {"ticker": "AAPL", "quarter": None, "year": 2025, "content": "Special."},
        ],
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/data/AAPL/earnings-calls")

    assert resp.status_code == 200
    assert resp.json()["transcripts"] == []
