"""Market overview routes — indices, sector ETFs, earnings calendar."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from starlette.requests import Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/indices", response_model=list[dict[str, object]])
async def get_indices() -> list[dict[str, object]]:
    """Fetch current prices for major market indices (S&P 500, NASDAQ, DOW 30, VIX, etc.)."""
    from finagent.engine.compute.market import fetch_market_indices

    results = await fetch_market_indices()
    return [r.model_dump() for r in results]


@router.get("/sectors", response_model=list[dict[str, object]])
async def get_sectors() -> list[dict[str, object]]:
    """Fetch current prices for GICS sector ETFs (XLK, XLF, XLE, etc.)."""
    from finagent.engine.compute.market import fetch_sector_etfs

    results = await fetch_sector_etfs()
    return [r.model_dump() for r in results]


@router.get("/earnings-calendar", response_model=list[dict[str, object]])
async def get_earnings_calendar(request: Request) -> list[dict[str, object]]:
    """Fetch upcoming earnings events for the next 7 days.

    Requires an FMP API key configured in Settings. Returns an empty list
    when no key is present — the frontend should surface a 'configure FMP key'
    hint rather than treating the empty response as an error.
    """
    from finagent.engine.compute.market import fetch_earnings_calendar

    settings = getattr(request.app.state, "deps", None)
    fmp_key: str | None = None
    if settings is not None:
        fmp_key = getattr(settings.settings, "fmp_api_key", None) or None

    results = await fetch_earnings_calendar(fmp_key)
    return [r.model_dump() for r in results]
