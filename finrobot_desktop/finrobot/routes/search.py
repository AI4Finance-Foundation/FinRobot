"""Search routes -- ticker autocomplete backed by the local SEC symbol index.

``GET /api/search/symbols?q=ap`` returns market-cap-ranked ``{symbol, name}``
suggestions from the in-memory index (``engine/data/symbol_index``). The lookup
never touches a live provider per keystroke and never raises: an unwarmed or
unavailable index returns an empty list so the homepage search box still works
without suggestions (core contract ②: degrade, never refuse).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel
from starlette.requests import Request

from finrobot.engine.data.symbol_index import ensure_symbol_index

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/search", tags=["search"])

# Mirror of config.FinRobotSettings.sec_user_agent default — only used if the
# app has no settings on state (e.g. a bare test app); production reads the real
# configured identity.
_DEFAULT_SEC_USER_AGENT = "FinRobot admin@example.com"


class SymbolSuggestion(BaseModel):
    """One autocomplete row: ticker + company name (the only fields the SEC
    universe carries — no price/exchange, by design, to avoid fabricating data)."""

    symbol: str
    name: str


class SymbolSearchResponse(BaseModel):
    query: str
    results: list[SymbolSuggestion]


@router.get("/symbols", response_model=SymbolSearchResponse)
async def search_symbols(
    request: Request,
    q: str = Query("", description="Partial ticker symbol or company name."),
    limit: int = Query(8, ge=1, le=25),
) -> SymbolSearchResponse:
    """Ticker autocomplete: ``ap`` -> AAPL / AMAT / APH … ranked by market cap.

    Pure in-memory lookup over the local SEC symbol index. Empty / junk / unknown
    queries return an empty list (HTTP 200), never an error — the index is warmed
    in the background at startup and lazily on first use.
    """
    deps = getattr(request.app.state, "deps", None)
    settings = getattr(deps, "settings", None)
    user_agent = getattr(settings, "sec_user_agent", _DEFAULT_SEC_USER_AGENT)
    index = await ensure_symbol_index(user_agent)
    hits = index.search(q, limit=limit)
    return SymbolSearchResponse(
        query=q,
        results=[SymbolSuggestion(symbol=h.symbol, name=h.name) for h in hits],
    )
