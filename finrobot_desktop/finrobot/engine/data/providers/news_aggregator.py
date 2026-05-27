# finrobot/engine/data/providers/news_aggregator.py
"""Multi-source news aggregation provider.

Fetches news from Yahoo Finance RSS (free, no key) and Alpha Vantage
News Sentiment (free tier, requires FINAGENT_ALPHA_VANTAGE_API_KEY).
Deduplicates by headline prefix similarity and returns a unified
news list with optional sentiment scores.

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
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree

import httpx

from finrobot.engine.compute.sentiment import score_headline
from finrobot.engine.data.interface import DataProvider, DataResult, ProviderError
from finrobot.engine.data.types import DataType

logger = logging.getLogger(__name__)

_TIMEOUT = 12.0
_YAHOO_RSS_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline"
_ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
_AV_MIN_INTERVAL = 12.5  # Alpha Vantage free tier: 5 calls/min -> 1 per 12s; add buffer
_DEDUP_PREFIX_LEN = 50  # headlines sharing this many leading chars are duplicates


class NewsAggregatorProvider(DataProvider):
    """Aggregates news from Yahoo Finance RSS + Alpha Vantage.

    Yahoo Finance RSS: always available, no API key required.
    Alpha Vantage: only used when alpha_vantage_api_key is provided.

    This provider only supports DataType.NEWS.
    """

    def __init__(self, *, alpha_vantage_api_key: str = "") -> None:
        self._av_key = alpha_vantage_api_key
        self._av_lock = asyncio.Lock()
        self._av_last_call: float = 0.0

    @property
    def name(self) -> str:
        return "news_aggregator"

    def capabilities(self) -> list[str | DataType]:
        return [DataType.NEWS]

    async def fetch(self, ticker: str, data_type: str | DataType, **kwargs: Any) -> DataResult:
        if data_type != DataType.NEWS:
            raise ProviderError(
                f"NewsAggregatorProvider only supports NEWS, got '{data_type}'"
            )

        tasks: list[asyncio.Task[list[dict[str, Any]]]] = []
        tasks.append(asyncio.create_task(self._fetch_yahoo_rss(ticker)))
        if self._av_key:
            tasks.append(asyncio.create_task(self._fetch_alpha_vantage(ticker)))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_items: list[dict[str, Any]] = []
        warnings: list[str] = []
        failures: list[str] = []
        for i, result in enumerate(results):
            source_name = "Yahoo RSS" if i == 0 else "Alpha Vantage"
            if isinstance(result, BaseException):
                warn = f"{source_name} fetch failed: {result}"
                logger.warning(warn)
                warnings.append(warn)
                failures.append(warn)
            else:
                all_items.extend(result)

        # If every source failed, the caller sees an empty news list that
        # is indistinguishable from "no news exists for this ticker". Raise
        # ProviderError so HTTP routes can turn this into a real error
        # response instead of silently degrading.
        if not all_items and failures and len(failures) == len(results):
            raise ProviderError(
                "All news sources failed for "
                f"'{ticker}': {'; '.join(failures)}"
            )

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

    async def _fetch_yahoo_rss(self, ticker: str) -> list[dict[str, Any]]:
        """Fetch news from Yahoo Finance RSS feed (no API key required)."""
        params = {"s": ticker, "region": "US", "lang": "en-US"}
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(_YAHOO_RSS_URL, params=params)
                resp.raise_for_status()
        except httpx.TimeoutException as e:
            raise ProviderError(f"Yahoo RSS timeout for '{ticker}': {e}") from e
        except httpx.HTTPStatusError as e:
            raise ProviderError(f"Yahoo RSS HTTP error for '{ticker}': {e}") from e

        items: list[dict[str, Any]] = []
        try:
            root = ElementTree.fromstring(resp.text)
            for item_el in root.iter("item"):
                title_el = item_el.find("title")
                link_el = item_el.find("link")
                pub_el = item_el.find("pubDate")
                if title_el is None or not (title_el.text or "").strip():
                    continue
                items.append({
                    "title": (title_el.text or "").strip(),
                    "source": "Yahoo Finance",
                    "url": (link_el.text or "").strip() if link_el is not None else "",
                    "published": self._parse_rss_date(
                        (pub_el.text or "").strip() if pub_el is not None else ""
                    ),
                    "sentiment_score": None,  # filled by keyword scorer later
                    "category": None,
                })
        except ElementTree.ParseError as e:
            raise ProviderError(f"Yahoo RSS XML parse error for '{ticker}': {e}") from e

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
        except httpx.TimeoutException as e:
            raise ProviderError(f"Alpha Vantage timeout for '{ticker}': {e}") from e
        except httpx.HTTPStatusError as e:
            raise ProviderError(f"Alpha Vantage HTTP error for '{ticker}': {e}") from e

        data = resp.json()
        if "feed" not in data:
            # Alpha Vantage returns {"Note": "..."} or {"Information": "..."} on
            # rate-limit / invalid key, not an HTTP error status.
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

            items.append({
                "title": title,
                "source": article.get("source", "Alpha Vantage"),
                "url": article.get("url", ""),
                "published": self._parse_av_date(
                    article.get("time_published", "")
                ),
                "sentiment_score": av_score,
                "category": article.get("category_within_source"),
            })

        return items

    @staticmethod
    def _deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove duplicates by comparing first N characters of headline.

        When duplicates are found, prefer the item with a sentiment_score
        (Alpha Vantage) over one without (Yahoo RSS).
        """
        seen: dict[str, dict[str, Any]] = {}
        for item in items:
            prefix = item.get("title", "")[:_DEDUP_PREFIX_LEN].lower().strip()
            if not prefix:
                continue
            existing = seen.get(prefix)
            if existing is None:
                seen[prefix] = item
            elif existing.get("sentiment_score") is None and item.get("sentiment_score") is not None:
                # Prefer the version with Alpha Vantage sentiment
                seen[prefix] = item
        return list(seen.values())

    @staticmethod
    def _parse_rss_date(date_str: str) -> str:
        """Parse RSS pubDate (RFC 2822) to ISO format string."""
        if not date_str:
            return datetime.now(tz=timezone.utc).isoformat()
        # Example: "Mon, 15 Jan 2024 18:30:00 +0000"
        try:
            dt = parsedate_to_datetime(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except (ValueError, TypeError):
            return datetime.now(tz=timezone.utc).isoformat()

    @staticmethod
    def _parse_av_date(date_str: str) -> str:
        """Parse Alpha Vantage time_published (YYYYMMDDTHHmmss) to ISO format."""
        if not date_str:
            return datetime.now(tz=timezone.utc).isoformat()
        try:
            # "20240115T183000"
            dt = datetime.strptime(date_str, "%Y%m%dT%H%M%S")
            dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except (ValueError, TypeError):
            return datetime.now(tz=timezone.utc).isoformat()
