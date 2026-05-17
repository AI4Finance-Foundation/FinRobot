"""Dashboard routes — AI today summary + valuation outliers for the home page."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError
from pydantic_ai import Agent
from pydantic_ai.exceptions import AgentRunError, ModelHTTPError, UnexpectedModelBehavior
from starlette.requests import Request

from finagent.engine.data.interface import ProviderError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class TodaySummaryRequest(BaseModel):
    """Frontend sends watchlist; backend fetches market + events itself."""

    watchlist: list[str] = []


class TodaySummaryResponse(BaseModel):
    summary: str
    model: str
    generated_at: float  # unix ts
    market: dict[str, Any]  # raw numbers for UI to show alongside narrative


# 15-minute cache keyed by sorted watchlist signature
_SUMMARY_CACHE: dict[str, tuple[float, TodaySummaryResponse]] = {}
_CACHE_TTL = 900.0  # 15 min


_SYSTEM_PROMPT = """You are FinAgent — a financial analyst writing one tight paragraph for a retail-investor dashboard.

Constraints:
- Chinese output. 3-5 sentences, max 180 characters.
- Lead with the single most actionable observation (earnings imminent? big catalyst? unusual move?). Then context. Then quiet items.
- Use real numbers from the input. Never invent.
- No disclaimers, no "as an AI", no hedging filler.
- No lists, no bold, no headings — flowing prose only."""


@router.post("/today-summary", response_model=TodaySummaryResponse)
async def today_summary(payload: TodaySummaryRequest, request: Request) -> TodaySummaryResponse:
    """Generate a one-paragraph AI summary of today's market + watchlist events.

    Cached in-memory for 15 minutes per watchlist signature so repeated dashboard
    visits don't burn LLM credits. Returns the raw market snapshot alongside the
    narrative so the UI can render numbers without re-fetching.
    """
    deps = getattr(request.app.state, "deps", None)
    if deps is None:
        raise HTTPException(status_code=503, detail="Backend deps not initialized")

    watchlist = [t.upper().strip() for t in payload.watchlist if t.strip()][:8]
    cache_key = ",".join(sorted(watchlist))

    now = time.time()
    cached = _SUMMARY_CACHE.get(cache_key)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]

    # Gather inputs concurrently — never block on a single slow source.
    market_data = await _gather_market_data(deps, watchlist)

    # Build a structured prompt from real numbers.
    user_prompt = _compose_prompt(market_data)

    # One-shot LLM call. No tools, no transcript pollution.
    model = deps.settings.create_model()
    summarizer: Agent[None, str] = Agent(model, instructions=_SYSTEM_PROMPT)

    try:
        result = await summarizer.run(user_prompt)
        summary_text = result.output.strip()
    except (
        AgentRunError,
        ModelHTTPError,
        UnexpectedModelBehavior,
        httpx.HTTPError,
        asyncio.TimeoutError,
    ) as e:
        logger.warning("today-summary LLM call failed: %s", e)
        # Fall back to deterministic narrative built from raw numbers — never lie
        summary_text = _deterministic_fallback(market_data)

    response = TodaySummaryResponse(
        summary=summary_text,
        model=deps.settings.model_name,
        generated_at=now,
        market=market_data,
    )
    _SUMMARY_CACHE[cache_key] = (now, response)
    return response


async def _gather_market_data(deps: Any, watchlist: list[str]) -> dict[str, Any]:
    """Fetch indices + watchlist prices + top catalysts in parallel."""
    from finagent.engine.compute.market import fetch_earnings_calendar, fetch_market_indices

    fmp_key = getattr(deps.settings, "fmp_api_key", None) or None

    async def _safe(coro: Any, default: Any) -> Any:
        try:
            return await coro
        except (httpx.HTTPError, asyncio.TimeoutError, ProviderError, ValueError) as e:
            logger.debug("dashboard gather (network/provider): %s", e)
            return default

    indices_task = _safe(fetch_market_indices(), [])
    earnings_task = _safe(fetch_earnings_calendar(fmp_key), [])

    # Fetch watchlist prices via DataLayer (each call may fail independently).
    async def _watchlist_prices() -> list[dict[str, Any]]:
        from finagent.engine.data.types import DataType

        out: list[dict[str, Any]] = []
        for tkr in watchlist:
            try:
                res = await deps.data_layer.fetch(DataType.PRICE, tkr)
                p = getattr(res, "data", None) or res
                price = getattr(p, "current_price", None) or (
                    p.get("current_price") if isinstance(p, dict) else None
                )
                change_pct = getattr(p, "change_pct", None) or (
                    p.get("change_pct") if isinstance(p, dict) else None
                )
                if price is not None:
                    out.append({"ticker": tkr, "price": price, "change_pct": change_pct})
            except (
                ProviderError,
                ValidationError,
                httpx.HTTPError,
                asyncio.TimeoutError,
                ValueError,
                KeyError,
            ) as e:
                logger.debug("watchlist price fetch %s: %s", tkr, e)
        return out

    indices, earnings, prices = await asyncio.gather(
        indices_task, earnings_task, _watchlist_prices()
    )

    # Normalize indices/earnings to plain dicts (they're pydantic models).
    indices_dump = [i.model_dump() if hasattr(i, "model_dump") else i for i in indices][:4]
    earnings_dump = [e.model_dump() if hasattr(e, "model_dump") else e for e in earnings]

    # Filter earnings to watchlist tickers when possible; keep top 3 by date.
    wl_set = set(watchlist)
    relevant_earnings = [e for e in earnings_dump if e.get("ticker", "").upper() in wl_set]
    upcoming = sorted(
        relevant_earnings or earnings_dump, key=lambda x: x.get("date", "")
    )[:3]

    avg_change = (
        sum(p["change_pct"] for p in prices if p.get("change_pct") is not None)
        / max(len([p for p in prices if p.get("change_pct") is not None]), 1)
        if prices
        else None
    )

    return {
        "indices": indices_dump,
        "watchlist_prices": prices,
        "watchlist_avg_change_pct": avg_change,
        "upcoming_earnings": upcoming,
    }


def _compose_prompt(m: dict[str, Any]) -> str:
    """Turn the gathered numbers into a compact bullet brief for the LLM."""
    lines: list[str] = []
    for idx in m["indices"]:
        lines.append(
            f"- {idx.get('name', idx.get('symbol'))}: {idx.get('change_pct'):+.2f}%"
        )
    if m["watchlist_prices"]:
        wl_summary = ", ".join(
            f"{p['ticker']} {p.get('change_pct', 0):+.2f}%" for p in m["watchlist_prices"]
        )
        avg = m.get("watchlist_avg_change_pct")
        lines.append(f"- 自选股 ({len(m['watchlist_prices'])} 只, avg {avg:+.2f}%): {wl_summary}")
    for ev in m["upcoming_earnings"]:
        lines.append(
            f"- {ev.get('ticker')} 财报 {ev.get('date')} "
            f"({ev.get('time', 'TBD')}, EPS est {ev.get('eps_estimate', 'N/A')})"
        )
    return "今日数据快照：\n" + "\n".join(lines) + "\n\n请写一段中文摘要。"


def _deterministic_fallback(m: dict[str, Any]) -> str:
    """When LLM fails, build a plain narrative from numbers — never lie."""
    parts: list[str] = []
    spx = next(
        (i for i in m["indices"] if "S&P" in i.get("name", "") or i.get("symbol") == "^GSPC"),
        None,
    )
    if spx:
        parts.append(f"标普 {spx.get('change_pct', 0):+.2f}%")
    avg = m.get("watchlist_avg_change_pct")
    if avg is not None:
        parts.append(f"自选股均值 {avg:+.2f}%")
    if m["upcoming_earnings"]:
        ev = m["upcoming_earnings"][0]
        parts.append(f"{ev.get('ticker')} 财报临近 ({ev.get('date')})")
    if not parts:
        return "今日数据尚未就绪。"
    return "今日 " + "、".join(parts) + "。"


# ─────────────────────────────────────────────────────────────────────────────
# Valuation outliers — for each watchlist ticker, find the latest DCF artifact
# and compute (implied - current) / current. Sorted by abs(offset) DESC.
# ─────────────────────────────────────────────────────────────────────────────

class ValuationOutliersRequest(BaseModel):
    watchlist: list[str] = []


class ValuationItem(BaseModel):
    ticker: str
    current_price: float | None
    implied_price: float | None
    offset_pct: float | None  # (implied - current) / current * 100
    dcf_age_h: float | None   # hours since DCF was computed
    artifact_id: str | None   # for "view full report" link


class ValuationOutliersResponse(BaseModel):
    items: list[ValuationItem]
    generated_at: float


@router.post("/valuation-overview", response_model=ValuationOutliersResponse)
async def valuation_overview(
    payload: ValuationOutliersRequest, request: Request
) -> ValuationOutliersResponse:
    """For each watchlist ticker, return latest DCF implied vs current price.

    Pulls from the artifact store — does NOT trigger new DCF runs (that would
    cost money and block the dashboard). If a ticker has no DCF artifact,
    returns implied_price=null so the frontend can prompt the user to run one.
    """
    deps = getattr(request.app.state, "deps", None)
    if deps is None:
        raise HTTPException(status_code=503, detail="Backend deps not initialized")

    store = request.app.state.artifact_store
    watchlist = [t.upper().strip() for t in payload.watchlist if t.strip()][:8]
    now_ts = time.time()
    now_dt = datetime.now(timezone.utc)

    async def _resolve(ticker: str) -> ValuationItem:
        # 1) Find most recent DCF artifact (cheap — index.json lookup)
        try:
            summaries = await store.list_by_ticker(
                ticker=ticker, type="dcf", include_archived=False, limit=1
            )
        except (OSError, ValueError, KeyError) as e:
            logger.debug("artifact list_by_ticker %s: %s", ticker, e)
            summaries = []

        implied: float | None = None
        age_h: float | None = None
        art_id: str | None = None
        if summaries:
            top = summaries[0]
            art_id = top.id
            try:
                artifact = await store.get(top.id)
                if artifact:
                    val = (artifact.outputs.structured or {}).get("implied_price")
                    if isinstance(val, (int, float)) and val > 0:
                        implied = float(val)
                    created = top.created_at
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    age_h = round((now_dt - created).total_seconds() / 3600, 1)
            except (OSError, ValueError, KeyError, AttributeError) as e:
                logger.debug("artifact load %s: %s", top.id, e)

        # 2) Current price via DataLayer (independent failure)
        current: float | None = None
        try:
            from finagent.engine.data.types import DataType

            res = await deps.data_layer.fetch(DataType.PRICE, ticker)
            p = getattr(res, "data", None) or res
            current_raw = (
                getattr(p, "current_price", None)
                or (p.get("current_price") if isinstance(p, dict) else None)
            )
            if isinstance(current_raw, (int, float)) and current_raw > 0:
                current = float(current_raw)
        except (ProviderError, httpx.HTTPError, asyncio.TimeoutError, ValueError, KeyError) as e:
            logger.debug("price fetch %s: %s", ticker, e)

        offset_pct: float | None = None
        if current is not None and implied is not None:
            offset_pct = round((implied - current) / current * 100, 2)

        return ValuationItem(
            ticker=ticker,
            current_price=current,
            implied_price=implied,
            offset_pct=offset_pct,
            dcf_age_h=age_h,
            artifact_id=art_id,
        )

    items = await asyncio.gather(*[_resolve(t) for t in watchlist])
    # Sort: items with offset first (by abs DESC), then items without
    items_sorted = sorted(
        items,
        key=lambda x: (
            x.offset_pct is None,  # False (have data) first
            -abs(x.offset_pct) if x.offset_pct is not None else 0,
        ),
    )
    return ValuationOutliersResponse(items=items_sorted, generated_at=now_ts)
