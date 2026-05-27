"""Dashboard routes — AI today summary + valuation outliers for the home page."""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.requests import Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# Exceptions where the landing endpoints should fall back to None-quotes
# instead of 500-ing. The hit-rate / recent-research routes get hammered by
# the desktop shell on every render — a 30-hour aiosqlite worker can wedge
# in arbitrary ways, and a one-shot fetcher import/AttributeError must not
# black out the entire landing banner. Architecturally we still avoid bare
# `except Exception:`; this constant enumerates the concrete failure modes
# we have observed (sqlite worker death, yfinance import gone after upgrade,
# asyncio loop teardown, network OS errors).
_QUOTE_BATCH_DEGRADABLE = (
    sqlite3.Error,
    RuntimeError,
    OSError,
    ValueError,
    TypeError,
    ImportError,
    AttributeError,
)


# ─────────────────────────────────────────────────────────────────────
# Removed 2026-05-27: /valuation-overview, /explain-move/{ticker},
# /scores-overview. All three were watchlist-driven cards no UI surface
# still calls; per the cleanup audit. Landing keeps hit-rate +
# recent-research only; per-ticker drill-downs happen in the workspace.
# ─────────────────────────────────────────────────────────────────────



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
    overall: HitRateBucket
    by_verdict: dict[str, HitRateBucket]  # always has BUY / HOLD / SELL keys
    generated_at: datetime


class RecentTickerRun(BaseModel):
    """One clickable row inside a ticker card."""

    artifact_id: str
    type: str
    verdict: str | None
    created_at: datetime
    age_label: str


class RecentTickerItem(BaseModel):
    """One card in /api/dashboard/recent-research — ticker drawer.

    2026-05-23 (v2): card now exposes the ticker's recent runs as discrete
    rows. UI routes every row to `/stocks/:ticker/runs/:artifact_id` so each
    individual report is one click away — the 1-ticker-to-N-reports
    relationship is visible, not collapsed into chips.

    `runs` is capped at MAX_RUNS_PER_TICKER (5); `run_count` is the true
    total so the UI can render a "+ N 更多" footer pointing at the
    workspace's full timeline.
    """

    ticker: str
    run_count: int
    runs: list[RecentTickerRun]  # newest first, max MAX_RUNS_PER_TICKER
    latest_signal: str | None  # header lamp; "hit" | "watching" | "failed" | null
    latest_at: datetime


class RecentResearchResponse(BaseModel):
    items: list[RecentTickerItem]
    total_in_store: int  # total artifact count (NOT distinct ticker count)
    distinct_ticker_count: int  # distinct tickers across all artifacts
    generated_at: datetime


# Simple TTL caches — landing page makes both calls on cold load; one minute
# is short enough to feel live and long enough to absorb a refresh storm.
_HIT_RATE_CACHE: dict[str, tuple[float, HitRateOverview]] = {}
_RECENT_CACHE: dict[tuple[int, bool], tuple[float, RecentResearchResponse]] = {}
_LANDING_CACHE_TTL_S = 60.0


@router.get("/hit-rate", response_model=HitRateOverview)
async def hit_rate(
    request: Request,
    window: str = "all",
) -> HitRateOverview:
    """Cross-ticker hit-rate buckets for the /stocks landing banner.

    `window`: "30d" | "90d" | "all" (default "all")

    The endpoint never returns 500 for sparse data — empty buckets come back
    as `hit_rate=null`. UI renders a "样本不足" hint in that case.
    """
    if window not in ("30d", "90d", "all"):
        raise HTTPException(status_code=400, detail="window must be 30d|90d|all")

    now_ts = time.time()
    cached = _HIT_RATE_CACHE.get(window)
    if cached and now_ts - cached[0] < _LANDING_CACHE_TTL_S:
        return cached[1]

    deps = getattr(request.app.state, "deps", None)
    if deps is None or deps.artifact_store is None:
        raise HTTPException(status_code=503, detail="Backend deps not initialized")
    store = deps.artifact_store

    inputs = await _collect_signal_inputs(store)
    from finrobot.engine.aggregations.hit_rate_overview import compute_hit_rate_overview

    stats = compute_hit_rate_overview(
        artifacts=inputs,
        window=window,  # type: ignore[arg-type]
    )

    overview = HitRateOverview(
        window=stats.window,
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
    _HIT_RATE_CACHE[window] = (now_ts, overview)
    return overview


@router.get("/recent-research", response_model=RecentResearchResponse)
async def recent_research(
    request: Request,
    limit: int = 5,
    include_archived: bool = False,
) -> RecentResearchResponse:
    """Top-N **tickers** for the /stocks landing strip (drawer cards).

    For each top-N ticker, load up to MAX_RUNS_PER_TICKER artifacts so each
    surfaced row carries its own verdict. Worst case = limit × 5 reads
    (e.g. limit=5 → ≤25 reads), then 60s cached.
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
        limit=500,
    )
    total_in_store = len(summaries)
    distinct_ticker_count = len({s.ticker for s in summaries if s.ticker})
    if not summaries:
        empty = RecentResearchResponse(
            items=[],
            total_in_store=0,
            distinct_ticker_count=0,
            generated_at=datetime.now(tz=timezone.utc),
        )
        _RECENT_CACHE[cache_key] = (now_ts, empty)
        return empty

    # Group by ticker → pick top-N tickers by their latest-summary timestamp.
    from collections import defaultdict

    by_ticker: dict[str, list[Any]] = defaultdict(list)
    for s in summaries:
        if s.ticker:
            by_ticker[s.ticker].append(s)
    top_tickers = sorted(
        by_ticker.keys(),
        key=lambda t: max(s.created_at for s in by_ticker[t]),
        reverse=True,
    )[:limit]

    # Live quotes for top-N only — cached batched call. The QuoteCache
    # singleton means the parallel /api/dashboard/hit-rate call within the
    # same 60s TTL window shares this batch (no double-fetch from yfinance).
    from finrobot.engine.data.quote_batch import fetch_quotes_batch_cached

    try:
        quotes = await fetch_quotes_batch_cached(top_tickers)
    except _QUOTE_BATCH_DEGRADABLE:
        # Live quotes are decorative for this endpoint — the page is fully
        # readable without them. Any failure (network / sqlite worker died /
        # asyncio teardown / yfinance import gone) falls back to None
        # prices instead of 500-ing the entire landing.
        logger.exception("Quote batch failed for recent-research")
        quotes = dict.fromkeys(top_tickers)

    # Per-row verdict comes straight from ArtifactSummary.verdict (already
    # extracted at save time, stored as an indexed SQLite column). Older
    # runs only contribute to run_count and link out to the workspace
    # timeline.
    from finrobot.engine.aggregations.recent_research import (
        RecentResearchInput,
        assemble_recent_tickers,
    )

    inputs: list[RecentResearchInput] = []
    for ticker in top_tickers:
        group = sorted(by_ticker[ticker], key=lambda s: s.created_at, reverse=True)
        latest = group[0]
        current = quotes.get(ticker)
        for s in group:
            is_latest = s.id == latest.id
            inputs.append(
                RecentResearchInput(
                    artifact_id=s.id,
                    ticker=s.ticker,
                    cross_tickers=tuple(s.cross_tickers),
                    type=s.type,
                    headline=s.headline,
                    verdict=s.verdict,
                    entry_price=s.entry_price,
                    target_price=s.target_price,
                    target_date=s.target_date,
                    current_price=current if is_latest else None,
                    created_at=s.created_at,
                )
            )

    views = assemble_recent_tickers(inputs=inputs, limit=limit)

    items = [
        RecentTickerItem(
            ticker=v.ticker,
            run_count=v.run_count,
            runs=[
                RecentTickerRun(
                    artifact_id=r.artifact_id,
                    type=r.type,
                    verdict=r.verdict,
                    created_at=r.created_at,
                    age_label=r.age_label,
                )
                for r in v.runs
            ],
            latest_signal=v.latest_signal,
            latest_at=v.latest_at,
        )
        for v in views
    ]

    response = RecentResearchResponse(
        items=items,
        total_in_store=total_in_store,
        distinct_ticker_count=distinct_ticker_count,
        generated_at=datetime.now(tz=timezone.utc),
    )
    _RECENT_CACHE[cache_key] = (now_ts, response)
    return response


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — assembly between ArtifactStore + aggregation modules
# ─────────────────────────────────────────────────────────────────────────────


async def _collect_signal_inputs(store: Any) -> list[Any]:
    """Walk artifact summaries → ArtifactSignalInput list (with live prices).

    Uses ``ArtifactSummary.verdict`` directly — does NOT reload the full
    artifact. The summary column is populated at save time
    (see ``SqliteArtifactStore.save`` → ``extract_verdict``), so for
    N artifacts the route does 1 ``list_by_ticker`` query + 1 cached
    quote batch instead of the legacy 1 + N JSON file reads.
    """
    from finrobot.engine.aggregations.hit_rate_overview import ArtifactSignalInput
    from finrobot.engine.data.quote_batch import fetch_quotes_batch_cached

    summaries = await store.list_by_ticker(
        ticker=None, include_archived=False, limit=500
    )
    if not summaries:
        return []

    tickers = sorted({s.ticker for s in summaries if s.ticker})
    try:
        quotes = await fetch_quotes_batch_cached(tickers)
    except _QUOTE_BATCH_DEGRADABLE:
        # Without live prices the aggregator can't classify signals so
        # buckets degrade to null hit-rate — UI shows "样本不足" which is
        # far better than a 500 black-out of the entire landing banner.
        logger.exception("Quote batch failed for hit-rate overview")
        quotes = dict.fromkeys(tickers)

    return [
        ArtifactSignalInput(
            entry_price=s.entry_price,
            target_price=s.target_price,
            current_price=quotes.get(s.ticker) if s.ticker else None,
            entry_date=s.created_at,
            target_date=s.target_date,
            verdict=s.verdict,
        )
        for s in summaries
    ]


