# finagent/engine/compute/news.py
"""News fetching and classification.

What this code does that raw LLM cannot:
- parse_raw_news: deterministic conversion of provider DataResult into typed
  RawNewsItem list (no LLM needed, pure data transformation).
- fetch_news: provider-chain fallback via DataLayer (deterministic routing).
- classify_news: LLM classifies news into typed NewsItem with constrained
  category/sentiment/importance via PydanticAI output_type — guarantees
  structural validity that raw LLM text cannot.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.exceptions import AgentRunError

from finagent.engine.data.interface import DataResult
from finagent.engine.data.types import DataType

if TYPE_CHECKING:
    from finagent.engine.data.layer import DataLayer
    from finagent.engine.deps import FinAgentDeps

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
    category: Literal["earnings", "product", "regulatory", "macro", "analyst", "management", "other"]
    sentiment: Literal["positive", "negative", "neutral"]
    importance: int = Field(ge=1, le=5)
    summary: str


class ClassifiedNewsBatch(BaseModel):
    """LLM structured output for batch news classification."""

    items: list[NewsItem]


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


async def classify_news(
    raw_items: list[RawNewsItem],
    deps: FinAgentDeps,
) -> list[NewsItem]:
    """Classify raw news items using LLM with structured output.

    What this does that raw LLM text cannot: forces each news item into
    a typed NewsItem with constrained category (7 options), sentiment
    (3 options), and importance (1-5) via PydanticAI output_type validation.
    Invalid LLM output is rejected by Pydantic, not silently accepted.

    Args:
        raw_items: News items to classify (from fetch_news or parse_raw_news).
        deps: FinAgentDeps with settings for model configuration.

    Returns:
        List of classified NewsItem. Empty list if input is empty or LLM fails.
    """
    if not raw_items:
        return []

    classification_agent = PydanticAgent(
        deps.settings.model_name,
        output_type=ClassifiedNewsBatch,
        instructions=(
            "Classify each news item. For each, provide:\n"
            "- category: earnings/product/regulatory/macro/analyst/management/other\n"
            "- sentiment: positive/negative/neutral\n"
            "- importance: 1-5 (5=most important for stock price)\n"
            "- summary: one sentence summary\n"
            "Preserve the original title, source, published, and url fields exactly."
        ),
        defer_model_check=True,
    )

    news_text = "\n".join(
        f"- [{item.source}] {item.title} "
        f"(published: {item.published.isoformat()}, url: {item.url})"
        for item in raw_items
    )
    prompt = f"Classify these {len(raw_items)} news items:\n{news_text}"

    try:
        result = await classification_agent.run(prompt, deps=deps)
        return result.output.items
    except (AgentRunError, ValueError, TypeError) as e:
        logger.warning(f"News classification failed: {e}")
        return []
