"""Global cmd+K search backend.

Routes:
  GET /api/search?q=<query>&limit=<int>
      → SearchResponse with typed results (ticker / artifact)

Routing logic for ``q``:
  - Looks like a ticker (shared ``validate_ticker`` syntax) → emit ticker
    navigation suggestion
  - Otherwise → substring search across artifacts
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from finrobot.engine.data.ticker import validate_ticker

router = APIRouter()

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class SearchResult(BaseModel):
    """A single search suggestion item."""

    kind: Literal["ticker", "artifact"]
    title: str
    subtitle: str = ""
    action: str
    """Frontend action string:
      - ``navigate:/stocks/AAPL``
      - ``navigate:/stocks/AAPL/runs/art_xxx``
    """
    score: float = 0.0


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _looks_like_ticker(q: str) -> bool:
    try:
        validate_ticker(q)
    except ValueError:
        return False
    return True


def _matches(q: str, *fields: str) -> bool:
    """Case-insensitive substring match across any of the given fields."""
    ql = q.lower()
    return any(ql in (field or "").lower() for field in fields)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=SearchResponse)
async def search(
    request: Request,
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(20, ge=1, le=100),
) -> SearchResponse:
    """Global cmd+K search.

    Args:
        q: Search query.
        limit: Maximum number of results to return (1–100, default 20).

    Returns:
        ``SearchResponse`` with results sorted by descending score.
    """
    q_stripped = q.strip()
    results: list[SearchResult] = []

    # Branch 1: ticker pattern
    if _looks_like_ticker(q_stripped):
        results.append(
            SearchResult(
                kind="ticker",
                title=q_stripped.upper(),
                subtitle="打开 Stocks 页",
                action=f"navigate:/stocks/{q_stripped.upper()}",
                score=10.0,
            )
        )

    # Branch 2: free-text → artifact substring match (ticker required)
    artifact_store = getattr(request.app.state, "artifact_store", None)
    if artifact_store is not None:
        artifact_summaries = await artifact_store.list_by_ticker(
            ticker=None, limit=200, include_archived=False
        )
        for s in artifact_summaries:
            if not s.ticker:
                # Skip artifacts without a ticker — they have no destination
                # route. Pipeline always requires ticker, so this is a defensive
                # guard for edge-case stored artifacts.
                continue
            if _matches(q_stripped, s.ticker, str(s.type), s.headline):
                verdict_chip = s.verdict if s.verdict else ""
                subtitle = f"{verdict_chip} · {s.headline}" if verdict_chip else s.headline
                results.append(
                    SearchResult(
                        kind="artifact",
                        title=f"{s.ticker} · {str(s.type).upper()}",
                        subtitle=subtitle,
                        action=f"navigate:/stocks/{s.ticker}/runs/{s.id}",
                        score=2.0,
                    )
                )

    results.sort(key=lambda r: r.score, reverse=True)
    return SearchResponse(query=q_stripped, results=results[:limit])
