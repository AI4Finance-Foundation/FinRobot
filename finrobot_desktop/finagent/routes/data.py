"""Data routes -- thin handlers that parse params, call services, return responses."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from starlette.requests import Request

from finagent.engine.compute.catalyst import (
    compute_expected_impact,
    extract_catalysts_from_news,
    rank_catalysts,
)
from finagent.engine.compute.extractor import extract_financial_data
from finagent.engine.compute.historical_extractor import extract_historical_from_yfinance
from finagent.engine.analysis.news_classifier import classify_news
from finagent.engine.compute.news import fetch_news
from finagent.engine.compute.sentiment import score_headline
from finagent.engine.data.cache import cached_fetch
from finagent.engine.data.interface import ProviderError
from finagent.engine.data.types import DataType
from finagent.engine.models.earnings_call import EarningsCallList, EarningsCallTranscript
from finagent.engine.models.financial import (
    AggregatedNewsFeed,
    AggregatedNewsItem,
    CatalystEvent,
    FinancialData,
    HistoricalMetrics,
)
from finagent.engine.services.market_data import (
    fetch_performance_data,
    fetch_price_history,
    fetch_quarterly_data,
)

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


@router.get("/sources/status")
async def get_sources_status(request: Request) -> dict[str, list[dict[str, object]]]:
    """Return all configured data providers with their enabled status and capabilities.

    A provider is considered *enabled* when it has been instantiated in the current
    data_layer (i.e. its required API key was present at startup).

    Response shape::

        {
          "providers": [
            {"name": "fmp", "enabled": true, "capabilities": ["financials", "price", ...]},
            ...
          ]
        }
    """
    data_layer = request.app.state.deps.data_layer
    providers = []
    for provider in data_layer._providers:
        capabilities = [
            cap.value if hasattr(cap, "value") else str(cap) for cap in provider.capabilities()
        ]
        providers.append(
            {
                "name": provider.name,
                "enabled": True,  # provider is in the list → it was successfully instantiated
                "capabilities": capabilities,
            }
        )
    return {"providers": providers}


# MUST be before /{ticker}/ routes to avoid FastAPI matching ticker="performance"
@router.get("/performance")
async def get_performance(
    tickers: str = "AAPL",
    benchmark: str = "SPY",
    period: str = "1y",
) -> dict[str, Any]:
    """Multi-ticker normalized price performance."""
    try:
        result = await fetch_performance_data(
            tickers=tickers.split(","),
            benchmark=benchmark,
            period=period,
        )
    except ValueError as e:
        raise _data_http_error(e, tickers) from e
    return result


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


@router.get("/{ticker}/news", response_model=AggregatedNewsFeed)
async def get_news(ticker: str, request: Request) -> AggregatedNewsFeed:
    """Aggregated news from all configured sources with sentiment scores.

    Fetches from Yahoo Finance RSS, Alpha Vantage (if key set), plus any
    other news-capable provider (FMP, Finnhub, yfinance). Deduplicates
    and scores each headline with keyword-based sentiment.
    """
    data_layer = request.app.state.deps.data_layer
    try:
        result = await data_layer.fetch(DataType.NEWS, ticker.upper())
    except (ValueError, ProviderError) as e:
        raise _data_http_error(e, ticker.upper()) from e

    raw_items = result.data.get("news_items", [])
    items: list[AggregatedNewsItem] = []
    for raw in raw_items:
        title = raw.get("title", "")
        if not title:
            continue
        sentiment = raw.get("sentiment_score")
        if sentiment is None:
            sentiment = score_headline(title)
        items.append(
            AggregatedNewsItem(
                title=title,
                source=raw.get("source", ""),
                url=raw.get("url", ""),
                published_at=raw.get("published", raw.get("published_at", "")),
                sentiment_score=sentiment,
                category=raw.get("category"),
            )
        )

    # Sort by published_at descending (most recent first)
    items.sort(key=lambda x: x.published_at, reverse=True)

    # Compute overall sentiment
    scores = [i.sentiment_score for i in items if i.sentiment_score is not None]
    overall = sum(scores) / len(scores) if scores else 0.0

    return AggregatedNewsFeed(
        ticker=ticker.upper(),
        items=items,
        sources_used=list({i.source for i in items if i.source}),
        overall_sentiment=round(overall, 3),
        fetched_at=result.timestamp,
        warnings=list(result.warnings),
    )


@router.get("/{ticker}/financials", response_model=FinancialData)
async def get_financials(ticker: str, request: Request) -> FinancialData:
    data_layer = request.app.state.deps.data_layer
    try:
        financials = await data_layer.fetch(DataType.FINANCIALS, ticker.upper())
        price = await data_layer.fetch(DataType.PRICE, ticker.upper())
    except (ValueError, ProviderError) as e:
        raise _data_http_error(e, ticker.upper()) from e
    extracted = extract_financial_data(financials, price)
    if financials.warnings or price.warnings:
        extracted.warnings = _dedupe(
            [*extracted.warnings, *financials.warnings, *price.warnings]
        )
    return extracted


@router.get("/{ticker}/price")
async def get_price(ticker: str, request: Request, period: str = "1y") -> dict[str, Any]:
    """Price data with configurable time period.

    Cached for 15 minutes (TTL set in cache._TTL_SECONDS[DataType.PRICE]).
    The cache key includes ``period`` so /price?period=1y and /price?period=5d
    don't collide.
    """
    cache = request.app.state.deps.data_layer.cache
    ticker_upper = ticker.upper()
    try:
        return await cached_fetch(
            cache,
            DataType.PRICE,
            ticker_upper,
            lambda: fetch_price_history(ticker_upper, period),
            cache_key_suffix=f":{period}",
        )
    except ValueError as e:
        raise _data_http_error(e, ticker_upper) from e


@router.get("/{ticker}/historical", response_model=HistoricalMetrics)
async def get_historical(ticker: str, request: Request) -> HistoricalMetrics:
    """Multi-year historical financial metrics including cash flows.

    Cached for 24h — annual financials only refresh after each 10-K filing.
    """
    cache = request.app.state.deps.data_layer.cache
    ticker_upper = ticker.upper()

    async def _fetch_as_dict() -> dict[str, Any]:
        metrics = await extract_historical_from_yfinance(ticker_upper)
        return metrics.model_dump(mode="json")

    try:
        payload = await cached_fetch(
            cache, DataType.HISTORICAL, ticker_upper, _fetch_as_dict
        )
    except ValueError as e:
        raise _data_http_error(e, ticker_upper) from e

    return HistoricalMetrics.model_validate(payload)


@router.get("/{ticker}/quarterly")
async def get_quarterly(ticker: str, request: Request) -> dict[str, Any]:
    """Quarterly income statement + cash flow data.

    Cached for 24h — quarterly reports come out once per quarter.
    """
    cache = request.app.state.deps.data_layer.cache
    ticker_upper = ticker.upper()
    try:
        return await cached_fetch(
            cache,
            DataType.QUARTERLY,
            ticker_upper,
            lambda: fetch_quarterly_data(ticker_upper),
        )
    except ValueError as e:
        raise _data_http_error(e, ticker_upper) from e


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
    for item in raw_transcripts:
        date_str = item.get("date", "")
        parsed_date = None
        if date_str:
            try:
                parsed_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass
        transcripts.append(
            EarningsCallTranscript(
                ticker=item.get("ticker", ticker.upper()),
                quarter=item.get("quarter", 0),
                year=item.get("year", 0),
                date=parsed_date,
                content=item.get("content", ""),
            )
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
