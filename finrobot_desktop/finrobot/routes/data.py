"""Data routes -- thin handlers that parse params, call services, return responses."""

from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import Any, cast
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from finrobot.engine.compute.catalyst import (
    compute_expected_impact,
    extract_catalysts_from_news,
    rank_catalysts,
)
from finrobot.engine.compute.extractor import extract_financial_data
from finrobot.engine.compute.historical_extractor import fetch_historical_metrics
from finrobot.engine.compute.market import technical_payload
from finrobot.engine.analysis.news_classifier import classify_news
from finrobot.engine.compute.news import fetch_news
from finrobot.engine.data.cache import cached_fetch
from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.data.types import DataType
from finrobot.engine.models.earnings_call import EarningsCallList, EarningsCallTranscript
from finrobot.engine.models.financial import (
    CatalystEvent,
    FinancialData,
    HistoricalMetrics,
)
from finrobot.engine.services.market_data import fetch_price_history

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/data", tags=["data"])


def _data_http_error(exc: Exception, ticker: str) -> HTTPException:
    """Translate data-layer exceptions into proper HTTP status codes + 中文 detail.

    - ProviderError → 502 Bad Gateway (upstream API failed)
    - ValueError    → 422 Unprocessable Entity (request data invalid / ticker not recognized)

    Detail is Chinese so the desktop UI can surface it directly to retail users
    without an extra translation layer.
    """
    if isinstance(exc, ProviderError):
        return HTTPException(
            status_code=502,
            detail=f"数据源暂不可用（{ticker}）：{exc}",
        )
    return HTTPException(
        status_code=422,
        detail=f"无法获取 {ticker} 的数据：{exc}",
    )


@router.get("/{ticker}/catalysts", response_model=list[CatalystEvent])
async def get_catalysts(
    ticker: str,
    request: Request,
    min_importance: int = 3,
) -> list[CatalystEvent]:
    """Fetch news, classify via LLM, extract catalyst events, return sorted by impact.

    Pipeline: fetch_news -> classify_news (LLM) -> extract_catalysts -> rank.

    Args:
        ticker: Stock ticker symbol.
        min_importance: Minimum news importance to become a catalyst (1-5).
    """
    deps = request.app.state.deps
    data_layer = deps.data_layer
    try:
        raw_news = await fetch_news(data_layer, ticker.upper())
    except (ValueError, ProviderError) as e:
        raise _data_http_error(e, ticker.upper()) from e

    if not raw_news:
        return []

    # LLM classification failure must surface as a real 5xx — silently
    # returning [] makes a backend outage indistinguishable from "no
    # catalysts found", which is the failure mode this endpoint exists to
    # avoid.
    try:
        classified = await classify_news(raw_news, deps)
    except RuntimeError as e:
        logger.error("Catalyst classification failed for %s: %s", ticker, e)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "catalyst_classification_failed",
                "message": str(e),
                "ticker": ticker.upper(),
            },
        ) from e

    catalysts = extract_catalysts_from_news(classified, min_importance=min_importance)
    catalysts = compute_expected_impact(catalysts)
    catalysts = rank_catalysts(catalysts)
    return catalysts


@router.get("/{ticker}/financials", response_model=FinancialData)
async def get_financials(ticker: str, request: Request) -> FinancialData:
    data_layer: DataLayer = request.app.state.deps.data_layer
    try:
        _fin = await data_layer.fetch_canonical(DataType.FINANCIALS, ticker.upper())
        _price = await data_layer.fetch_canonical(DataType.PRICE, ticker.upper())
    except (ValueError, ProviderError) as e:
        raise _data_http_error(e, ticker.upper()) from e
    # fetch_canonical is overloaded on the DataType literal, so _fin / _price are
    # already typed NormalizedFinancials / NormalizedPrice — no narrowing needed.
    # Cross-validation warnings already merged into fin/price.warnings by
    # fetch_canonical, and extract_financial_data carries them through.
    extracted = extract_financial_data(_fin, _price)
    return extracted


@router.get("/{ticker}/price")
async def get_price(ticker: str, request: Request, period: str = "1y") -> dict[str, Any]:
    """Price data with configurable time period.

    Cached for 15 minutes (TTL set in cache._TTL_SECONDS[DataType.PRICE]).
    The cache key includes ``period`` so /price?period=1y and /price?period=5d
    don't collide.

    Error mapping:
      - ValueError      → 422 (invalid ticker)
      - ProviderError   → 502 (yfinance service down)
    """
    data_layer = request.app.state.deps.data_layer
    cache = data_layer.cache
    ticker_upper = ticker.upper()
    route_cache_key = f"{ticker_upper}:{period}"
    cached = await cache.get(DataType.PRICE, route_cache_key)
    if cached is not None and not cached.is_stale:
        cached_payload = dict(cast(dict[str, Any], cached.data.data))
        return await _enrich_price_payload_from_financial_cache(cache, ticker_upper, cached_payload)

    if period == "1y":
        provider_cached = await _provider_price_cache_payload(cache, ticker_upper)
        if provider_cached is not None:
            return provider_cached

    try:
        payload = await cached_fetch(
            cache,
            DataType.PRICE,
            ticker_upper,
            lambda: fetch_price_history(data_layer, ticker_upper),
            cache_key_suffix=f":{period}",
        )
        return await _enrich_price_payload_from_financial_cache(cache, ticker_upper, payload)
    except (ValueError, ProviderError) as e:
        if cached is not None:
            stale_payload = dict(cached.data.data)
            raw_warnings = stale_payload.get("warnings", [])
            warnings = list(raw_warnings) if isinstance(raw_warnings, list) else []
            warnings.insert(0, f"数据源请求失败，正在显示缓存行情（{ticker_upper} / {period}）。")
            stale_payload["warnings"] = _dedupe(warnings)
            return await _enrich_price_payload_from_financial_cache(
                cache, ticker_upper, stale_payload
            )
        if period == "1y":
            stale_provider = await _provider_price_cache_payload(
                cache,
                ticker_upper,
                include_stale=True,
                warning=f"数据源请求失败，正在显示缓存行情（{ticker_upper} / provider）。",
            )
            if stale_provider is not None:
                return stale_provider
        raise _data_http_error(e, ticker_upper) from e


@router.get("/{ticker}/historical", response_model=HistoricalMetrics)
async def get_historical(ticker: str, request: Request) -> HistoricalMetrics:
    """Multi-year historical financial metrics including cash flows.

    Cached for 24h — annual financials only refresh after each 10-K filing.
    """
    data_layer = request.app.state.deps.data_layer
    cache = data_layer.cache
    ticker_upper = ticker.upper()

    async def _fetch_as_dict() -> dict[str, Any]:
        metrics = await fetch_historical_metrics(data_layer, ticker_upper)
        return metrics.model_dump(mode="json")

    try:
        payload = await cached_fetch(cache, DataType.HISTORICAL, ticker_upper, _fetch_as_dict)
    except (ValueError, ProviderError) as e:
        raise _data_http_error(e, ticker_upper) from e

    return HistoricalMetrics.model_validate(payload)


@router.get("/{ticker}/earnings-calls", response_model=EarningsCallList)
async def get_earnings_calls(
    ticker: str,
    request: Request,
    limit: int = 4,
    quarter: int | None = None,
    year: int | None = None,
) -> EarningsCallList:
    """Fetch earnings call transcripts from FMP.

    Requires an FMP API key. Returns up to ``limit`` most recent transcripts.
    Optionally filter by specific quarter and year.
    """
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
            detail="财报电话会逐字稿需要 FMP API 密钥。请在 设置 → API 密钥 配置 FMP_API_KEY 后重试。",
        )

    try:
        result = await data_layer.fetch(
            DataType.EARNINGS_TRANSCRIPT,
            ticker.upper(),
            quarter=quarter,
            year=year,
            limit=limit,
        )
    except (ValueError, ProviderError) as e:
        raise _data_http_error(e, ticker.upper()) from e

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
                    ticker=item.get("ticker", ticker.upper()),
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
                ticker.upper(),
                item.get("quarter"),
                item.get("year"),
            )

    if skipped:
        logger.warning(
            "Returned %d/%d earnings transcripts for %s; %d skipped as malformed",
            len(transcripts),
            len(raw_transcripts),
            ticker.upper(),
            skipped,
        )

    return EarningsCallList(ticker=ticker.upper(), transcripts=transcripts)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


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
    warnings_raw = raw.get("warnings", [])
    warnings = list(warnings_raw) if isinstance(warnings_raw, list) else []
    if warning is not None:
        warnings.insert(0, warning)
    payload = {
        "ticker": ticker,
        "current_price": raw.get("current_price"),
        "change": change,
        "change_pct": change_pct,
        "market_cap": raw.get("market_cap"),
        "company_name": raw.get("company_name"),
        "exchange": raw.get("exchange"),
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
    """
    _stamp_as_of(payload)
    payload["session_state"] = _compute_session_state(
        payload.get("as_of"),
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
        payload["market_cap"] = market_data.get("market_cap")
    if payload.get("company_name") is None:
        payload["company_name"] = raw.get("company_name")
    return payload


def _stamp_as_of(payload: dict[str, Any]) -> None:
    """Set ``payload['as_of']`` to the latest price bar's date when absent.

    This is the semantic time of the data (the session the price represents),
    which the freshness pill reads — distinct from ``fetched_at`` (fetch time).
    """
    if payload.get("as_of"):
        return
    hist = payload.get("history") or payload.get("price_history")
    if isinstance(hist, list) and hist and isinstance(hist[-1], dict):
        last_date = hist[-1].get("date")
        if last_date:
            payload["as_of"] = last_date


class _MarketSession:
    """Regular-session window for one exchange, in that exchange's timezone."""

    __slots__ = ("tz", "open", "close")

    def __init__(self, tz: str, open_: time, close: time) -> None:
        self.tz = ZoneInfo(tz)
        self.open = open_
        self.close = close


# Map yfinance ticker suffix → exchange regular session. US (no suffix) is the
# fallback for US-listed names. Each window is in the exchange's local timezone;
# lunch breaks (HK/CN/JP) are folded into a continuous span here — half-days and
# lunch-break minutes can over-report "live", an acceptable minimal-fix tradeoff
# (see BUG-081 note). Markets we can't map fall through to "unknown" rather than
# falsely claiming "closed" on a real intraday quote.
_US_SESSION = _MarketSession("America/New_York", time(9, 30), time(16, 0))
_SESSION_BY_SUFFIX: dict[str, _MarketSession] = {
    "HK": _MarketSession("Asia/Hong_Kong", time(9, 30), time(16, 0)),
    "SS": _MarketSession("Asia/Shanghai", time(9, 30), time(15, 0)),
    "SZ": _MarketSession("Asia/Shanghai", time(9, 30), time(15, 0)),
    "T": _MarketSession("Asia/Tokyo", time(9, 0), time(15, 0)),
    "L": _MarketSession("Europe/London", time(8, 0), time(16, 30)),
    "PA": _MarketSession("Europe/Paris", time(9, 0), time(17, 30)),
    "DE": _MarketSession("Europe/Berlin", time(9, 0), time(17, 30)),
    "TO": _MarketSession("America/Toronto", time(9, 30), time(16, 0)),
    "AX": _MarketSession("Australia/Sydney", time(10, 0), time(16, 0)),
    "KS": _MarketSession("Asia/Seoul", time(9, 0), time(15, 30)),
    "KQ": _MarketSession("Asia/Seoul", time(9, 0), time(15, 30)),
    "TW": _MarketSession("Asia/Taipei", time(9, 0), time(13, 30)),
    "NS": _MarketSession("Asia/Kolkata", time(9, 15), time(15, 30)),
    "BO": _MarketSession("Asia/Kolkata", time(9, 15), time(15, 30)),
    "SI": _MarketSession("Asia/Singapore", time(9, 0), time(17, 0)),
}

# US exchange codes (yfinance/FMP) — used when a ticker carries no suffix but
# the provider reports an exchange, to confirm a US session vs. fall to unknown.
_US_EXCHANGE_CODES = frozenset(
    {"NMS", "NYQ", "NGM", "NCM", "NASDAQ", "NYSE", "AMEX", "PCX", "BATS", "ASE"}
)


def _resolve_market_session(ticker: str | None, exchange: str | None) -> _MarketSession | None:
    """Pick the exchange session for ``ticker``, or ``None`` when undeterminable.

    Resolution order: yfinance ticker suffix (``.HK`` / ``.SS`` / …) → US for a
    suffix-less ticker carrying a known US exchange code → US for a suffix-less
    ticker with no exchange hint (the common US case). Returns ``None`` for a
    suffix we don't map, so the caller can honestly say "unknown" instead of
    asserting a US session for a foreign listing.
    """
    if ticker:
        _, dot, suffix = ticker.rpartition(".")
        if dot:
            return _SESSION_BY_SUFFIX.get(suffix.upper())  # unmapped suffix → None
    # No dotted suffix: a local listing or a US name.
    if exchange and exchange.upper() not in _US_EXCHANGE_CODES:
        # Provider names a non-US exchange we don't recognize — don't fake US.
        return None
    return _US_SESSION


def _compute_session_state(
    as_of: str | None,
    *,
    ticker: str | None = None,
    exchange: str | None = None,
    now: datetime | None = None,
) -> str:
    """Classify ``current_price`` as a live intraday quote or a session close.

    Returns ``"live"`` only when the resolving exchange's regular session is in
    progress AND today's bar is present; ``"closed"`` when the session is over
    or no today-bar exists; and ``"unknown"`` when the market can't be resolved
    (an unmapped foreign suffix / unrecognized non-US exchange) — never falsely
    "closed" on a real foreign intraday quote (BUG-081).

    Computed in the *resolving* exchange's timezone (not always ET): a HK/A-share/
    JP intraday quote sits in ET overnight, so the prior US-only logic stamped it
    "closed" and the freshness pill showed a live quote as a prior-day close.
    Resolving per-ticker fixes that; the US path (suffix-less ticker) is unchanged.

    The client can't derive session state from ``as_of`` alone — its notion of
    "today" is the viewer's local date, which drifts from the exchange date.

    Holidays need no calendar: on a market holiday there is no bar for today, so
    ``as_of < today`` → ``"closed"``. Not modeled: half-day early closes and
    lunch-break minutes read ``"live"`` (continuous-span sessions). Pre/post-market
    quotes report ``"closed"`` (only the regular session counts as live).
    """
    if not as_of:
        return "closed"
    try:
        as_of_date = date.fromisoformat(as_of[:10])
    except ValueError:
        return "closed"
    session = _resolve_market_session(ticker, exchange)
    if session is None:
        return "unknown"
    now_local = now.astimezone(session.tz) if now else datetime.now(tz=session.tz)
    in_regular_session = (
        now_local.weekday() < 5 and session.open <= now_local.time() < session.close
    )
    if in_regular_session and as_of_date >= now_local.date():
        return "live"
    return "closed"


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
        closes.append(close)
    if len(closes) < 2:
        return None, None
    prev_close = closes[-2]
    if prev_close == 0:
        return None, None
    change = closes[-1] - prev_close
    return change, change / prev_close * 100
