# finagent/engine/compute/news.py
"""News fetching and classification.

What this code does that raw LLM cannot: deterministic conversion of
provider DataResult into typed RawNewsItem list.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field
from finagent.engine.data.interface import DataResult


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
    category: Literal["earnings", "product", "regulatory", "macro", "analyst", "management", "other"]
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
