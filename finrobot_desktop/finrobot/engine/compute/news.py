# finrobot/engine/compute/news.py
"""News data models and deterministic parsing.

What this code does that raw LLM cannot:
- parse_raw_news: deterministic conversion of provider DataResult into typed
  RawNewsItem list (no LLM needed, pure data transformation).
- fetch_news: provider-chain fallback via DataLayer (deterministic routing).

LLM-based classification (classify_news) lives in
finrobot.engine.analysis.news_classifier to respect the compute/ leaf-layer
red line (no LLM library imports allowed).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.types import DataType

if TYPE_CHECKING:
    from finrobot.engine.data.layer import DataLayer

logger = logging.getLogger(__name__)


class RawNewsItem(BaseModel):
    title: str
    source: str
    published: datetime
    url: str


class NewsItem(BaseModel):
    title: str
    source: str
    published: datetime
    url: str
    category: Literal[
        "earnings", "product", "regulatory", "macro", "analyst", "management", "other"
    ]
    sentiment: Literal["positive", "negative", "neutral"]
    importance: int = Field(ge=1, le=5)
    summary: str


def _parse_datetime(s: str) -> datetime:
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        dt = datetime.now(tz=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_raw_news(data_result: DataResult) -> list[RawNewsItem]:
    """Convert a DataResult with news_items into typed RawNewsItem list.

    Expects data_result.data["news_items"] to be a list of dicts with keys:
    title, source, published, url. Items without a title are skipped.
    """
    items = data_result.data.get("news_items", [])
    return [
        RawNewsItem(
            title=item.get("title", ""),
            source=item.get("source", ""),
            published=_parse_datetime(item.get("published", "")),
            url=item.get("url", ""),
        )
        for item in items
        if item.get("title")
    ]


async def fetch_news(data_layer: DataLayer, ticker: str) -> list[RawNewsItem]:
    """Fetch raw news from providers via DataLayer chain fallback.

    What this does that raw LLM cannot: deterministic provider routing
    (FMP -> Finnhub -> yfinance) with automatic fallback and caching.
    """
    result = await data_layer.fetch(DataType.NEWS, ticker)
    return parse_raw_news(result)
