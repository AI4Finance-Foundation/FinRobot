# finrobot/engine/primitives/sentiment.py
"""Keyword-based headline sentiment scoring.

What this code does that raw LLM cannot:
- Deterministic, reproducible sentiment scores from headline text.
- No API call, no latency, no cost. Runs in microseconds.
- Serves as a fast fallback when LLM classification is unavailable
  or when Alpha Vantage pre-computed sentiment is missing.

Score range: [-1.0, 1.0]
  -1.0 = maximally negative
   0.0 = neutral
  +1.0 = maximally positive
"""

from __future__ import annotations

import re

_POSITIVE_KEYWORDS: frozenset[str] = frozenset(
    {
        "beat",
        "beats",
        "surge",
        "surges",
        "surging",
        "upgrade",
        "upgrades",
        "upgraded",
        "record",
        "growth",
        "profit",
        "profits",
        "exceed",
        "exceeds",
        "exceeded",
        "exceeding",
        "outperform",
        "outperforms",
        "rally",
        "rallies",
        "rallying",
        "gain",
        "gains",
        "strong",
        "bullish",
        "breakout",
        "soar",
        "soars",
        "soaring",
        "optimistic",
        "upbeat",
        "raise",
        "raises",
        "raised",
        "dividend",
        "buyback",
        "approval",
        "approved",
    }
)

_NEGATIVE_KEYWORDS: frozenset[str] = frozenset(
    {
        "miss",
        "misses",
        "missed",
        "decline",
        "declines",
        "declining",
        "downgrade",
        "downgrades",
        "downgraded",
        "loss",
        "losses",
        "cut",
        "cuts",
        "warning",
        "warns",
        "warned",
        "layoff",
        "layoffs",
        "bearish",
        "plunge",
        "plunges",
        "plunging",
        "drop",
        "drops",
        "dropping",
        "slump",
        "slumps",
        "weak",
        "weakness",
        "sell",
        "selloff",
        "recall",
        "investigation",
        "lawsuit",
        "fine",
        "fined",
        "default",
        "bankruptcy",
        "crash",
        "crashes",
        "risk",
        "concern",
        "concerns",
    }
)

_WORD_RE = re.compile(r"[a-z]+")


def score_headline(headline: str) -> float:
    """Score a single headline's sentiment from keywords.

    Args:
        headline: News headline text.

    Returns:
        Sentiment score in [-1.0, 1.0]. 0.0 if no keywords match.
    """
    words = set(_WORD_RE.findall(headline.lower()))
    pos_count = len(words & _POSITIVE_KEYWORDS)
    neg_count = len(words & _NEGATIVE_KEYWORDS)
    total = pos_count + neg_count
    if total == 0:
        return 0.0
    raw = (pos_count - neg_count) / total
    # Clamp to [-1, 1] (mathematically guaranteed, but explicit for clarity)
    return max(-1.0, min(1.0, raw))
