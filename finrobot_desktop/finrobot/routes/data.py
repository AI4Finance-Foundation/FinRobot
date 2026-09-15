"""Data routes -- thin handlers that parse params, call services, return responses."""

from __future__ import annotations

import logging
import math
from datetime import date, datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
from starlette.requests import Request

from finrobot.routes._ready import ensure_engine_ready

from finrobot.engine.compute.operators.catalyst import (
    cluster_near_duplicates,
    extract_catalysts_from_news,
    rank_catalysts,
)
from finrobot.engine.compute.coordinators.extractor import extract_financial_data
from finrobot.engine.compute.coordinators.historical_extractor import fetch_historical_metrics
from finrobot.engine.compute.coordinators.market import technical_payload
from finrobot.engine.compute.coordinators.news import fetch_news
from finrobot.engine.data.cache import cached_fetch
from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.data.normalize.session import compute_session_state, derive_price_as_of
from finrobot.engine.data.ticker import validate_ticker
from finrobot.engine.data.types import DataType
from finrobot.engine.primitives.market_cap import market_cap_on_live_price
from finrobot.engine.models.earnings_call import EarningsCallList, EarningsCallTranscript
from finrobot.engine.models.financial import (
    CatalystEvent,
    FinancialData,
    HistoricalMetrics,
)
from finrobot.engine.services.market_data import fetch_price_history
from finrobot.ratelimit import enforce_live_data_limit
from finrobot.warning_text import humanize_warnings, safe_error_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/data", tags=["data"])


def _data_http_error(exc: Exception, ticker: str) -> HTTPException:
    """Translate data-layer exceptions into proper HTTP status codes + 中文 detail.

    - ProviderError → 502 Bad Gateway (upstream API failed)
    - ValueError    → 422 Unprocessable Entity (request data invalid / ticker not recognized)

    Detail is Chinese so the desktop UI can surface it directly to retail users
    without an extra translation layer.
    """
    detail = safe_error_text(exc)
    if isinstance(exc, ProviderError):
        return HTTPException(
            status_code=502,
            detail=f"Data source temporarily unavailable ({ticker}): {detail}",
        )
    return HTTPException(
        status_code=422,
        detail=f"Unable to fetch data for {ticker}: {detail}",
    )


def _normalize_ticker_param(ticker: str) -> str:
    """Funnel a path-param ticker through the shared ``validate_ticker`` chokepoint
    so the data routes share ONE ticker definition with the pipeline / CLI /
    compute routes. A bare ``ticker.upper()`` (the prior behaviour) let ``BRK.B``
    and ``BRK-B`` split into two cache / coverage slots for one security AND served
    the dotted form straight to yfinance, which returns no data for it. This
    canonicalizes the share-class dot → hyphen and rejects junk; ValueError → 422."""
    try:
        return validate_ticker(ticker)
    except ValueError as exc:
        raise _data_http_error(exc, ticker.upper()) from exc


def _fmp_degradation_warning(request: Request, provider: str | None) -> str | None:
    """User-visible note when FMP is configured but the data came from yfinance.

    build_data_layer puts FMP first in the chain whenever a key is set, so for
    FMP-served types (FINANCIALS / PRICE) ``provider == yfinance`` despite a
    configured key means the FMP call failed (invalid/expired key, outage,
    circuit open) and the layer silently fell back. The fallback itself is
    correct behaviour — serving stale-keyed users nothing would be worse — but
    it must be VISIBLE: the response already carries ``data_source``, and this
    warning tells the user why it isn't the source they configured. Route-side
    by design: the provider chain (layer.py) stays policy-free.
    """
    settings = getattr(request.app.state.deps, "settings", None)
    if not settings or not getattr(settings, "fmp_api_key", ""):
        return None
    if provider is not None and provider.startswith("yfinance"):
        return (
            "FMP is configured, but this data came from a yfinance fallback. Go to Settings -> Data Sources to test whether the FMP key "
            "is still valid (the layer falls back automatically when the key is invalid or FMP is down)."
        )
    return None


def _with_fmp_degradation_note(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    """Append the FMP-fallback warning to a /price payload when applicable.

    Called at every ``return`` of :func:`get_price` (fresh fetch, route cache,
    provider cache, stale fallbacks) so the note follows the payload no matter
    which path served it.
    """
    raw_source = payload.get("data_source")
    degraded = _fmp_degradation_warning(
        request, raw_source if isinstance(raw_source, str) else None
    )
    warnings = _warning_list(payload.get("warnings"))
    if degraded:
        if degraded not in warnings:
            warnings.append(degraded)
    if warnings or "warnings" in payload:
        payload["warnings"] = _dedupe(humanize_warnings(warnings))
    return payload


@router.get(
    "/{ticker}/catalysts",
    response_model=list[CatalystEvent],
    dependencies=[Depends(ensure_engine_ready)],
)
async def get_catalysts(
    ticker: str,
    request: Request,
    min_importance: int = Query(
        default=3,
        ge=1,
        le=5,
        description="Minimum news importance to become a catalyst (1-5).",
    ),
) -> list[CatalystEvent]:
    """Fetch news, classify via LLM, extract catalyst events, return sorted by impact.

    Pipeline: fetch_news -> classify_news (LLM) -> extract_catalysts -> rank.

    The classify step is a slow (~11–18s) LLM round-trip with no provider cache
    of its own, so the assembled list is cached (DataType.CATALYST, 30 min,
    keyed by min_importance). Warm loads skip the whole pipeline; only a cold
    load (or a stale cache) pays the LLM cost. Caching also stabilises the
    calendar — classification is non-deterministic run-to-run.

    Args:
        ticker: Stock ticker symbol.
        min_importance: Minimum news importance to become a catalyst (1-5).
    """
    enforce_live_data_limit(request)
    deps = request.app.state.deps
    data_layer = deps.data_layer
    cache = data_layer.cache
    ticker_upper = _normalize_ticker_param(ticker)

    async def _fetch_catalysts() -> dict[str, Any]:
        # Lazy: news_classifier pulls the pydantic_ai stack (it runs an LLM); kept
        # off the sidecar cold-start import path (tests/unit/test_cold_import.py).
        from finrobot.engine.analysis.news_classifier import classify_news

        raw_news = await fetch_news(data_layer, ticker_upper)
        if not raw_news:
            return {"catalysts": []}
        classified = await classify_news(raw_news, deps, ticker=ticker_upper)
        events = extract_catalysts_from_news(classified, min_importance=min_importance)
        # Event-level near-duplicate clustering BEFORE ranking — mirrors the research
        # pipeline (equity_research.py). The live calendar previously skipped this, so
        # N variants of the same story ("Apple raises prices") each rendered as a
        # separate catalyst with its own 5/5 impact. Clustering collapses them to one
        # event carrying source_count = cluster size (conservative Jaccard 0.6 / 3-day
        # window, so genuinely distinct events are never merged).
        events = cluster_near_duplicates(events)
        # Single ranking pass: rank_catalysts now keys on abs(expected impact)
        # (the same magnitude compute_expected_impact used), so the previous
        # compute_expected_impact-then-rank_catalysts chain was redundant — and
        # worse, the second sort's old sign-blind key silently overrode the first.
        events = rank_catalysts(events)
        return {"catalysts": [e.model_dump(mode="json") for e in events]}

    try:
        payload = await cached_fetch(
            cache,
            DataType.CATALYST,
            ticker_upper,
            _fetch_catalysts,
            cache_key_suffix=f":{min_importance}",
        )
    except (ValueError, ProviderError) as e:
        raise _data_http_error(e, ticker_upper) from e
    except RuntimeError as e:
        # LLM classification failure must surface as a real 5xx — silently
        # returning [] makes a backend outage indistinguishable from "no
        # catalysts found", which is the failure mode this endpoint exists to
        # avoid. The fetcher raised before cache.set, so nothing is cached.
        logger.error("Catalyst classification failed for %s: %s", ticker_upper, e)
        raise HTTPException(
            status_code=500,
            detail=f"Catalyst classification failed ({ticker_upper}): {e}",
        ) from e

    raw_list = payload.get("catalysts", [])
    return [CatalystEvent.model_validate(item) for item in raw_list]


@router.get(
    "/{ticker}/financials",
    response_model=FinancialData,
    dependencies=[Depends(ensure_engine_ready)],
)
async def get_financials(ticker: str, request: Request) -> FinancialData:
    enforce_live_data_limit(request)
    data_layer: DataLayer = request.app.state.deps.data_layer
    ticker_upper = _normalize_ticker_param(ticker)
    try:
        _fin = await data_layer.fetch_canonical(DataType.FINANCIALS, ticker_upper)
        _price = await data_layer.fetch_canonical(DataType.PRICE, ticker_upper)
    except (ValueError, ProviderError) as e:
        raise _data_http_error(e, ticker_upper) from e
    # fetch_canonical is overloaded on the DataType literal, so _fin / _price are
    # already typed NormalizedFinancials / NormalizedPrice — no narrowing needed.
    # Cross-validation warnings already merged into fin/price.warnings by
    # fetch_canonical, and extract_financial_data carries them through.
    extracted = extract_financial_data(_fin, _price)
    degraded = _fmp_degradation_warning(request, extracted.data_source)
    if degraded and degraded not in extracted.warnings:
        extracted.warnings.append(degraded)
    extracted.warnings = _dedupe(humanize_warnings(extracted.warnings))
    return extracted


# Accepted chart windows. ``period`` only scopes the route cache key — the
# fetcher always pulls the provider's ~1y PRICE window — so this is an input
# allow-list (unknown values → 422) rather than a data-range selector. Keep it
# to the standard yfinance vocabulary the chart UI can offer.
PricePeriod = Literal["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"]


@router.get("/{ticker}/price", dependencies=[Depends(ensure_engine_ready)])
async def get_price(ticker: str, request: Request, period: PricePeriod = "1y") -> dict[str, Any]:
    """Price data with configurable time period.

    Cached for 15 minutes (TTL set in cache._TTL_SECONDS[DataType.PRICE]).
    The cache key includes ``period`` so /price?period=1y and /price?period=5d
    don't collide.

    Error mapping:
      - invalid ``period`` → 422 (Literal validation, before any fetch)
      - ValueError         → 422 (invalid ticker)
      - ProviderError      → 502 (yfinance service down)
    """
    enforce_live_data_limit(request)
    data_layer = request.app.state.deps.data_layer
    cache = data_layer.cache
    ticker_upper = _normalize_ticker_param(ticker)
    route_cache_key = f"{ticker_upper}:{period}"
    cached = await cache.get(DataType.PRICE, route_cache_key)
    if cached is not None and not cached.is_stale:
        cached_payload = dict(cast(dict[str, Any], cached.data.data))
        return _with_fmp_degradation_note(
            request,
            await _enrich_price_payload_from_financial_cache(cache, ticker_upper, cached_payload),
        )

    if period == "1y":
        provider_cached = await _provider_price_cache_payload(cache, ticker_upper)
        if provider_cached is not None:
            return _with_fmp_degradation_note(request, provider_cached)

    try:
        payload = await cached_fetch(
            cache,
            DataType.PRICE,
            ticker_upper,
            lambda: fetch_price_history(data_layer, ticker_upper),
            cache_key_suffix=f":{period}",
        )
        return _with_fmp_degradation_note(
            request,
            await _enrich_price_payload_from_financial_cache(cache, ticker_upper, payload),
        )
    except (ValueError, ProviderError) as e:
        if cached is not None:
            stale_payload = dict(cached.data.data)
            raw_warnings = stale_payload.get("warnings", [])
            warnings = list(raw_warnings) if isinstance(raw_warnings, list) else []
            warnings.insert(
                0, f"Data source request failed; showing cached quotes ({ticker_upper} / {period})."
            )
            stale_payload["warnings"] = _dedupe(warnings)
            return _with_fmp_degradation_note(
                request,
                await _enrich_price_payload_from_financial_cache(
                    cache, ticker_upper, stale_payload
                ),
            )
        if period == "1y":
            stale_provider = await _provider_price_cache_payload(
                cache,
                ticker_upper,
                include_stale=True,
                warning=f"Data source request failed; showing cached quotes ({ticker_upper} / provider).",
            )
            if stale_provider is not None:
                return _with_fmp_degradation_note(request, stale_provider)
        raise _data_http_error(e, ticker_upper) from e


@router.get(
    "/{ticker}/historical",
    response_model=HistoricalMetrics,
    dependencies=[Depends(ensure_engine_ready)],
)
async def get_historical(ticker: str, request: Request) -> HistoricalMetrics:
    """Multi-year historical financial metrics including cash flows.

    Cached for 24h — annual financials only refresh after each 10-K filing.
    """
    enforce_live_data_limit(request)
    data_layer = request.app.state.deps.data_layer
    cache = data_layer.cache
    ticker_upper = _normalize_ticker_param(ticker)

    async def _fetch_as_dict() -> dict[str, Any]:
        metrics = await fetch_historical_metrics(data_layer, ticker_upper)
        return metrics.model_dump(mode="json")

    try:
        payload = await cached_fetch(cache, DataType.HISTORICAL, ticker_upper, _fetch_as_dict)
    except (ValueError, ProviderError) as e:
        raise _data_http_error(e, ticker_upper) from e

    # Same FMP-fallback disclosure as /financials and /price: outside the 24h
    # route cache on purpose, so the note reflects the CURRENT settings (a key
    # fixed after the cached fetch stops warning without waiting out the TTL).
    return HistoricalMetrics.model_validate(_with_fmp_degradation_note(request, payload))


@router.get(
    "/{ticker}/earnings-calls",
    response_model=EarningsCallList,
    dependencies=[Depends(ensure_engine_ready)],
)
async def get_earnings_calls(
    ticker: str,
    request: Request,
    limit: int = Query(
        default=4,
        ge=1,
        le=12,
        description="Most-recent transcripts to return (12 = three years of quarterly calls).",
    ),
    quarter: int | None = Query(default=None, ge=1, le=4),
    year: int | None = Query(default=None, ge=1990, le=2100),
) -> EarningsCallList:
    """Fetch earnings call transcripts from FMP.

    Requires an FMP API key. Returns up to ``limit`` most recent transcripts.
    Optionally filter by specific quarter and year. All three params are
    bounded at the edge (mirroring the sentiment route's ``days`` cap): they
    flow into the FMP request AND the cache key, so an unbounded value both
    hammers the provider quota and mints unbounded cache rows on disk.
    """
    enforce_live_data_limit(request)
    data_layer = request.app.state.deps.data_layer

    # Check if any provider supports earnings transcripts
    has_transcript_provider = any(
        DataType.EARNINGS_TRANSCRIPT in p.capabilities() for p in data_layer._providers
    )
    if not has_transcript_provider:
        # 503 Service Unavailable — config-dependent capability not enabled.
        # Detail is Chinese + actionable so UI can prompt the user to fix it.
        raise HTTPException(
            status_code=503,
            detail="Earnings-call transcripts require an FMP API key. Configure FMP_API_KEY in Settings -> API Keys and retry.",
        )

    ticker_upper = _normalize_ticker_param(ticker)
    try:
        result = await data_layer.fetch(
            DataType.EARNINGS_TRANSCRIPT,
            ticker_upper,
            quarter=quarter,
            year=year,
            limit=limit,
        )
    except (ValueError, ProviderError) as e:
        raise _data_http_error(e, ticker_upper) from e

    raw_transcripts = result.data.get("transcripts", [])
    transcripts = []
    skipped = 0
    for item in raw_transcripts:
        date_str = item.get("date", "")
        parsed_date = None
        if date_str:
            try:
                parsed_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass
        # Construct per-item inside try/except: FMP serves annual/special calls
        # with a missing/zero/null quarter, but EarningsCallTranscript requires
        # quarter ∈ 1..4. A single bad item must degrade to a skip + warning, not
        # crash the whole endpoint with a bare 500 (the model rejects the 0
        # sentinel _.get("quarter", 0)_ feeds it).
        try:
            transcripts.append(
                EarningsCallTranscript(
                    ticker=item.get("ticker", ticker_upper),
                    quarter=item.get("quarter", 0),
                    year=item.get("year", 0),
                    date=parsed_date,
                    content=item.get("content", ""),
                )
            )
        except ValidationError:
            skipped += 1
            logger.warning(
                "Skipped malformed earnings transcript for %s (quarter=%r, year=%r)",
                ticker_upper,
                item.get("quarter"),
                item.get("year"),
            )

    if skipped:
        logger.warning(
            "Returned %d/%d earnings transcripts for %s; %d skipped as malformed",
            len(transcripts),
            len(raw_transcripts),
            ticker_upper,
            skipped,
        )

    return EarningsCallList(ticker=ticker_upper, transcripts=transcripts)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _warning_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


async def _provider_price_cache_payload(
    cache: Any,
    ticker: str,
    *,
    include_stale: bool = False,
    warning: str | None = None,
) -> dict[str, Any] | None:
    """Reuse provider-layer 1y price cache when the route cache is empty.

    Provider-backed pipelines cache ``DataType.PRICE`` under ``ticker`` while
    this route caches richer chart payloads under ``ticker:period``. For the
    default 1y view the provider cache already carries current price and
    one-year price history, so returning it avoids a duplicate yfinance call.
    """
    cached = await cache.get(DataType.PRICE, ticker)
    if cached is None or (cached.is_stale and not include_stale):
        return None
    raw = cached.data.data
    if not isinstance(raw, dict):
        return None
    history_raw = raw.get("history") or raw.get("price_history") or []
    history = history_raw if isinstance(history_raw, list) else []
    change, change_pct = _price_change_from_history(history)
    warnings = list(cached.data.warnings)
    warnings_raw = raw.get("warnings", [])
    if isinstance(warnings_raw, list):
        warnings.extend(w for w in warnings_raw if w not in warnings)
    if warning is not None:
        warnings.insert(0, warning)
    payload = {
        "ticker": ticker,
        "current_price": raw.get("current_price"),
        # Native quote currency of the live price (see fetch_price_history) —
        # carried through the provider-cache fast path so every /price shape is
        # identical regardless of which path served it.
        "quote_currency": raw.get("quote_currency"),
        "change": change,
        "change_pct": change_pct,
        "market_cap": raw.get("market_cap"),
        "company_name": raw.get("company_name"),
        "exchange": raw.get("exchange"),
        # Per-exchange session phase from the provider (yfinance marketState);
        # the _enrich choke point feeds it to compute_session_state. None on the
        # FMP-sourced cache → clock-window fallback (still correct).
        "market_state": raw.get("market_state"),
        "quote_timestamp": raw.get("quote_timestamp"),
        "next_earnings_date": raw.get("next_earnings_date"),
        "history": history,
        "fetched_at": cached.data.timestamp.isoformat(),
        "data_source": f"{cached.data.provider}:provider-cache",
        "warnings": warnings,
    }
    return await _enrich_price_payload_from_financial_cache(cache, ticker, payload)


async def _enrich_price_payload_from_financial_cache(
    cache: Any,
    ticker: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Fill display metadata from financials cache without adding network work.

    Also stamps ``as_of`` — the date of the latest price bar, i.e. the session
    ``current_price`` belongs to — and ``session_state`` (live vs closed). The
    freshness pill binds to these, not to ``fetched_at`` (the fetch wall-clock),
    so a closed-market view can't claim "near-real-time" over a prior session's
    closing price (ADR-0004 audit A/B). Every /price return path flows through
    here, so this is the one place to set them.

    It is also where the stable response contract is pinned: the fetcher path
    (``fetch_price_history``) omits ``ticker`` and ``quote_timestamp`` while the
    1y provider-cache fast path sets both, so without this the /price shape would
    differ by which path served it (the frontend types ``ticker`` as required —
    a non-1y / cache-miss response left it undefined). Set them for every path.
    """
    payload["ticker"] = payload.get("ticker") or ticker
    payload.setdefault("quote_timestamp", None)
    # Pin the quote-currency contract for every /price path (the fetcher sets it
    # from the canonical PRICE; legacy/stale cached payloads predating the field
    # leave it None → the client treats absent as USD, the US-majority no-op).
    payload.setdefault("quote_currency", None)
    _stamp_as_of(payload)
    payload["session_state"] = compute_session_state(
        payload.get("as_of"),
        market_state=payload.get("market_state"),
        ticker=payload.get("ticker") or ticker,
        exchange=payload.get("exchange"),
    )
    # Technicals trend snapshot — computed here (the one choke point all /price
    # paths flow through: fetcher, provider-cache fast path, stale-cache
    # fallback) so every path carries it identically. The guard keeps any
    # pre-set value (e.g. a re-enriched cached payload) instead of recomputing.
    if "technicals" not in payload:
        hist = payload.get("history") or payload.get("price_history") or []
        payload["technicals"] = technical_payload(hist if isinstance(hist, list) else [])
    if payload.get("market_cap") is not None and payload.get("company_name") is not None:
        return payload

    cached_financials = await cache.get(DataType.FINANCIALS, ticker)
    if cached_financials is None:
        return payload

    raw = cached_financials.data.data
    if not isinstance(raw, dict):
        return payload

    market = raw.get("market")
    market_data = market if isinstance(market, dict) else raw

    if payload.get("market_cap") is None:
        # The financials-cache market_cap is priced at THAT snapshot's own (often
        # prior-close) quote, while the /price payload already carries a fresher
        # live current_price. Grafting the absolute cap across the two price epochs
        # makes market_cap / current_price ≠ the true share count — the AAPL/MU/NVDA
        # /price-vs-/financials disagreement (probe 2026-06-09). Mark it to the live
        # price (shares × current_price) so the served cap is consistent with the
        # served price. Falls back to the cached absolute only when shares + the
        # cached price are both absent (nothing to re-mark from).
        payload["market_cap"] = market_cap_on_live_price(
            cached_market_cap=market_data.get("market_cap"),
            cached_shares=market_data.get("shares_outstanding"),
            cached_price=market_data.get("current_price"),
            live_price=payload.get("current_price"),
        )
    if payload.get("company_name") is None:
        payload["company_name"] = raw.get("company_name")
    return payload


def _stamp_as_of(payload: dict[str, Any]) -> None:
    """Set ``payload['as_of']`` to the price's observation time when absent.

    Mirrors ``normalize_price`` via the shared ``derive_price_as_of`` chain
    (quote timestamp → session close → bar date), so the ``/price`` route and the
    Coverage card never disagree on a price's age. Distinct from ``fetched_at``
    (the fetch wall-clock). When the provider gave a quote timestamp this stamps
    the real trade instant; otherwise it falls back to the bar's session close —
    never the bar date's midnight (which overstated age by ~20h).
    """
    if payload.get("as_of"):
        return
    hist = payload.get("history") or payload.get("price_history")
    last_bar_date: date | None = None
    if isinstance(hist, list) and hist and isinstance(hist[-1], dict):
        raw = hist[-1].get("date")
        if isinstance(raw, str) and raw:
            try:
                last_bar_date = date.fromisoformat(raw[:10])
            except ValueError:
                last_bar_date = None
    if payload.get("quote_timestamp") is None and last_bar_date is None:
        return
    as_of, _ = derive_price_as_of(
        payload.get("quote_timestamp"),
        last_bar_date,
        ticker=payload.get("ticker"),
        exchange=payload.get("exchange"),
    )
    payload["as_of"] = as_of.isoformat()


def _price_change_from_history(history: list[Any]) -> tuple[float | None, float | None]:
    closes: list[float] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        raw_close = item.get("close")
        if not isinstance(raw_close, int | float | str):
            continue
        try:
            close = float(raw_close)
        except (TypeError, ValueError):
            continue
        # NaN slips the isinstance gate (it IS a float) and would poison the
        # change/changePct readout — 守 None ≠ 守 finiteness.
        if not math.isfinite(close):
            continue
        closes.append(close)
    if len(closes) < 2:
        return None, None
    prev_close = closes[-2]
    if prev_close == 0:
        return None, None
    change = closes[-1] - prev_close
    return change, change / prev_close * 100
