"""Tests for /api/search endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from finrobot.routes.search import _looks_like_ticker, _matches, _parse_slash_command


# ---------------------------------------------------------------------------
# Unit tests for helpers (no HTTP needed)
# ---------------------------------------------------------------------------


class TestLooksLikeTicker:
    def test_simple_ticker(self) -> None:
        assert _looks_like_ticker("AAPL") is True

    def test_lowercase_ticker(self) -> None:
        # function uppercases internally
        assert _looks_like_ticker("aapl") is True

    def test_ticker_with_dot(self) -> None:
        assert _looks_like_ticker("9988.HK") is True

    def test_ticker_with_hyphen(self) -> None:
        assert _looks_like_ticker("BRK-B") is True

    def test_too_long_not_ticker(self) -> None:
        assert _looks_like_ticker("TOOLONGSTRING") is False

    def test_natural_language_not_ticker(self) -> None:
        assert _looks_like_ticker("apple revenue growth") is False

    def test_slash_command_not_ticker(self) -> None:
        assert _looks_like_ticker("/dcf AAPL") is False


class TestParseSlashCommand:
    def test_dcf_with_ticker(self) -> None:
        results = _parse_slash_command("/dcf AAPL")
        assert len(results) == 1
        r = results[0]
        assert r.kind == "slash_command"
        assert "AAPL" in r.title
        assert r.action == "run:dcf:AAPL"
        assert r.score == 8.0

    def test_lbo_with_ticker(self) -> None:
        results = _parse_slash_command("/lbo MSFT")
        assert results[0].action == "run:lbo:MSFT"

    def test_ic_memo_with_ticker(self) -> None:
        results = _parse_slash_command("/ic-memo TSLA")
        assert results[0].action == "run:ic-memo:TSLA"

    def test_unknown_command_returns_empty(self) -> None:
        assert _parse_slash_command("/unknown AAPL") == []

    def test_slash_only_returns_empty(self) -> None:
        assert _parse_slash_command("/") == []

    def test_no_ticker_shows_placeholder(self) -> None:
        results = _parse_slash_command("/dcf")
        assert "??" in results[0].title
        assert results[0].action == "run:dcf:??"


class TestMatches:
    def test_case_insensitive_match(self) -> None:
        assert _matches("apple", "Apple Inc") is True

    def test_no_match(self) -> None:
        assert _matches("banana", "Apple Inc", "AAPL") is False

    def test_matches_any_field(self) -> None:
        assert _matches("aapl", "Technology", "AAPL", "DCF report") is True

    def test_empty_query(self) -> None:
        # Empty string matches everything (substring of anything)
        assert _matches("", "any text") is True


# ---------------------------------------------------------------------------
# Integration tests via HTTP client
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_app():
    """Minimal FastAPI app with /api/search mounted and a stub artifact_store."""
    from fastapi import FastAPI

    from finrobot.routes.search import router as search_router

    test_app = FastAPI()

    # Stub artifact_store that returns no artifacts by default
    mock_store = AsyncMock()
    mock_store.list_by_ticker = AsyncMock(return_value=[])
    test_app.state.artifact_store = mock_store

    test_app.include_router(search_router, prefix="/api/search")
    return test_app


@pytest.fixture()
def client(mock_app: Any) -> Any:
    return AsyncClient(transport=ASGITransport(app=mock_app), base_url="http://test")


async def test_search_ticker_aapl(client: AsyncClient) -> None:
    async with client as c:
        resp = await c.get("/api/search?q=AAPL")
    assert resp.status_code == 200
    data = resp.json()
    results = data["results"]
    assert len(results) >= 1
    # Ticker result should be first (highest score=10)
    assert results[0]["kind"] == "ticker"
    assert results[0]["action"] == "navigate:/stocks/AAPL"


async def test_search_slash_dcf_msft(client: AsyncClient) -> None:
    async with client as c:
        resp = await c.get("/api/search?q=/dcf+MSFT")
    assert resp.status_code == 200
    data = resp.json()
    slash_results = [r for r in data["results"] if r["kind"] == "slash_command"]
    assert len(slash_results) == 1
    assert slash_results[0]["action"] == "run:dcf:MSFT"


async def test_search_natural_language_no_match(client: AsyncClient) -> None:
    """Free text that doesn't match any artifacts or sessions returns empty results."""
    async with client as c:
        resp = await c.get("/api/search?q=苹果增长")
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "苹果增长"
    # No artifacts or sessions seeded → empty
    assert data["results"] == []


async def test_search_empty_string_returns_422(client: AsyncClient) -> None:
    async with client as c:
        resp = await c.get("/api/search?q=")
    assert resp.status_code == 422


async def test_search_too_long_string_returns_422(client: AsyncClient) -> None:
    async with client as c:
        resp = await c.get(f"/api/search?q={'A' * 201}")
    assert resp.status_code == 422


async def test_search_limit_respected(client: AsyncClient) -> None:
    async with client as c:
        resp = await c.get("/api/search?q=AAPL&limit=1")
    assert resp.status_code == 200
    assert len(resp.json()["results"]) <= 1


async def test_search_artifact_emits_runs_path_with_verdict(tmp_path: Path) -> None:
    """Artifacts with a ticker emit /stocks/{ticker}/runs/{id} nav path + verdict in subtitle."""
    from fastapi import FastAPI

    from finrobot.routes.search import router as search_router

    mock_summary = MagicMock()
    mock_summary.ticker = "AAPL"
    mock_summary.type = "dcf"
    mock_summary.headline = "Apple DCF valuation 2026"
    mock_summary.id = "art_001"
    mock_summary.verdict = "BUY"

    mock_store = AsyncMock()
    mock_store.list_by_ticker = AsyncMock(return_value=[mock_summary])

    test_app = FastAPI()
    test_app.state.artifact_store = mock_store
    test_app.include_router(search_router, prefix="/api/search")

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
        resp = await c.get("/api/search?q=apple+dcf")

    assert resp.status_code == 200
    artifact_results = [r for r in resp.json()["results"] if r["kind"] == "artifact"]
    assert len(artifact_results) == 1
    assert artifact_results[0]["action"] == "navigate:/stocks/AAPL/runs/art_001"
    assert "BUY" in artifact_results[0]["subtitle"]
    assert "Apple DCF valuation 2026" in artifact_results[0]["subtitle"]


async def test_search_artifact_without_ticker_is_dropped() -> None:
    """ArtifactSummary with ticker=None must NOT appear in search results."""
    from fastapi import FastAPI

    from finrobot.routes.search import router as search_router

    mock_summary = MagicMock()
    mock_summary.ticker = None
    mock_summary.type = "skill"
    mock_summary.headline = "Generic skill artifact"
    mock_summary.id = "art_002"
    mock_summary.verdict = None

    mock_store = AsyncMock()
    mock_store.list_by_ticker = AsyncMock(return_value=[mock_summary])

    test_app = FastAPI()
    test_app.state.artifact_store = mock_store
    test_app.include_router(search_router, prefix="/api/search")

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
        resp = await c.get("/api/search?q=generic")
    artifact_results = [r for r in resp.json()["results"] if r["kind"] == "artifact"]
    assert artifact_results == []


async def test_search_no_session_results(client: AsyncClient) -> None:
    """Session search results have been removed (dead route until SessionDetailPage lands)."""
    async with client as c:
        resp = await c.get("/api/search?q=anything")
    session_results = [r for r in resp.json()["results"] if r["kind"] == "session"]
    assert session_results == []
