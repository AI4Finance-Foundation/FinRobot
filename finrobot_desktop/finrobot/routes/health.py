"""Health-check endpoints for the lifespan-driven warmup state.

The QuoteCache warmup (see `_warm_quote_cache_background` in `server.py`)
fires as soon as the server's `Application startup complete` event is
emitted, but the actual yfinance fan-out takes ~2s for a typical studied
ticker set. If a user opens the desktop shell during that window, the
landing-page dashboard endpoints fall through to a cold yfinance fetch
inside the request, producing the same 4-5s blocking that we just got
rid of at startup.

`/api/health/quotes-warmed` exposes a boolean flag the frontend polls
so it can keep the landing surface in a skeleton state until the
warmup task finishes. The flag is set true on either:
  - successful warmup completion (any number of tickers prefilled), or
  - empty studied-ticker set (warmup had nothing to do, dashboard is
    already cold-safe because there's no artifact-derived ticker list
    to fan out over).

That collapses the "should I render?" decision to a single bool on
the frontend.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from starlette.requests import Request

router = APIRouter(prefix="/api/health", tags=["health"])


class QuotesWarmedStatus(BaseModel):
    warmed: bool
    studied_ticker_count: int
    """How many distinct studied tickers the warmup task targeted. 0
    means there were no artifacts to derive tickers from, in which case
    the dashboard has no quote dependency anyway."""
    engine_ready: bool = True
    """Data-provider chain wired (post-yield warmup done). False during the cold-
    start window — live-data routes 503 'starting' until it flips, so the frontend
    shows 'starting engine' rather than erroring. Defaults True for back-compat /
    test harnesses without a lifespan (mirrors routes/_ready.py)."""
    agents_ready: bool = True
    """LLM agents built (or decided unbuildable). False during cold start — chat /
    runs 503 'starting' until it flips."""


@router.get("/quotes-warmed", response_model=QuotesWarmedStatus)
async def quotes_warmed(request: Request) -> QuotesWarmedStatus:
    """Return whether the lifespan QuoteCache warmup has finished.

    The frontend landing page polls this at ~500ms intervals while
    `warmed == False` to drive a skeleton-vs-content switch.
    """
    app_state = request.app.state
    return QuotesWarmedStatus(
        warmed=bool(getattr(app_state, "quotes_warmed", False)),
        studied_ticker_count=int(getattr(app_state, "quotes_warmed_ticker_count", 0)),
        engine_ready=bool(getattr(app_state, "engine_ready", True)),
        agents_ready=bool(getattr(app_state, "agents_ready", True)),
    )
