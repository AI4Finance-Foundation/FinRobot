"""Catalyst event ranking and filtering.

What this code does that raw LLM cannot: deterministic sorting by
expected impact (impact_score × probability), reproducible filtering.
"""
from __future__ import annotations

from finagent.engine.models.financial import CatalystEvent


def rank_catalysts(events: list[CatalystEvent], top_n: int | None = None) -> list[CatalystEvent]:
    """Sort catalyst events by expected impact (impact_score × probability), descending.

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
