"""Catalyst event ranking, filtering, extraction, and summarization.

What this code does that raw LLM cannot:
- Deterministic sorting by expected impact (impact_score x probability).
- Reproducible filtering by score/sentiment thresholds.
- Deterministic news-to-catalyst conversion with typed category mapping.
- Quantitative expected-impact scoring with sentiment multiplier.
- Structured summary computation (net sentiment, category breakdown, top events).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlparse
from typing import Any, cast

from finrobot.engine.compute.coordinators.news import NewsItem
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
    """Sort catalyst events by ``abs(expected impact)`` descending.

    Keyed on ``abs(_expected_impact(e))`` (= impact_score × probability ×
    |sentiment_mult|), the SAME magnitude ``compute_expected_impact`` ranks by,
    so the two are interchangeable and a caller never needs to apply both. The
    earlier ``impact_score × probability`` key ignored sentiment, so a NEUTRAL
    headline (mult 0 → 0 expected impact) out-ranked a real directional catalyst
    on raw impact alone; chaining this after ``compute_expected_impact`` (the
    /data route did) then silently overrode the sign-aware order with the
    sign-blind one.

    Args:
        events: List of catalyst events to rank.
        top_n: If provided, return only the top N events.

    Returns:
        Sorted list of catalyst events, optionally truncated to top_n.
    """
    ranked = sorted(events, key=lambda e: abs(_expected_impact(e)), reverse=True)
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
                # Internal net-sentiment WEIGHT (news 0.7 < primary-source 8-K 1.0),
                # not a displayed forecast — a past event carries no real occurrence
                # probability. CatalystEvent.probability is exclude=True (see the field
                # docstring), so this weight never reaches an export bundle or response;
                # the report shows impact and direction only.
                probability=0.7,
                reasoning=item.summary,
                published=item.published,
                url=item.url or None,
            )
        )
    return events


# ---------------------------------------------------------------------------
# Near-duplicate catalyst clustering
# ---------------------------------------------------------------------------
#
# Why this exists: extract_catalysts_from_news maps news 1:1 to CatalystEvent.
# One real-world catalyst (e.g. a single antitrust suit) is routinely covered by
# several outlets / law-firm press releases with DIFFERENT headlines. Without
# clustering, summarize_catalyst_outlook counts that one event N times: both
# total_catalysts and net_sentiment (which divides by len(events)) get pulled by
# the same underlying fact repeated N times. cluster_near_duplicates collapses
# each such group to a single representative event before scoring.
#
# Design constraint (the hard one): false-merge MUST be 0 — never fold two
# genuinely distinct events (earnings vs product launch vs lawsuit) into one.
# Under-merging (leaving two true duplicates separate) is tolerable; over-merging
# is not. So the cluster key is a CONSERVATIVE conjunction, not a single title
# similarity score:
#
#   same category
#     AND |published_a - published_b| <= _DEDUP_WINDOW_DAYS
#     AND (title-token Jaccard >= _DEDUP_JACCARD_MIN  OR  same URL domain + same day)
#
# Same-entity is satisfied by construction: extract_catalysts_from_news is called
# per-ticker, so every event in one list is already the SAME company/security.
# (If this ever feeds a multi-ticker list, an explicit entity key must be added
# to the conjunction first — clustering across tickers without it WOULD false-merge.)

# Calibration thresholds — conservative defaults chosen to drive false-merge to 0
# at the cost of some under-merging. FROZEN 2026-07-06 after a hand-labeled basket
# of REAL multi-event news (TSLA/LLY/JPM/NVDA/AAPL, pulled live, blind-labeled
# before clustering): pair-level confusion matrix = 0 false-merge, 12 missed-merge
# (tolerated), and the tightest genuinely-distinct same-category+window pair sits at
# Jaccard 0.10 vs the 0.60 gate (0.50 margin). Basket + matrix in the freezing
# commit; regression lock in tests/unit/test_catalyst.py::TestFreezeValidationRealBasket.
# Kept module-level + tunable so any future recalibration is a one-line edit that
# must re-clear the same false-merge==0 gate.
#   _DEDUP_JACCARD_MIN = 0.6 : two headlines must share >=60% of their (stopword-
#       stripped) tokens. Different law-firm releases on the SAME suit share the
#       company + action nouns (well above 0.6); two DIFFERENT same-category
#       events (e.g. "EU antitrust probe" vs "DOJ data-privacy suit") share far
#       fewer tokens and stay separate. Trade-off observed at freeze: heavily
#       reworded cross-outlet coverage of one event (different domains, <60% shared
#       tokens) is left UNMERGED — the operator reliably collapses only near-verbatim
#       re-runs and same-domain-same-day wires, which is the deliberate conservative
#       posture (false-merge is the cardinal sin; under-merge is acceptable).
#   _DEDUP_WINDOW_DAYS = 3 : coverage of one event clusters within days; a 3-day
#       window catches lagging re-reports without bridging to the next quarter's
#       distinct event. Events with no publish date are NEVER merged (a missing
#       date cannot prove temporal proximity — see _within_window).
_DEDUP_JACCARD_MIN: float = 0.6
_DEDUP_WINDOW_DAYS: int = 3

# Stopwords stripped before Jaccard so shared filler ("the", "to", "says") can't
# inflate similarity between unrelated headlines. Deliberately small/generic.
_TITLE_STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with",
        "at", "by", "from", "as", "is", "are", "was", "were", "be", "been",
        "it", "its", "this", "that", "these", "those", "after", "over",
        "amid", "into", "says", "said", "new", "report", "reports",
    }
)


def _title_tokens(title: str) -> frozenset[str]:
    """Lowercased alphanumeric token set of a headline, minus stopwords.

    Used only for Jaccard similarity, so a set (not a list) is correct: token
    ORDER and repetition don't matter for "do these two headlines describe the
    same event". Returns frozenset for cheap hashing/reuse.
    """
    raw = re.findall(r"[a-z0-9]+", title.lower())
    return frozenset(t for t in raw if t and t not in _TITLE_STOPWORDS)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard similarity |a∩b| / |a∪b|; 0.0 when both are empty."""
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _url_domain(url: str | None) -> str | None:
    """Registrable host of a URL, lowercased, or None when absent/unparseable.

    A None domain must never match another None domain (two undated/url-less
    items are NOT evidence of the same source), so callers treat None as
    "no match" rather than equality.
    """
    if not url:
        return None
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return None
    return host or None


def _within_window(a: datetime | None, b: datetime | None) -> bool:
    """True iff both events are dated and within _DEDUP_WINDOW_DAYS of each other.

    Missing date → False (never merge): a missing publish date cannot prove the
    two items cover the same dated event, and false-merge is the cardinal sin.
    Naive datetimes are normalized to UTC to match the rest of the pipeline.
    """
    if a is None or b is None:
        return False
    if a.tzinfo is None:
        a = a.replace(tzinfo=timezone.utc)
    if b.tzinfo is None:
        b = b.replace(tzinfo=timezone.utc)
    return abs((a - b).days) <= _DEDUP_WINDOW_DAYS


def _same_day(a: datetime | None, b: datetime | None) -> bool:
    """True iff both events are dated and fall on the same UTC calendar day."""
    if a is None or b is None:
        return False
    if a.tzinfo is None:
        a = a.replace(tzinfo=timezone.utc)
    if b.tzinfo is None:
        b = b.replace(tzinfo=timezone.utc)
    return a.astimezone(timezone.utc).date() == b.astimezone(timezone.utc).date()


def _is_near_duplicate(a: CatalystEvent, b: CatalystEvent) -> bool:
    """Conservative near-duplicate test for two SAME-ticker catalyst events.

    See module comment for the full rationale. Returns True only when ALL of:
      - same category
      - published within _DEDUP_WINDOW_DAYS (both dated)
      - title Jaccard >= _DEDUP_JACCARD_MIN  OR  (same URL domain AND same day)
    """
    if a.category != b.category:
        return False
    if not _within_window(a.published, b.published):
        return False
    if _jaccard(_title_tokens(a.headline), _title_tokens(b.headline)) >= _DEDUP_JACCARD_MIN:
        return True
    domain_a = _url_domain(a.url)
    domain_b = _url_domain(b.url)
    if domain_a is not None and domain_a == domain_b and _same_day(a.published, b.published):
        return True
    return False


def cluster_near_duplicates(events: list[CatalystEvent]) -> list[CatalystEvent]:
    """Collapse near-duplicate catalyst events into one representative each.

    All events MUST belong to the same ticker (the per-ticker invariant of
    extract_catalysts_from_news) — see module comment; entity equality is
    assumed, not re-checked.

    Clustering is single-linkage (transitive): if A~B and B~C, then A, B, C form
    one cluster even when A and C alone don't meet the threshold — coverage of
    one event chains through intermediate re-reports. Per cluster, the event with
    the highest ``impact_score × probability`` is kept as the representative (the
    strongest signal of the underlying catalyst), and its ``source_count`` is set
    to the cluster size so downstream consumers can show "covered by N sources".

    Order-preserving: representatives come back in the order their cluster's
    earliest member appeared in ``events``, so this is a pure, deterministic
    reduction with no reliance on dict/set iteration order.

    False-merge is the cardinal sin (distinct earnings vs product vs lawsuit must
    NOT collapse); under-merge is tolerated. Thresholds are conservative module
    constants — see _DEDUP_JACCARD_MIN / _DEDUP_WINDOW_DAYS ([金融待核]).

    Args:
        events: Same-ticker catalyst events to deduplicate.

    Returns:
        One representative CatalystEvent per near-duplicate cluster, with
        ``source_count`` reflecting how many inputs collapsed into it.
    """
    n = len(events)
    if n <= 1:
        # Still normalize source_count to 1 on a lone event so the field is
        # meaningful (== sources merged) rather than whatever the input carried.
        return [e.model_copy(update={"source_count": 1}) for e in events]

    # Union-find over event indices; single-linkage clustering.
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    for i in range(n):
        for j in range(i + 1, n):
            if find(i) != find(j) and _is_near_duplicate(events[i], events[j]):
                union(i, j)

    # Group indices by root, preserving first-seen order of each cluster.
    clusters: dict[int, list[int]] = {}
    order: list[int] = []
    for i in range(n):
        root = find(i)
        if root not in clusters:
            clusters[root] = []
            order.append(root)
        clusters[root].append(i)

    result: list[CatalystEvent] = []
    for root in order:
        members = clusters[root]
        # Representative = strongest signal (impact × probability). Ties resolve
        # to the earliest index for determinism.
        rep_idx = max(members, key=lambda k: (events[k].impact_score * events[k].probability, -k))
        rep = events[rep_idx].model_copy(update={"source_count": len(members)})
        result.append(rep)
    return result


def filter_fresh_news(
    news_items: list[NewsItem],
    max_age_days: int = 30,
) -> tuple[list[NewsItem], int]:
    """Drop news items older than max_age_days.

    Returns:
        (fresh_items, stale_count) where stale_count is the number dropped.

    Items with timezone-naive published are normalized to UTC before comparison.
    An item with no publish date (``published is None``) cannot be proven fresh,
    so it is dropped and counted as stale — never kept as if recent.
    """
    now = datetime.now(tz=timezone.utc)
    fresh: list[NewsItem] = []
    for item in news_items:
        pub = item.published
        if pub is None:
            continue
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        if (now - pub).days <= max_age_days:
            fresh.append(item)
    return fresh, len(news_items) - len(fresh)


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
        net_sentiment: float -- mean expected impact per event, in [-5, 5].
        top_positive: list[CatalystEvent] -- top 3 positive events by impact.
        top_negative: list[CatalystEvent] -- top 3 negative events by impact.
        category_breakdown: dict[str, int] -- count per category.

    net_sentiment uses mean (not sum) so a large news day with 30+ events
    doesn't collapse to a clamp ceiling and lose discriminative power.
    Natural range of mean(impact_score * prob * sign) with max impact_score=5
    and prob<=1 stays within [-5, 5] already; clamp kept as safety rail.

    Args:
        events: Catalyst events to summarize.
    """
    breakdown: dict[str, int] = {}
    positives: list[CatalystEvent] = []
    negatives: list[CatalystEvent] = []
    impact_sum = 0.0

    for e in events:
        impact_sum += _expected_impact(e)
        breakdown[e.category] = breakdown.get(e.category, 0) + 1
        if e.sentiment == "positive":
            positives.append(e)
        elif e.sentiment == "negative":
            negatives.append(e)

    mean_sentiment = impact_sum / max(len(events), 1)
    net = max(-5.0, min(5.0, mean_sentiment))
    top_pos = rank_catalysts(positives, top_n=3)
    top_neg = rank_catalysts(negatives, top_n=3)

    return {
        "total_catalysts": len(events),
        "net_sentiment": round(net, 2),
        "top_positive": top_pos,
        "top_negative": top_neg,
        "category_breakdown": breakdown,
    }
