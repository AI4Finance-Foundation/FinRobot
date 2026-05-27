"""Catalyst event ranking, filtering, extraction, and summarization.

What this code does that raw LLM cannot:
- Deterministic sorting by expected impact (impact_score x probability).
- Reproducible filtering by score/sentiment thresholds.
- Deterministic news-to-catalyst conversion with typed category mapping.
- Quantitative expected-impact scoring with sentiment multiplier.
- Structured summary computation (net sentiment, category breakdown, top events).
"""

from __future__ import annotations

from typing import Any, cast

from finrobot.engine.compute.news import NewsItem
from finrobot.engine.models.financial import CatalystEvent


# ---------------------------------------------------------------------------
# Catalyst category taxonomy & mapping from news categories
# ---------------------------------------------------------------------------

CATALYST_CATEGORIES: dict[str, str] = {
    "product_launch": "New product, service launch, or major feature release",
    "earnings": "Quarterly earnings, guidance update, revenue warning",
    "regulatory": "FDA approval, antitrust, compliance, legal settlement",
    "acquisition": "M&A, partnership, strategic investment, divestiture",
    "management": "CEO/CFO change, board reshuffle, reorganization",
    "market": "Market share shift, pricing change, competitive dynamics",
}

_NEWS_TO_CATALYST: dict[str, str] = {
    "earnings": "earnings",
    "product": "product_launch",
    "regulatory": "regulatory",
    "management": "management",
    "analyst": "market",
    "macro": "market",
    "other": "market",
}

_SENTIMENT_MULT: dict[str, float] = {
    "positive": 1.0,
    "negative": -1.0,
    "neutral": 0.0,
}


def _expected_impact(event: CatalystEvent) -> float:
    """Signed expected impact = impact_score × probability × sentiment_multiplier.

    Single source of truth used by compute_expected_impact and
    summarize_catalyst_outlook so the formula stays in lockstep.
    """
    mult = _SENTIMENT_MULT.get(event.sentiment, 0.0)
    return event.impact_score * event.probability * mult


# ---------------------------------------------------------------------------
# Original functions (preserved from P1.5)
# ---------------------------------------------------------------------------


def rank_catalysts(events: list[CatalystEvent], top_n: int | None = None) -> list[CatalystEvent]:
    """Sort catalyst events by expected impact (impact_score x probability), descending.

    Args:
        events: List of catalyst events to rank.
        top_n: If provided, return only the top N events.

    Returns:
        Sorted list of catalyst events, optionally truncated to top_n.
    """
    ranked = sorted(events, key=lambda e: e.impact_score * e.probability, reverse=True)
    if top_n is not None:
        return ranked[:top_n]
    return ranked


def filter_by_impact(
    events: list[CatalystEvent],
    min_score: int = 1,
    sentiment: str | None = None,
) -> list[CatalystEvent]:
    """Filter catalyst events by minimum impact score and/or sentiment.

    Args:
        events: List of catalyst events to filter.
        min_score: Minimum impact_score (inclusive). Default is 1 (no filtering).
        sentiment: If provided, keep only events matching this sentiment value.

    Returns:
        Filtered list of catalyst events.
    """
    result = [e for e in events if e.impact_score >= min_score]
    if sentiment is not None:
        result = [e for e in result if e.sentiment == sentiment]
    return result


# ---------------------------------------------------------------------------
# P6 additions: extraction, impact computation, summarization
# ---------------------------------------------------------------------------


def classify_catalyst_type(news_category: str) -> str:
    """Map news.py 7-category to catalyst 6-category.

    Unknown categories default to 'market'.
    """
    return _NEWS_TO_CATALYST.get(news_category, "market")


def extract_catalysts_from_news(
    news_items: list[NewsItem],
    min_importance: int = 3,
) -> list[CatalystEvent]:
    """Convert high-importance news items to CatalystEvent objects.

    Only news with importance >= min_importance become catalysts.
    Deterministic conversion -- no LLM call.

    Args:
        news_items: Classified news items from news.py pipeline.
        min_importance: Minimum importance threshold (inclusive).

    Returns:
        List of CatalystEvent objects derived from qualifying news.
    """
    events: list[CatalystEvent] = []
    for item in news_items:
        if item.importance < min_importance:
            continue
        events.append(
            CatalystEvent(
                category=cast(Any, classify_catalyst_type(item.category)),
                headline=item.title,
                sentiment=item.sentiment,
                impact_score=item.importance,
                probability=0.7,  # default; pipeline can override via LLM
                reasoning=item.summary,
            )
        )
    return events


def compute_expected_impact(events: list[CatalystEvent]) -> list[CatalystEvent]:
    """Compute expected impact and sort by abs(expected_impact) descending.

    expected_impact = impact_score x probability x sentiment_multiplier
    sentiment_multiplier: positive=+1, negative=-1, neutral=0

    Args:
        events: Catalyst events to score.

    Returns:
        Events sorted by absolute expected impact, highest first.
    """
    scored = [(abs(_expected_impact(e)), e) for e in events]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s[1] for s in scored]


def summarize_catalyst_outlook(events: list[CatalystEvent]) -> dict[str, Any]:
    """Produce structured catalyst summary for pipeline narrative.

    Returns dict with:
        total_catalysts: int -- number of events.
        net_sentiment: float -- sum of expected impacts, clamped to [-5, 5].
        top_positive: list[CatalystEvent] -- top 3 positive events by impact.
        top_negative: list[CatalystEvent] -- top 3 negative events by impact.
        category_breakdown: dict[str, int] -- count per category.

    Args:
        events: Catalyst events to summarize.
    """
    net = 0.0
    breakdown: dict[str, int] = {}
    positives: list[CatalystEvent] = []
    negatives: list[CatalystEvent] = []

    for e in events:
        net += _expected_impact(e)
        breakdown[e.category] = breakdown.get(e.category, 0) + 1
        if e.sentiment == "positive":
            positives.append(e)
        elif e.sentiment == "negative":
            negatives.append(e)

    net = max(-5.0, min(5.0, net))
    top_pos = rank_catalysts(positives, top_n=3)
    top_neg = rank_catalysts(negatives, top_n=3)

    return {
        "total_catalysts": len(events),
        "net_sentiment": round(net, 2),
        "top_positive": top_pos,
        "top_negative": top_neg,
        "category_breakdown": breakdown,
    }
