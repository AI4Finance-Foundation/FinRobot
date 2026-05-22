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
    dcf_age_h: float | None  # hours since DCF was computed
    artifact_id: str | None  # for "view full report" link


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
            current_raw = getattr(p, "current_price", None) or (
                p.get("current_price") if isinstance(p, dict) else None
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


# ─────────────────────────────────────────────────────────────────────────────
# "Why is it moving?" — 1-2 sentence LLM explanation of today's price action
# for a single ticker. Pulls price + top news + top catalyst, asks the LLM
# to synthesize the most likely driver.
# ─────────────────────────────────────────────────────────────────────────────


class WhyMovingResponse(BaseModel):
    ticker: str
    change_pct: float | None
    explanation: str
    sources: list[str]  # headlines / catalyst titles used
    model: str
    generated_at: float


_WHY_CACHE: dict[str, tuple[float, WhyMovingResponse]] = {}
_WHY_TTL = 30 * 60.0  # 30 min — news shifts faster than daily summary


_WHY_PROMPT = """You are FinAgent explaining stock price moves to a retail investor.

Constraints:
- Chinese, 1-2 sentences, max 80 characters total.
- Lead with the most likely driver. Reference specific news/catalyst items by name.
- If price barely moved (|change| < 0.5%) say so directly: "今日波动不大，无明显驱动事件。"
- If no news/catalyst data exists, be honest: "近期无重大新闻，可能受大盘/板块影响。"
- Never invent. Never hedge with "may be" / "could be" / "as an AI"."""


@router.post("/explain-move/{ticker}", response_model=WhyMovingResponse)
async def explain_move(ticker: str, request: Request) -> WhyMovingResponse:
    """Why is this ticker moving today? Synthesize price + news + catalysts → 1 sentence.

    Cached 30 min per ticker. Reuses existing data layer endpoints concurrently
    so this stays cheap even when called on every watchlist item hover.
    """
    deps = getattr(request.app.state, "deps", None)
    if deps is None:
        raise HTTPException(status_code=503, detail="Backend deps not initialized")

    tkr = ticker.upper().strip()
    now = time.time()
    cached = _WHY_CACHE.get(tkr)
    if cached and now - cached[0] < _WHY_TTL:
        return cached[1]

    # Parallel fetch: price + news + catalysts
    snapshot = await _gather_ticker_snapshot(deps, tkr)

    user_prompt = _compose_why_prompt(tkr, snapshot)

    model = deps.settings.create_model()
    summarizer: Agent[None, str] = Agent(model, instructions=_WHY_PROMPT)

    try:
        result = await summarizer.run(user_prompt)
        explanation = result.output.strip()
    except (
        AgentRunError,
        ModelHTTPError,
        UnexpectedModelBehavior,
        httpx.HTTPError,
        asyncio.TimeoutError,
    ) as e:
        logger.warning("explain-move LLM failed for %s: %s", tkr, e)
        explanation = _deterministic_why_fallback(snapshot)

    response = WhyMovingResponse(
        ticker=tkr,
        change_pct=snapshot.get("change_pct"),
        explanation=explanation,
        sources=snapshot.get("sources", [])[:3],
        model=deps.settings.model_name,
        generated_at=now,
    )
    _WHY_CACHE[tkr] = (now, response)
    return response


async def _gather_ticker_snapshot(deps: Any, ticker: str) -> dict[str, Any]:
    """Fetch price + news headlines + top catalyst for one ticker concurrently."""
    from finagent.engine.compute.catalyst import (
        compute_expected_impact,
        extract_catalysts_from_news,
        rank_catalysts,
    )
    from finagent.engine.analysis.news_classifier import classify_news
    from finagent.engine.compute.news import fetch_news
    from finagent.engine.data.types import DataType

    async def _price() -> tuple[float | None, float | None]:
        try:
            res = await deps.data_layer.fetch(DataType.PRICE, ticker)
            p = getattr(res, "data", None) or res
            cp = getattr(p, "current_price", None) or (
                p.get("current_price") if isinstance(p, dict) else None
            )
            cpct = getattr(p, "change_pct", None) or (
                p.get("change_pct") if isinstance(p, dict) else None
            )
            return (
                float(cp) if isinstance(cp, (int, float)) else None,
                float(cpct) if isinstance(cpct, (int, float)) else None,
            )
        except (ProviderError, httpx.HTTPError, asyncio.TimeoutError, ValueError, KeyError):
            return (None, None)

    async def _news_and_catalysts() -> tuple[list[str], list[dict[str, Any]]]:
        try:
            raw = await fetch_news(deps.data_layer, ticker)
        except (ValueError, ProviderError, httpx.HTTPError, asyncio.TimeoutError):
            return ([], [])
        if not raw:
            return ([], [])
        # Top 5 headlines (raw, no LLM classification — cheaper)
        headlines = [getattr(r, "title", "") or "" for r in raw[:5] if getattr(r, "title", None)]
        # Classify + extract catalysts (uses LLM but cached by news layer)
        try:
            classified = await classify_news(raw, deps)
            cats = extract_catalysts_from_news(classified, min_importance=3)
            cats = compute_expected_impact(cats)
            cats = rank_catalysts(cats)
            cat_dicts: list[dict[str, Any]] = [
                c.model_dump() if hasattr(c, "model_dump") else dict(c)  # type: ignore[arg-type]
                for c in cats[:2]
            ]
        except (
            AgentRunError,
            ModelHTTPError,
            UnexpectedModelBehavior,
            httpx.HTTPError,
            asyncio.TimeoutError,
            ValueError,
        ):
            cat_dicts = []
        return (headlines, cat_dicts)

    (price_pair, news_pair) = await asyncio.gather(_price(), _news_and_catalysts())
    current_price, change_pct = price_pair
    headlines, catalysts = news_pair

    sources = [*[c.get("title", "") for c in catalysts if c.get("title")], *headlines][:5]

    return {
        "ticker": ticker,
        "current_price": current_price,
        "change_pct": change_pct,
        "top_catalysts": catalysts,
        "headlines": headlines,
        "sources": sources,
    }


def _compose_why_prompt(ticker: str, s: dict[str, Any]) -> str:
    parts: list[str] = [f"代码: {ticker}"]
    cp = s.get("change_pct")
    if cp is not None:
        parts.append(f"今日涨跌: {cp:+.2f}%")
    else:
        parts.append("今日涨跌: 数据未获取")
    cats = s.get("top_catalysts") or []
    if cats:
        parts.append("近期催化剂:")
        for c in cats[:2]:
            title = c.get("title", "")
            impact = c.get("impact", "")
            parts.append(f"  - [{impact}] {title}")
    headlines = s.get("headlines") or []
    if headlines:
        parts.append("近期新闻头条:")
        for h in headlines[:5]:
            parts.append(f"  - {h}")
    if not cats and not headlines:
        parts.append("（无近期新闻或催化剂数据）")
    parts.append("\n用 1-2 句中文解释今日动向。")
    return "\n".join(parts)


def _deterministic_why_fallback(s: dict[str, Any]) -> str:
    cp = s.get("change_pct")
    if cp is None:
        return "今日数据尚未就绪。"
    if abs(cp) < 0.5:
        return "今日波动不大，无明显驱动事件。"
    cats = s.get("top_catalysts") or []
    if cats:
        c = cats[0]
        title = c.get("title", "")
        return f"今日 {cp:+.2f}%，可能与「{title}」相关。"
    headlines = s.get("headlines") or []
    if headlines:
        return f"今日 {cp:+.2f}%，近期头条：{headlines[0][:40]}。"
    return f"今日 {cp:+.2f}%，无重大新闻，可能跟大盘/板块走势相关。"


# ─────────────────────────────────────────────────────────────────────────────
# Composite scores overview — for each watchlist ticker, compute a 0-100
# CompositeScore from financials + DCF artifact. Catalyst sub-score is left
# at baseline (50) because classifying news per ticker on every dashboard
# visit would burn LLM credits.
# ─────────────────────────────────────────────────────────────────────────────


class ScoresOverviewRequest(BaseModel):
    watchlist: list[str] = []


class ScoreOverviewItem(BaseModel):
    ticker: str
    total: int | None  # null when no inputs at all
    signal: str | None
    fundamental: int | None
    valuation: int | None
    catalyst: int | None
    sentiment: int | None
    breakdown: dict[str, str]
    current_price: float | None


class ScoresOverviewResponse(BaseModel):
    items: list[ScoreOverviewItem]  # sorted by total DESC, nulls last
    generated_at: float


_SCORES_CACHE: dict[str, tuple[float, ScoresOverviewResponse]] = {}
_SCORES_TTL = 30 * 60.0  # 30 min — fundamentals/DCF don't shift fast


@router.post("/scores-overview", response_model=ScoresOverviewResponse)
async def scores_overview(
    payload: ScoresOverviewRequest, request: Request
) -> ScoresOverviewResponse:
    """For each watchlist ticker, compute a CompositeScore from cached inputs.

    Reuses DCF artifact (same as valuation-overview) + financials endpoint.
    Skips catalyst sub-score input — running classify_news per ticker on
    every dashboard load would be too expensive. The frontend can pick the
    top scorer to spotlight.
    """
    deps = getattr(request.app.state, "deps", None)
    if deps is None:
        raise HTTPException(status_code=503, detail="Backend deps not initialized")

    watchlist = [t.upper().strip() for t in payload.watchlist if t.strip()][:8]
    cache_key = ",".join(sorted(watchlist))
    now = time.time()
    cached = _SCORES_CACHE.get(cache_key)
    if cached and now - cached[0] < _SCORES_TTL:
        return cached[1]

    store = request.app.state.artifact_store

    async def _resolve(ticker: str) -> ScoreOverviewItem:
        from finagent.engine.compute.composite_score import (
            ScoreRequest,
            calculate_composite_score,
        )
        from finagent.engine.data.types import DataType

        # Fan out: price + financials + DCF artifact lookup in parallel
        async def _price() -> float | None:
            try:
                res = await deps.data_layer.fetch(DataType.PRICE, ticker)
                p = getattr(res, "data", None) or res
                raw = getattr(p, "current_price", None) or (
                    p.get("current_price") if isinstance(p, dict) else None
                )
                return float(raw) if isinstance(raw, (int, float)) and raw > 0 else None
            except (ProviderError, httpx.HTTPError, asyncio.TimeoutError, ValueError, KeyError):
                return None

        async def _fin() -> dict[str, Any]:
            try:
                res = await deps.data_layer.fetch(DataType.FINANCIALS, ticker)
                data = getattr(res, "data", None) or res
                if hasattr(data, "model_dump"):
                    dumped = data.model_dump()
                    return dumped if isinstance(dumped, dict) else {}
                return data if isinstance(data, dict) else {}
            except (ProviderError, httpx.HTTPError, asyncio.TimeoutError, ValueError, KeyError):
                return {}

        async def _dcf_implied() -> float | None:
            try:
                summaries = await store.list_by_ticker(
                    ticker=ticker, type="dcf", include_archived=False, limit=1
                )
            except (OSError, ValueError, KeyError):
                return None
            if not summaries:
                return None
            try:
                artifact = await store.get(summaries[0].id)
                if not artifact:
                    return None
                val = (artifact.outputs.structured or {}).get("implied_price")
                return float(val) if isinstance(val, (int, float)) and val > 0 else None
            except (OSError, ValueError, KeyError, AttributeError):
                return None

        current, fin, implied = await asyncio.gather(_price(), _fin(), _dcf_implied())

        income = fin.get("income", {}) if isinstance(fin, dict) else {}
        market = fin.get("market", {}) if isinstance(fin, dict) else {}

        revenue = income.get("revenue") if isinstance(income, dict) else None
        gross_profit = income.get("gross_profit") if isinstance(income, dict) else None
        gross_margin = (
            float(gross_profit) / float(revenue)
            if isinstance(revenue, (int, float))
            and revenue > 0
            and isinstance(gross_profit, (int, float))
            else None
        )

        revenue_growth = income.get("revenue_growth_yoy") if isinstance(income, dict) else None
        pe_ratio = market.get("pe_ratio") if isinstance(market, dict) else None

        dcf_upside = (
            (implied - current) / current if current is not None and implied is not None else None
        )

        try:
            req = ScoreRequest(
                pe_ratio=float(pe_ratio) if isinstance(pe_ratio, (int, float)) else None,
                gross_margin=gross_margin,
                revenue_growth_yoy=(
                    float(revenue_growth) if isinstance(revenue_growth, (int, float)) else None
                ),
                dcf_upside_pct=dcf_upside,
            )
            score = calculate_composite_score(req)
            return ScoreOverviewItem(
                ticker=ticker,
                total=score.total,
                signal=score.signal,
                fundamental=score.fundamental,
                valuation=score.valuation,
                catalyst=score.catalyst,
                sentiment=score.sentiment,
                breakdown=score.breakdown,
                current_price=current,
            )
        except (ValidationError, ValueError) as e:
            logger.debug("score calc %s: %s", ticker, e)
            return ScoreOverviewItem(
                ticker=ticker,
                total=None,
                signal=None,
                fundamental=None,
                valuation=None,
                catalyst=None,
                sentiment=None,
                breakdown={},
                current_price=current,
            )

    items = await asyncio.gather(*[_resolve(t) for t in watchlist])
    items_sorted = sorted(
        items,
        key=lambda x: (x.total is None, -(x.total or 0)),
    )
    response = ScoresOverviewResponse(items=items_sorted, generated_at=now)
    _SCORES_CACHE[cache_key] = (now, response)
    return response


# ─────────────────────────────────────────────────────────────────────────────
# Landing-page banner: cross-ticker hit-rate + recent research
# ─────────────────────────────────────────────────────────────────────────────


class HitRateBucket(BaseModel):
    """One verdict-bucket (or overall) hit-rate snapshot."""

    n_total: int
    n_closed: int
    n_hit: int
    hit_rate: float | None
    """null when n_closed == 0 (sample too small)."""


class HitRateOverview(BaseModel):
    """Response for /api/dashboard/hit-rate."""

    window: str  # "30d" | "90d" | "all"
    sample_window_days: int | None
    overall: HitRateBucket
    by_verdict: dict[str, HitRateBucket]  # always has BUY / HOLD / SELL keys
    generated_at: datetime


class RecentResearchItem(BaseModel):
    """One row in /api/dashboard/recent-research."""

    artifact_id: str
    ticker: str | None
    cross_tickers: list[str]
    type: str
    headline: str
    verdict: str | None
    entry_price: float | None
    target_price: float | None
    current_price: float | None
    delta_to_target_pct: float | None
    signal: str | None  # "hit" | "watching" | "failed" | null
    created_at: datetime
    age_label: str


class RecentResearchResponse(BaseModel):
    items: list[RecentResearchItem]
    total_in_store: int
    generated_at: datetime


# Simple TTL caches — landing page makes both calls on cold load; one minute
# is short enough to feel live and long enough to absorb a refresh storm.
_HIT_RATE_CACHE: dict[tuple[str, str], tuple[float, HitRateOverview]] = {}
_RECENT_CACHE: dict[tuple[int, bool], tuple[float, RecentResearchResponse]] = {}
_LANDING_CACHE_TTL_S = 60.0


@router.get("/hit-rate", response_model=HitRateOverview)
async def hit_rate(
    request: Request,
    window: str = "all",
    verdict_filter: str = "all",
) -> HitRateOverview:
    """Cross-ticker hit-rate buckets for the /stocks landing banner.

    `window`:        "30d" | "90d" | "all" (default "all")
    `verdict_filter`: "BUY" | "HOLD" | "SELL" | "all" — narrows the artifacts
                      *before* the overall / by_verdict roll-up so a focused
                      view (e.g. only BUY calls) still shows verdict slices.

    The endpoint never returns 500 for sparse data — empty buckets come back
    as `hit_rate=null`. UI renders a "样本不足" hint in that case.
    """
    if window not in ("30d", "90d", "all"):
        raise HTTPException(status_code=400, detail="window must be 30d|90d|all")
    if verdict_filter not in ("BUY", "HOLD", "SELL", "all"):
        raise HTTPException(status_code=400, detail="verdict_filter must be BUY|HOLD|SELL|all")

    cache_key = (window, verdict_filter)
    now_ts = time.time()
    cached = _HIT_RATE_CACHE.get(cache_key)
    if cached and now_ts - cached[0] < _LANDING_CACHE_TTL_S:
        return cached[1]

    deps = getattr(request.app.state, "deps", None)
    if deps is None or deps.artifact_store is None:
        raise HTTPException(status_code=503, detail="Backend deps not initialized")
    store = deps.artifact_store

    inputs = await _collect_signal_inputs(store, verdict_filter)
    from finagent.engine.aggregations.hit_rate_overview import (
        Window,
        compute_hit_rate_overview,
    )

    stats = compute_hit_rate_overview(
        artifacts=inputs,
        window=window,  # type: ignore[arg-type]
    )

    overview = HitRateOverview(
        window=stats.window,
        sample_window_days=stats.sample_window_days,
        overall=HitRateBucket(
            n_total=stats.overall.n_total,
            n_closed=stats.overall.n_closed,
            n_hit=stats.overall.n_hit,
            hit_rate=stats.overall.hit_rate,
        ),
        by_verdict={
            k: HitRateBucket(
                n_total=v.n_total,
                n_closed=v.n_closed,
                n_hit=v.n_hit,
                hit_rate=v.hit_rate,
            )
            for k, v in stats.by_verdict.items()
        },
        generated_at=stats.generated_at,
    )
    _HIT_RATE_CACHE[cache_key] = (now_ts, overview)
    # Mark Window import as used (the type alias keeps mypy happy on the
    # comma-separated import above; the cast is just for ergonomics).
    _ = Window
    return overview


@router.get("/recent-research", response_model=RecentResearchResponse)
async def recent_research(
    request: Request,
    limit: int = 5,
    include_archived: bool = False,
) -> RecentResearchResponse:
    """Top-N recent artifacts for the /stocks landing strip.

    Each row carries the lazily-computed signal verdict + a friendly
    `age_label` so the UI does no clock math.
    """
    if limit < 1 or limit > 20:
        raise HTTPException(status_code=400, detail="limit must be 1..20")

    cache_key = (limit, include_archived)
    now_ts = time.time()
    cached = _RECENT_CACHE.get(cache_key)
    if cached and now_ts - cached[0] < _LANDING_CACHE_TTL_S:
        return cached[1]

    deps = getattr(request.app.state, "deps", None)
    if deps is None or deps.artifact_store is None:
        raise HTTPException(status_code=503, detail="Backend deps not initialized")
    store = deps.artifact_store

    summaries = await store.list_by_ticker(
        ticker=None,
        include_archived=include_archived,
        limit=200,  # over-fetch so we have headroom after dropping signal-less entries
    )
    total_in_store = len(summaries)
    if not summaries:
        empty = RecentResearchResponse(
            items=[], total_in_store=0, generated_at=datetime.now(tz=timezone.utc)
        )
        _RECENT_CACHE[cache_key] = (now_ts, empty)
        return empty

    # Need top-N by date *before* fetching prices (price call is the bottleneck).
    summaries.sort(key=lambda s: s.created_at, reverse=True)
    head = summaries[: max(limit * 2, limit)]  # slight overshoot for verdict / headline lookups
    tickers = sorted({s.ticker for s in head if s.ticker})

    from finagent.engine.data.quote_batch import fetch_quotes_batch

    try:
        quotes = await asyncio.to_thread(fetch_quotes_batch, tickers)
    except (ImportError, AttributeError, ValueError, TypeError, OSError):
        logger.exception("Quote batch failed for recent-research")
        quotes = dict.fromkeys(tickers)

    inputs = await _build_recent_inputs(store, head, quotes, limit)

    from finagent.engine.aggregations.recent_research import assemble_recent_research

    views = assemble_recent_research(inputs=inputs, limit=limit)

    items = [
        RecentResearchItem(
            artifact_id=v.artifact_id,
            ticker=v.ticker,
            cross_tickers=list(v.cross_tickers),
            type=v.type,
            headline=v.headline,
            verdict=v.verdict,
            entry_price=v.entry_price,
            target_price=v.target_price,
            current_price=v.current_price,
            delta_to_target_pct=v.delta_to_target_pct,
            signal=v.signal,
            created_at=v.created_at,
            age_label=v.age_label,
        )
        for v in views
    ]

    response = RecentResearchResponse(
        items=items,
        total_in_store=total_in_store,
        generated_at=datetime.now(tz=timezone.utc),
    )
    _RECENT_CACHE[cache_key] = (now_ts, response)
    return response


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — assembly between ArtifactStore + aggregation modules
# ─────────────────────────────────────────────────────────────────────────────


async def _collect_signal_inputs(
    store: Any,
    verdict_filter: str,
) -> list[Any]:
    """Walk artifacts → ArtifactSignalInput list (with live prices).

    `verdict_filter` is applied here so the overview's overall bucket
    reflects the filter — without this the UI's "show only my BUYs" toggle
    would still mix HOLD/SELL into overall.
    """
    from finagent.artifact.summary_extractor import extract_verdict
    from finagent.engine.aggregations.hit_rate_overview import ArtifactSignalInput
    from finagent.engine.data.quote_batch import fetch_quotes_batch

    summaries = await store.list_by_ticker(
        ticker=None, include_archived=False, limit=500
    )
    if not summaries:
        return []

    # Per-artifact verdict requires loading the full Artifact; we batch by
    # artifact_id so the same json file isn't read twice.
    verdicts: dict[str, str | None] = {}
    headlines: dict[str, str] = {}
    for s in summaries:
        if s.id in verdicts:
            continue
        art = await store.get(s.id)
        verdicts[s.id] = extract_verdict(art) if art is not None else None
        headlines[s.id] = s.headline

    tickers = sorted({s.ticker for s in summaries if s.ticker})
    try:
        quotes = await asyncio.to_thread(fetch_quotes_batch, tickers)
    except (ImportError, AttributeError, ValueError, TypeError, OSError):
        logger.exception("Quote batch failed for hit-rate overview")
        quotes = dict.fromkeys(tickers)

    out: list[ArtifactSignalInput] = []
    for s in summaries:
        verdict = verdicts.get(s.id)
        if verdict_filter != "all" and verdict != verdict_filter:
            continue
        current = quotes.get(s.ticker) if s.ticker else None
        out.append(
            ArtifactSignalInput(
                entry_price=s.entry_price,
                target_price=s.target_price,
                current_price=current,
                entry_date=s.created_at,
                target_date=s.target_date,
                verdict=verdict,
            )
        )
    return out


async def _build_recent_inputs(
    store: Any,
    summaries: list[Any],
    quotes: dict[str, float | None],
    _limit: int,
) -> list[Any]:
    """Convert ArtifactSummary[] → RecentResearchInput[] with verdicts loaded."""
    from finagent.artifact.summary_extractor import extract_verdict
    from finagent.engine.aggregations.recent_research import RecentResearchInput

    out: list[RecentResearchInput] = []
    for s in summaries:
        art = await store.get(s.id)
        verdict = extract_verdict(art) if art is not None else None
        current = quotes.get(s.ticker) if s.ticker else None
        out.append(
            RecentResearchInput(
                artifact_id=s.id,
                ticker=s.ticker,
                cross_tickers=tuple(s.cross_tickers),
                type=s.type,
                headline=s.headline,
                verdict=verdict,
                entry_price=s.entry_price,
                target_price=s.target_price,
                target_date=s.target_date,
                current_price=current,
                created_at=s.created_at,
            )
        )
    return out
