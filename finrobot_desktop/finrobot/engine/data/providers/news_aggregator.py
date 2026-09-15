# finrobot/engine/data/providers/news_aggregator.py
"""Multi-source news aggregation provider.

Fetches news from yfinance (free, no key — via ``YFinanceProvider``) and Alpha
Vantage News Sentiment (free tier, requires FINROBOT_ALPHA_VANTAGE_API_KEY).
Deduplicates by headline prefix similarity and returns a unified news list
with optional sentiment scores.

History: this provider used to scrape Yahoo Finance's RSS headline feed
(``feeds.finance.yahoo.com/rss/2.0/headline``) as its free no-key source.
Yahoo took that endpoint offline — it now returns 404 — so with no Alpha
Vantage key the provider used to error 100% of the time (BUG-072). We replaced
the dead RSS scrape with the existing ``YFinanceProvider`` NEWS capability,
which serves the same Yahoo headlines and needs no key. The aggregator delegates
to that provider rather than importing yfinance directly, so all yfinance access
stays behind the single sanctioned gateway (门一; see
tests/audit/test_no_direct_yfinance_imports.py).

What this code does that raw LLM cannot:
- Concurrent fetching from multiple sources via asyncio.gather.
- Deterministic deduplication by headline prefix (first 50 chars).
- Unified NewsItem schema regardless of upstream format differences.
- Keyword-based sentiment scoring as fallback when Alpha Vantage
  sentiment is unavailable.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from finrobot.engine.data.interface import (
    DataProvider,
    DataResult,
    ProviderError,
    RateLimitedProviderError,
)
from finrobot.engine.primitives.sentiment import score_headline
from finrobot.engine.data.providers.yfinance_provider import YFinanceProvider
from finrobot.engine.data.types import DataType

logger = logging.getLogger(__name__)

_TIMEOUT = 12.0
_ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
_AV_MIN_INTERVAL = 12.5  # Alpha Vantage free tier: 5 calls/min -> 1 per 12s; add buffer
_DEDUP_PREFIX_LEN = 50  # headlines sharing this many leading chars are duplicates


class NewsAggregatorProvider(DataProvider):
    """Aggregates news from yfinance + Alpha Vantage.

    yfinance: free, no API key required — the always-on source, fetched through
    a held ``YFinanceProvider`` (no direct yfinance import; see module docstring).
    Alpha Vantage: only used when ``alpha_vantage_api_key`` is provided, and adds
    per-ticker sentiment scores on top of the yfinance headlines.

    This provider only supports DataType.NEWS.
    """

    def __init__(
        self,
        *,
        alpha_vantage_api_key: str = "",
        yfinance_provider: YFinanceProvider | None = None,
    ) -> None:
        self._av_key = alpha_vantage_api_key
        self._av_lock = asyncio.Lock()
        self._av_last_call: float = 0.0
        # Delegate the free no-key Yahoo headlines to the sanctioned yfinance
        # gateway instead of importing yfinance here (门一红线). Injectable for
        # tests; defaults to a fresh provider for normal use.
        self._yfinance = yfinance_provider or YFinanceProvider()

    @property
    def name(self) -> str:
        return "news_aggregator"

    def capabilities(self) -> list[str | DataType]:
        return [DataType.NEWS]

    async def fetch(self, ticker: str, data_type: str | DataType, **kwargs: Any) -> DataResult:
        if data_type != DataType.NEWS:
            raise ProviderError(f"NewsAggregatorProvider only supports NEWS, got '{data_type}'")

        tasks: list[asyncio.Task[list[dict[str, Any]]]] = []
        tasks.append(asyncio.create_task(self._fetch_yfinance(ticker)))
        if self._av_key:
            tasks.append(asyncio.create_task(self._fetch_alpha_vantage(ticker)))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_items: list[dict[str, Any]] = []
        warnings: list[str] = []
        failures: list[str] = []
        for i, result in enumerate(results):
            source_name = "yfinance" if i == 0 else "Alpha Vantage"
            if isinstance(result, BaseException):
                # User-facing warning carries the exception TYPE only — the raw
                # message (yfinance/httpx) embeds the upstream request URL, and this
                # warning rides DataResult.warnings → the report. Full detail → log.
                warn = f"{source_name} fetch failed: {type(result).__name__}"
                logger.warning("%s fetch failed: %r", source_name, result)
                warnings.append(warn)
                failures.append(warn)
            else:
                all_items.extend(result)

        # If every source failed, the caller sees an empty news list that
        # is indistinguishable from "no news exists for this ticker". Raise
        # ProviderError so HTTP routes can turn this into a real error
        # response instead of silently degrading.
        if not all_items and failures and len(failures) == len(results):
            raise ProviderError(f"All news sources failed for '{ticker}': {'; '.join(failures)}")

        deduplicated = self._deduplicate(all_items)

        # Apply keyword sentiment to items missing a sentiment score
        for item in deduplicated:
            if item.get("sentiment_score") is None:
                item["sentiment_score"] = score_headline(item.get("title", ""))

        return DataResult(
            data={"news_items": deduplicated},
            provider=self.name,
            ticker=ticker,
            data_type=DataType.NEWS,
            timestamp=datetime.now(tz=timezone.utc),
            warnings=warnings,
        )

    async def _fetch_yfinance(self, ticker: str) -> list[dict[str, Any]]:
        """Fetch Yahoo headlines via the sanctioned ``YFinanceProvider`` NEWS path.

        Replaces the dead Yahoo RSS scrape (BUG-072): the RSS headline feed at
        feeds.finance.yahoo.com now returns 404, but YFinanceProvider already
        exposes the same headlines via ``DataType.NEWS`` (its ``_fetch_news``).
        We delegate to it rather than importing yfinance here, keeping all
        yfinance access behind the single门一 gateway.
        """
        result = await self._yfinance.fetch(ticker, DataType.NEWS)
        raw_items = result.data.get("news_items", [])

        items: list[dict[str, Any]] = []
        for article in raw_items:
            title = (article.get("title") or "").strip()
            if not title:
                continue
            items.append(
                {
                    "title": title,
                    "source": article.get("source") or "Yahoo Finance",
                    "url": article.get("url", ""),
                    "published": self._normalize_published(article.get("published", "")),
                    "sentiment_score": None,  # filled by keyword scorer later
                    "category": None,
                }
            )

        return items

    async def _fetch_alpha_vantage(self, ticker: str) -> list[dict[str, Any]]:
        """Fetch news + sentiment from Alpha Vantage NEWS_SENTIMENT endpoint."""
        async with self._av_lock:
            elapsed = time.monotonic() - self._av_last_call
            if elapsed < _AV_MIN_INTERVAL:
                await asyncio.sleep(_AV_MIN_INTERVAL - elapsed)
            self._av_last_call = time.monotonic()

        params = {
            "function": "NEWS_SENTIMENT",
            "tickers": ticker,
            "apikey": self._av_key,
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(_ALPHA_VANTAGE_URL, params=params)
                resp.raise_for_status()
        # The Alpha Vantage request URL carries ``?apikey=<live key>``; the raw
        # httpx exception's str() contains that URL, so never interpolate ``e``
        # into the message (it ends up in DataResult.warnings → transcript).
        # ``from e`` keeps the detail for server-side logging only.
        except httpx.TimeoutException as e:
            raise ProviderError(f"Alpha Vantage timeout for '{ticker}'") from e
        except httpx.HTTPStatusError as e:
            # ONLY a structural 429 maps to the typed RateLimitedProviderError;
            # other statuses stay generic (the sanitized message keeps the code).
            if e.response.status_code == 429:
                raise RateLimitedProviderError(f"Alpha Vantage HTTP 429 for '{ticker}'") from e
            raise ProviderError(
                f"Alpha Vantage HTTP {e.response.status_code} for '{ticker}'"
            ) from e

        data = resp.json()
        if "feed" not in data:
            # Alpha Vantage returns {"Note": "..."} or {"Information": "..."} on
            # rate-limit / invalid key, not an HTTP error status. Neither key is
            # a reliable rate-limit discriminator (newer AV puts the daily-limit
            # notice under "Information" too), so this stays a plain
            # ProviderError — the note text ("rate limit is 25 requests per
            # day") is exactly what the is_rate_limit_error substring fallback
            # exists to catch.
            note = data.get("Note") or data.get("Information") or "No feed in response"
            raise ProviderError(f"Alpha Vantage: {note}")

        items: list[dict[str, Any]] = []
        for article in data["feed"]:
            title = article.get("title", "").strip()
            if not title:
                continue

            # Alpha Vantage provides per-ticker sentiment in ticker_sentiment list
            av_score: float | None = None
            for ts in article.get("ticker_sentiment", []):
                if ts.get("ticker", "").upper() == ticker.upper():
                    try:
                        av_score = float(ts.get("ticker_sentiment_score", 0))
                    except (ValueError, TypeError):
                        av_score = None
                    break

            items.append(
                {
                    "title": title,
                    "source": article.get("source", "Alpha Vantage"),
                    "url": article.get("url", ""),
                    "published": self._parse_av_date(article.get("time_published", "")),
                    "sentiment_score": av_score,
                    "category": article.get("category_within_source"),
                }
            )

        return items

    @staticmethod
    def _deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove duplicates by comparing first N characters of headline.

        When duplicates are found, prefer the item with a sentiment_score
        (Alpha Vantage) over one without (yfinance).
        """
        seen: dict[str, dict[str, Any]] = {}
        for item in items:
            prefix = item.get("title", "")[:_DEDUP_PREFIX_LEN].lower().strip()
            if not prefix:
                continue
            existing = seen.get(prefix)
            if existing is None:
                seen[prefix] = item
            elif (
                existing.get("sentiment_score") is None and item.get("sentiment_score") is not None
            ):
                # Prefer the version with Alpha Vantage sentiment
                seen[prefix] = item
        return list(seen.values())

    @staticmethod
    def _normalize_published(value: Any) -> str:
        """Normalize a yfinance published timestamp to an ISO 8601 string.

        yfinance returns either an ISO string (``content.pubDate``) or a Unix
        epoch seconds int (legacy ``providerPublishTime``). When the date is
        missing or unparseable, return "" (unknown) — never a fabricated
        ``now()``. A fake "just published" timestamp lets undated/stale news
        slip through the freshness filter as a fresh catalyst.
        """
        if value is None or value == "":
            return ""
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
            except (ValueError, OSError, OverflowError):
                return ""
        text = str(value).strip()
        if not text:
            return ""
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except (ValueError, TypeError):
            # Non-ISO text is unusable downstream (only fromisoformat is tried),
            # so it is the "unknown" sentinel too, not leaked raw.
            return ""

    @staticmethod
    def _parse_av_date(date_str: str) -> str:
        """Parse Alpha Vantage time_published (YYYYMMDDTHHmmss) to ISO format.

        Missing/unparseable → "" (unknown), never a fabricated ``now()``.
        """
        if not date_str:
            return ""
        try:
            # "20240115T183000"
            dt = datetime.strptime(date_str, "%Y%m%dT%H%M%S")
            dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except (ValueError, TypeError):
            return ""
