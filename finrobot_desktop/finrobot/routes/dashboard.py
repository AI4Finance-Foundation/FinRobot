"""Dashboard routes — AI today summary + valuation outliers for the home page."""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.requests import Request

from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.quote_cache import Quote

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


_HIT_RATE_SAMPLE_CAP = 500
"""Max summaries the hit-rate aggregation reads — bounds compute cost. When the
store holds more than this, the buckets reflect only the latest 500 artifacts;
``HitRateOverview.is_sampled`` discloses that instead of pretending it's the
full track record."""


class HitRateOverview(BaseModel):
    """Response for /api/dashboard/hit-rate."""

    window: str  # "30d" | "90d" | "all"
    overall: HitRateBucket
    by_verdict: dict[str, HitRateBucket]  # always has BUY / HOLD / SELL keys
    generated_at: datetime
    is_sampled: bool = False
    """True when the store exceeded the sample cap, so buckets cover only the
    latest ``sample_size`` artifacts rather than the full track record."""
    sample_size: int = _HIT_RATE_SAMPLE_CAP
    """The cap applied to the underlying summary scan (compute-cost bound)."""


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

# _HIT_RATE_CACHE keys embed the caller-supplied ``tickers`` scope verbatim, so
# the key space is attacker/typo-unbounded (every distinct comma-list is a new
# entry that lives forever — TTL only stops REUSE, not growth). Cap the dict:
# on insert past the cap, drop expired entries first, then oldest-by-timestamp.
# 64 comfortably covers window×coverage-group combinations a desktop ever uses.
# _RECENT_CACHE needs no cap — its key space is bounded by construction
# (limit ∈ 1..20 × include_archived bool → ≤ 40 keys).
_HIT_RATE_CACHE_MAX = 64


def _hit_rate_cache_put(key: str, entry: tuple[float, HitRateOverview]) -> None:
    if key not in _HIT_RATE_CACHE and len(_HIT_RATE_CACHE) >= _HIT_RATE_CACHE_MAX:
        now_ts = entry[0]
        expired = [
            k for k, (ts, _) in _HIT_RATE_CACHE.items() if now_ts - ts >= _LANDING_CACHE_TTL_S
        ]
        for k in expired:
            del _HIT_RATE_CACHE[k]
        while len(_HIT_RATE_CACHE) >= _HIT_RATE_CACHE_MAX:
            oldest = min(_HIT_RATE_CACHE, key=lambda k: _HIT_RATE_CACHE[k][0])
            del _HIT_RATE_CACHE[oldest]
    _HIT_RATE_CACHE[key] = entry


def invalidate_dashboard_caches() -> None:
    """Drop the landing-page TTL caches so the next GET recomputes from store.

    Artifact-lifecycle mutations (a run completing and saving its artifact, a
    delete, a mark-viewed that bumps the strip's ordering) must surface on the
    dashboard immediately — not after the 60s ``_LANDING_CACHE_TTL_S`` window
    expires. The lifecycle call sites (``routes.runs`` on RunCompleted,
    ``routes.artifacts`` on delete/view) call this so "just ran a report, don't
    see it" never happens. The TTL stays as a backstop for everything that does
    NOT route through an explicit invalidation (e.g. background stale-archive).
    """
    _HIT_RATE_CACHE.clear()
    _RECENT_CACHE.clear()


@router.get("/hit-rate", response_model=HitRateOverview)
async def hit_rate(
    request: Request,
    window: str = "all",
    tickers: str | None = None,
) -> HitRateOverview:
    """Hit-rate buckets for the track-record panel.

    `window`: "30d" | "90d" | "all" (default "all")
    `tickers`: optional comma-separated symbols to scope the stats to a coverage
        group (BUG-055). Omitted → global (all artifacts). An empty value scopes
        to the empty set → null buckets (an empty group has no track record).

    The endpoint never returns 500 for sparse data — empty buckets come back
    as `hit_rate=null`. UI renders a "样本不足" hint in that case.
    """
    if window not in ("30d", "90d", "all"):
        raise HTTPException(status_code=400, detail="window must be 30d|90d|all")

    ticker_set: set[str] | None = None
    if tickers is not None:
        ticker_set = {t.strip().upper() for t in tickers.split(",") if t.strip()}

    now_ts = time.time()
    cache_key = window if ticker_set is None else f"{window}|{','.join(sorted(ticker_set))}"
    cached = _HIT_RATE_CACHE.get(cache_key)
    if cached and now_ts - cached[0] < _LANDING_CACHE_TTL_S:
        return cached[1]

    deps = getattr(request.app.state, "deps", None)
    if deps is None or deps.artifact_store is None:
        raise HTTPException(status_code=503, detail="Backend deps not initialized")
    store = deps.artifact_store

    inputs = await _collect_signal_inputs(store, deps.data_layer, ticker_set)
    # Disclose sampling honestly (BUG-039): the cap only loses data when the
    # IN-scope, IN-window artifact count exceeds it. Compare against the SAME
    # population the buckets describe — scoped to `ticker_set` and cut to
    # `window` — not the global all-time COUNT(*). A fully-captured 30d window
    # (e.g. 40 in-window artifacts, 700 in store) is then honestly is_sampled=
    # False instead of being mislabeled 'partial'.
    from finrobot.engine.aggregations.hit_rate_overview import (
        _WINDOW_DAYS,
        compute_hit_rate_overview,
    )

    window_days = _WINDOW_DAYS[window]  # type: ignore[index]
    cutoff = (
        datetime.now(tz=timezone.utc) - timedelta(days=window_days)
        if window_days is not None
        else None
    )
    scoped_windowed_count = await store.count(
        include_archived=False, tickers=ticker_set, created_after=cutoff
    )
    is_sampled = scoped_windowed_count > _HIT_RATE_SAMPLE_CAP

    stats = compute_hit_rate_overview(
        artifacts=inputs,
        window=window,  # type: ignore[arg-type]
    )

    overview = HitRateOverview(
        is_sampled=is_sampled,
        sample_size=_HIT_RATE_SAMPLE_CAP,
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
    _hit_rate_cache_put(cache_key, (now_ts, overview))
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
    # Full-store aggregates — NOT len(summaries). The summary list is capped at
    # 500 (compute bound for the card-assembly fan-out); past the cap
    # len(summaries) would silently report "500" as the total. The header
    # counts must reflect the true store, so query them directly.
    total_in_store = await store.count(include_archived=include_archived)
    distinct_ticker_count = await store.distinct_ticker_count(include_archived=include_archived)
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

    # Signal-lamp prices for top-N — CACHE-ONLY, never a cold provider call.
    # The strip's cards are DB-backed and must not block on a yfinance/FMP
    # round-trip (pre-fix this endpoint paid up to the 8s warmup budget on
    # every cold boot — see ADR/landing). Warm tickers light their lamp now;
    # cold ones come back None and fill on the frontend's post-warmup refetch
    # once the lifespan warmup has populated the shared QuoteCache. Live price
    # is a progressive enhancement here, not a render dependency — that is why
    # this uses fetch_quotes_cache_only while /hit-rate (whose bucket math
    # genuinely needs warm quotes) still cold-fetches.
    from finrobot.engine.data.quote_batch import fetch_quotes_cache_only

    try:
        quotes = await fetch_quotes_cache_only(top_tickers)
    except _QUOTE_BATCH_DEGRADABLE:
        # A wedged L1/L2 read must never 500 the landing — fall back to None
        # prices (lamps pending) instead.
        logger.exception("Cache-only quote read failed for recent-research")
        quotes = dict.fromkeys(top_tickers)

    # Each cache-only quote carries its own currency (Quote.price + Quote.currency),
    # so the latest-run signal lamp (_signal_for → compute_signal) can compare it
    # against the USD entry/target in USD. Convert to a USD float per ticker: USD →
    # as-is; foreign + FX → converted; foreign + FX-miss OR unknown-currency →
    # None (lamp pending — never assume USD). No cold provider call: the cache-only
    # contract holds because the currency rode in WITH the warm quote.
    usd_quotes = await _signal_prices_usd(quotes, deps.data_layer)

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
        current = usd_quotes.get(ticker)
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


async def _collect_signal_inputs(
    store: Any, data_layer: Any, tickers: set[str] | None = None
) -> list[Any]:
    """Walk artifact summaries → ArtifactSignalInput list (with live prices).

    Uses ``ArtifactSummary.verdict`` directly — does NOT reload the full
    artifact. The summary column is populated at save time
    (see ``SqliteArtifactStore.save`` → ``extract_verdict``), so for
    N artifacts the route does 1 ``list_by_ticker`` query + 1 cached
    quote batch instead of the legacy 1 + N JSON file reads.
    """
    from finrobot.engine.aggregations.hit_rate_overview import ArtifactSignalInput
    from finrobot.engine.data.quote_batch import fetch_quotes_batch_cached

    if tickers is not None:
        # Scope to a coverage group's members (BUG-055/BUG-018). Push the filter
        # into SQL so the cap applies to the SCOPED page — a group whose reports
        # predate the global newest-N page is no longer evicted before it can be
        # seen. An EMPTY set (an empty group) yields no inputs → null hit-rate,
        # not the global one.
        summaries = await store.list_by_ticker(
            tickers=tickers, include_archived=False, limit=_HIT_RATE_SAMPLE_CAP
        )
    else:
        summaries = await store.list_by_ticker(
            ticker=None, include_archived=False, limit=_HIT_RATE_SAMPLE_CAP
        )
    if not summaries:
        return []

    quote_tickers = sorted({s.ticker for s in summaries if s.ticker})
    try:
        quotes = await fetch_quotes_batch_cached(quote_tickers, data_layer)
    except _QUOTE_BATCH_DEGRADABLE:
        # Without live prices the aggregator can't classify signals so
        # buckets degrade to null hit-rate — UI shows "样本不足" which is
        # far better than a 500 black-out of the entire landing banner.
        logger.exception("Quote batch failed for hit-rate overview")
        quotes = dict.fromkeys(quote_tickers)

    # Each quote carries its own currency (Quote.price + Quote.currency), so
    # compute_signal can compare it against the canonical-USD entry/target in USD.
    # For a foreign LOCAL listing (2330.TW, quote=TWD) the raw price would otherwise
    # be compared against a USD target → mis-bucketed verdicts (same cross-currency
    # hole fixed in coverage + valuation). USD / pure-ADR → strict no-op.
    usd_by_ticker = await _signal_prices_usd(quotes, data_layer)
    return [
        ArtifactSignalInput(
            entry_price=s.entry_price,
            target_price=s.target_price,
            current_price=usd_by_ticker.get(s.ticker) if s.ticker else None,
            entry_date=s.created_at,
            target_date=s.target_date,
            verdict=s.verdict,
        )
        for s in summaries
    ]


async def _signal_prices_usd(
    quotes: dict[str, Quote | None],
    data_layer: Any,
) -> dict[str, float | None]:
    """Convert each carried quote to a USD price — the basis entry/target sit on —
    for the signal-lamp / hit-rate comparison.

    The currency travels WITH the price (``Quote.currency``, stamped by the QUOTE
    provider from its own source), so there is no second currency lookup and no
    quote-batch-warm + canonical-cold mismatch (the strip mis-lit-lamp root fix):
      - USD quote (US issuer, pure ADR) → price as-is, strict no-op, no FX call.
      - foreign quote + FX available → price × ``DataLayer.fx_rate_to_usd``.
      - foreign quote + FX miss, OR unknown currency (provider couldn't resolve) →
        None, so the artifact's signal drops (``_signal_for`` treats None as
        insufficient data). NEVER assume USD on an unknown currency, never fabricate
        a mixed-currency comparison.
    """
    out: dict[str, float | None] = {}
    for ticker, quote in quotes.items():
        price = quote.price if quote is not None else None
        if price is None or price <= 0:
            out[ticker] = price
            continue
        ccy = (quote.currency or "").upper() if quote is not None else ""
        if ccy == "USD":
            out[ticker] = price
            continue
        if not ccy:
            # Currency unknown — cannot align to USD; abstain rather than assume USD.
            out[ticker] = None
            continue
        try:
            rate = await data_layer.fx_rate_to_usd(ccy)
        except _QUOTE_BATCH_DEGRADABLE + (ProviderError,) as exc:
            logger.info(
                "signal-price FX %s→USD failed for %s — dropping signal: %s", ccy, ticker, exc
            )
            out[ticker] = None
            continue
        out[ticker] = price * rate
    return out
