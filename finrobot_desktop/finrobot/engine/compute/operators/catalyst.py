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
    "acquisition": "acquisition",
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


# ---------------------------------------------------------------------------
# Source authority tiering (BACKLOG A5.2)
# ---------------------------------------------------------------------------
#
# extract_catalysts_from_news previously gave every news-derived event the same
# flat probability=0.7 net-sentiment weight regardless of source. That let a
# flood of law-firm "shareholder alert" press releases (a securities-litigation
# PLAINTIFF-SOLICITATION pattern, not journalism) swamp net_sentiment on a
# lawsuit/investigation storyline — one real matter covered by both real
# journalism AND several law firms soliciting plaintiffs nets out to e.g.
# "9 events / -1.87 BEARISH" when only ~3-4 are independent facts.
#
# Design constraint: NO hand-curated "which outlets are authoritative" domain
# whitelist. A list of "mainstream financial media" is arbitrary, needs endless
# maintenance, and picking winners among legitimate outlets is an editorial
# judgment this deterministic layer should not make. Instead two OBJECTIVE
# anchors:
#   - primary:       url domain is sec.gov (a news item citing back to an SEC
#                     filing) — same standing as the existing 8-K primary-
#                     source weight (_sec_8k_to_catalyst, probability=1.0).
#   - low_authority:  headline matches the SOLICITATION PATTERN securities-
#                     litigation firms use to recruit plaintiffs ("Law Firm
#                     Encourages Investors...", "Shareholder Alert", "if you
#                     have lost money..."). A STRUCTURAL PATTERN, not a name
#                     list — generalizes to any of the dozens of such firms
#                     without naming them. A bare "LLP" mention in ordinary
#                     M&A-advisory news does NOT alone qualify — see
#                     _is_law_firm_solicitation.
#   - standard:       everything else (mainstream press AND unclassified/
#                     generic sources alike) — the pre-existing 0.7 baseline,
#                     UNCHANGED. Deliberately NOT split further into
#                     "mainstream vs aggregator/UGC": there is no objective,
#                     non-arbitrary way to draw that line without a maintained
#                     whitelist, so both stay at the status-quo weight.
_SOURCE_TIER_WEIGHT: dict[str, float] = {
    "primary": 1.0,
    "standard": 0.7,
    "low_authority": 0.25,
}

# Legal-practice suffix markers (not firm names) — matches any securities-
# litigation shop without a maintained roster of firm names.
_LAW_FIRM_ENTITY_RE = re.compile(
    r"\b(law firm|law offices?|law group|llp|attorneys?)\b", re.IGNORECASE
)

# Unambiguous plaintiff-solicitation boilerplate. Any ONE hit alone qualifies —
# this phrasing essentially never appears in ordinary journalism.
_SOLICITATION_PHRASE_RE = re.compile(
    r"encourages?\s[^.]{0,60}investors"
    r"|shareholder alert|investor alert"
    r"|announces?\s(?:an\s)?investigation"
    r"|investigat(?:ing|ion)\s(?:of\s)?(?:claims|potential claims)"
    r"|if you (?:purchased|have lost|suffered losses|lost money)"
    r"|class action (?:lawsuit\s)?(?:on behalf of|against)"
    r"|securities fraud (?:investigation|class action)",
    re.IGNORECASE,
)


def _is_law_firm_solicitation(headline: str) -> bool:
    """True iff `headline` is a plaintiff-recruitment press-release pattern.

    Requires EITHER an unambiguous solicitation phrase alone, OR a law-firm
    entity marker (LLP/"Law Firm"/etc.) co-occurring with "invest" — a bare LLP
    mention in ordinary M&A-advisory or court-ruling coverage (no investor-
    solicitation language) must NOT alone downgrade a legitimate source.
    """
    if _SOLICITATION_PHRASE_RE.search(headline):
        return True
    return bool(_LAW_FIRM_ENTITY_RE.search(headline)) and bool(
        re.search(r"invest", headline, re.IGNORECASE)
    )


def _source_authority_tier(headline: str, url: str | None) -> str:
    """Classify a news-derived catalyst's source into a net-sentiment weight tier.

    See the module comment above ``_SOURCE_TIER_WEIGHT`` for the design
    rationale (no arbitrary "authoritative outlet" whitelist).
    """
    domain = _url_domain(url)
    if domain is not None and (domain == "sec.gov" or domain.endswith(".sec.gov")):
        return "primary"
    if _is_law_firm_solicitation(headline):
        return "low_authority"
    return "standard"


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
    """Map news.py 8-category taxonomy to catalyst's 6-category taxonomy.

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
        tier = _source_authority_tier(item.title, item.url)
        events.append(
            CatalystEvent(
                category=cast(Any, classify_catalyst_type(item.category)),
                headline=item.title,
                sentiment=item.sentiment,
                impact_score=item.importance,
                # Internal net-sentiment WEIGHT, tiered by source authority
                # (BACKLOG A5.2 — see _SOURCE_TIER_WEIGHT / _source_authority_tier):
                # primary-source (SEC) 1.0, standard news 0.7 (the prior flat
                # default), plaintiff-solicitation law-firm PR 0.25. NOT a displayed
                # forecast — a past event carries no real occurrence probability.
                # CatalystEvent.probability is exclude=True (see the field
                # docstring), so this weight never reaches an export bundle or
                # response; the report shows impact and direction only.
                probability=_SOURCE_TIER_WEIGHT[tier],
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
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "at",
        "by",
        "from",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "after",
        "over",
        "amid",
        "into",
        "says",
        "said",
        "new",
        "report",
        "reports",
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


# ---------------------------------------------------------------------------
# Cross-media event-fingerprint signal (BACKLOG A5.1)
# ---------------------------------------------------------------------------
#
# The title-Jaccard / same-domain-same-day rules above catch near-VERBATIM
# re-runs and boilerplate law-firm re-wording (which shares the company name +
# action nouns, e.g. "Microsoft hit with shareholder antitrust lawsuit ..." x4).
# They do NOT catch genuine cross-media coverage of one event where two
# outlets independently write substantially different headlines — e.g.
# "Microsoft to cut Xbox jobs" vs "Xbox layoffs hit gaming unit amid
# restructuring", or a Copilot-related shareholder investigation covered by
# several law firms whose headlines happen to fall BELOW the 0.6 Jaccard bar.
#
# Fix: a SECOND, narrower merge signal — same category + window (inherited
# from the caller) AND both headlines fall in the SAME bounded event-type
# bucket (a small controlled vocabulary of unambiguous action words: legal
# action, layoffs, M&A, leadership change) AND they share a non-trivial
# "subject entity" token (a capitalized phrase — a product/unit/agency name)
# after stripping the ticker's own company name (the dominant capitalized
# token across the whole basket, since every event here is about ONE company
# by construction — see _strip_dominant_entities).
#
# Why this stays false-merge-safe on the frozen basket
# (tests/unit/test_catalyst.py::TestFreezeValidationRealBasket): the tightest
# real distinct pairs there are BOTH product_launch stories (Tesla Model Y L
# vs Robotaxi Miami; Apple iPhone lineup vs foldable iPhone) — neither
# headline contains a legal/layoffs/M&A/leadership keyword, so
# _event_type_bucket returns None for both and this signal never fires. The
# one same-CATEGORY distinct pair that DOES hit a bucket (EU antitrust probe
# vs DOJ privacy suit, both "legal_action") shares no subject entity beyond
# the company name (EU/Teams vs DOJ), so it also stays unmerged. Purely
# additive: this signal only ADDS recall on top of the existing rules, never
# removes an existing merge.
_EVENT_TYPE_KEYWORD_BUCKETS: dict[str, tuple[str, ...]] = {
    "legal_action": (
        # "investigat" is a stem (not a full word) so it matches every
        # conjugation — investigate/investigates/investigating/investigation/
        # investigations — with one entry instead of enumerating each.
        "lawsuit",
        "sues",
        "sued",
        "suit",
        "litigation",
        "investigat",
        "probe",
        "antitrust",
        "class action",
        "settlement",
        "fine",
        "fined",
        "penalty",
    ),
    "layoffs": (
        "layoffs",
        "layoff",
        "job cuts",
        "cuts jobs",
        "cutting jobs",
        "workforce reduction",
        "job losses",
        "headcount reduction",
        "downsizing",
        "job cut",
    ),
    "mna": (
        "acquire",
        "acquires",
        "acquisition",
        "merger",
        "merges",
        "buyout",
        "takeover",
        "divest",
        "divestiture",
    ),
    "leadership": (
        "resigns",
        "resignation",
        "steps down",
        "appoints",
        "appointment",
        "names ceo",
        "ceo departure",
        "ousted",
    ),
}


def _event_type_bucket(title: str) -> str | None:
    """Bucket name if `title` contains one of its keyword phrases, else None.

    Substring match on the lowercased title (not tokenized) so multi-word
    phrases like "class action" and "job cuts" match. First matching bucket
    wins; in practice the buckets are disjoint (a headline rarely straddles
    two of these unambiguous action-word sets).
    """
    lowered = title.lower()
    for bucket, phrases in _EVENT_TYPE_KEYWORD_BUCKETS.items():
        if any(phrase in lowered for phrase in phrases):
            return bucket
    return None


_ENTITY_WORD_RE = re.compile(r"\b[A-Z][a-zA-Z']*\b")

# Generic corporate/legal boilerplate nouns that ARE capitalized (sentence-
# case titles) but carry ZERO discriminating power for "is this the SAME
# specific story" — nearly every law-firm PR contains "Investors"/"Firm"/
# "Corporation"/etc. regardless of which underlying matter it covers. A
# SEPARATE set from _TITLE_STOPWORDS (which the frozen title-Jaccard
# calibration — see _DEDUP_JACCARD_MIN — already depends on; extending that
# set would silently re-calibrate the existing frozen threshold instead of
# only affecting this new signal).
_GENERIC_ENTITY_WORDS: frozenset[str] = frozenset(
    {
        "investors",
        "investor",
        "shareholder",
        "shareholders",
        "firm",
        "firms",
        "corporation",
        "corp",
        "inc",
        "llc",
        "llp",
        "law",
        "announces",
        "announcement",
        "encourages",
        "investigation",
        "investigations",
        "investigates",
        "regarding",
        "possible",
        "losses",
        "contact",
    }
)


def _headline_entities(title: str) -> frozenset[str]:
    """Coarse proper-noun candidate set: individual Title-Case words, minus
    generic sentence-starter stopwords (reuses _TITLE_STOPWORDS), generic
    corporate/legal boilerplate nouns (_GENERIC_ENTITY_WORDS), and single
    characters.

    Deliberately PER-WORD, not per-phrase: a distinctive subject like
    "Copilot" must match across headlines even when it sits in a different
    surrounding phrase in each ("... Following Copilot Concerns" vs "...
    Amid Copilot Probe") — joining each run of consecutive capitalized words
    into ONE phrase string would bury it inside two different, non-equal
    phrase strings and never match.

    A heuristic, NOT real NER — it over-captures (ordinary capitalized verbs
    at a headline's start) as well as under-captures (lowercase-styled
    brands like "iPhone"). That is acceptable because it is used only as a
    conjunctive ADDITIONAL signal alongside _event_type_bucket, both gated
    behind the caller's existing same-category + same-window guard —
    imprecision here can only affect pairs that already share a
    legal/layoffs/M&A/leadership keyword bucket.
    """
    return frozenset(
        w.lower()
        for w in _ENTITY_WORD_RE.findall(title)
        if len(w) >= 2
        and w.lower() not in _TITLE_STOPWORDS
        and w.lower() not in _GENERIC_ENTITY_WORDS
    )


def _strip_dominant_entities(entity_sets: list[frozenset[str]]) -> list[frozenset[str]]:
    """Remove tokens present in a STRICT MAJORITY of `entity_sets`.

    Every event clustered together is about the SAME company (per-ticker
    construction — see module docstring), so the company's own name is by far
    the most common capitalized token across the basket and carries ZERO
    discriminating power for "is this the SAME underlying story". Stripping it
    prevents "both headlines mention Microsoft" from masquerading as a shared
    subject entity.
    """
    counts: dict[str, int] = {}
    for entities in entity_sets:
        for token in entities:
            counts[token] = counts.get(token, 0) + 1
    total = len(entity_sets)
    dominant = {tok for tok, n in counts.items() if total > 0 and n * 2 > total}
    if not dominant:
        return entity_sets
    return [entities - dominant for entities in entity_sets]


def _is_near_duplicate(
    a: CatalystEvent,
    b: CatalystEvent,
    entities_a: frozenset[str] = frozenset(),
    entities_b: frozenset[str] = frozenset(),
) -> bool:
    """Conservative near-duplicate test for two SAME-ticker catalyst events.

    See module comment for the full rationale. Returns True only when
    (same category AND published within _DEDUP_WINDOW_DAYS, both dated) AND
    ANY of:
      - title Jaccard >= _DEDUP_JACCARD_MIN
      - same URL domain AND same day
      - same event-type bucket (BACKLOG A5.1) AND a shared subject entity
        (``entities_a``/``entities_b``, dominant company-name token already
        stripped by the caller — see _strip_dominant_entities)
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
    bucket_a = _event_type_bucket(a.headline)
    if (
        bucket_a is not None
        and bucket_a == _event_type_bucket(b.headline)
        and entities_a & entities_b
    ):
        return True
    return False


# ---------------------------------------------------------------------------
# Disagreement disclosure across merged sources (BACKLOG A5.1/A5.3)
# ---------------------------------------------------------------------------
#
# cluster_near_duplicates picks ONE representative headline/reasoning per
# cluster and discards the rest — correct for the common case (re-worded
# coverage of the same fact), but wrong when the sources actually report
# DIFFERENT numbers (e.g. differing settlement/deal-size figures) or the
# classifier scored their importance very differently. Silently keeping only
# the highest-signal member's number would hide a real disagreement, which
# violates "never hide a conflict" (core contract 2 — always disclose,
# never fabricate a single answer where sources disagree). So: flag it,
# appended to the representative's `reasoning` — deterministic, regex-based,
# no LLM, no schema change (the field already exists and was previously
# unused by any frontend consumer).
_SCORE_VARIANCE_THRESHOLD = 2  # min-max spread on the 1-5 importance scale
# LLM classifier noise of +/-1 point across independently-classified sources
# is normal (see llm-pipeline-recall: rubric calibration is non-deterministic);
# a spread this wide signals the SOURCES likely disagree on materiality, not
# just classifier jitter.

_NUMERIC_CONFLICT_TOLERANCE = 0.05  # relative — rounding noise, not a real conflict

_MONEY_RE = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?\s?(?:million|billion|trillion|mn|bn|tn|[MBKT])?\b",
    re.IGNORECASE,
)
_MONEY_SCALE: dict[str, float] = {
    "k": 1e3,
    "m": 1e6,
    "mn": 1e6,
    "million": 1e6,
    "b": 1e9,
    "bn": 1e9,
    "billion": 1e9,
    "t": 1e12,
    "tn": 1e12,
    "trillion": 1e12,
}
_PERCENT_RE = re.compile(r"\d+(?:\.\d+)?\s?%")
_HEADCOUNT_RE = re.compile(
    r"\d[\d,]*\s?(?:jobs|employees|workers|positions|roles|staff)\b", re.IGNORECASE
)


def _normalized_money(raw: str) -> float | None:
    """ "$700 million" and "$700M" both normalize to 700_000_000.0 — synonymous
    phrasing must NOT read as a numeric conflict; only genuinely different
    values should.
    """
    num_match = re.search(r"[\d,]+(?:\.\d+)?", raw)
    if not num_match:
        return None
    try:
        num = float(num_match.group(0).replace(",", ""))
    except ValueError:
        return None
    suffix_match = re.search(r"(million|billion|trillion|mn|bn|tn|[MBKT])\b", raw, re.IGNORECASE)
    scale = _MONEY_SCALE.get(suffix_match.group(0).lower(), 1.0) if suffix_match else 1.0
    return round(num * scale, 2)


def _numeric_claims(text: str) -> dict[str, dict[float, str]]:
    """Extract {kind: {normalized_value: first_raw_text_seen}} from `text`.

    kind in {"money", "percent", "headcount"} — separate namespaces so a
    $700M figure never collides with a 700-person headcount. The raw text is
    kept only as the human-readable label for the first occurrence of each
    distinct value; the normalized float is what determines "same vs different".
    """
    claims: dict[str, dict[float, str]] = {"money": {}, "percent": {}, "headcount": {}}
    for m in _MONEY_RE.finditer(text):
        value = _normalized_money(m.group(0))
        if value is not None:
            claims["money"].setdefault(value, m.group(0).strip())
    for m in _PERCENT_RE.finditer(text):
        try:
            value = float(m.group(0).replace("%", "").strip())
        except ValueError:
            continue
        claims["percent"].setdefault(value, m.group(0).strip())
    for m in _HEADCOUNT_RE.finditer(text):
        num_match = re.search(r"[\d,]+", m.group(0))
        if not num_match:
            continue
        try:
            value = float(num_match.group(0).replace(",", ""))
        except ValueError:
            continue
        claims["headcount"].setdefault(value, m.group(0).strip())
    return claims


def _distinct_value_clusters(values: dict[float, str]) -> list[tuple[float, str]]:
    """Collapse values within _NUMERIC_CONFLICT_TOLERANCE (relative) of the
    previous accepted value — rounding/precision noise across sources ("$1.2
    billion" vs "$1.18 billion") must not read as a conflict. Chained
    (each candidate compared to the last ACCEPTED cluster, not to every prior
    value) — adequate for the small, mostly-bimodal value sets real headlines
    produce.
    """
    ordered = sorted(values.items())
    if not ordered:
        return []
    clusters = [ordered[0]]
    for value, raw in ordered[1:]:
        last_value = clusters[-1][0]
        tolerance = max(abs(last_value), abs(value)) * _NUMERIC_CONFLICT_TOLERANCE
        if abs(value - last_value) > tolerance:
            clusters.append((value, raw))
    return clusters


def _numeric_conflict_note(members: list[CatalystEvent]) -> str | None:
    """ "[Sources report differing figures: X; Y]" when merged members cite
    genuinely DIFFERENT (beyond rounding tolerance) numeric values of the same
    kind. Synonymous phrasing normalizes to the same value and never triggers
    a false conflict — only real disagreement does.
    """
    merged: dict[str, dict[float, str]] = {"money": {}, "percent": {}, "headcount": {}}
    for member in members:
        text = f"{member.headline} {member.reasoning}"
        for kind, values in _numeric_claims(text).items():
            for value, raw in values.items():
                merged[kind].setdefault(value, raw)
    conflicting: list[str] = []
    for values in merged.values():
        clusters = _distinct_value_clusters(values)
        if len(clusters) > 1:
            conflicting.extend(raw for _, raw in clusters)
    if not conflicting:
        return None
    return "[Sources report differing figures: " + "; ".join(conflicting) + "]"


def _score_variance_note(members: list[CatalystEvent]) -> str | None:
    """ "[Source disagreement: importance scored X-Y across N reports]" when the
    classifier's per-source importance spread is >= _SCORE_VARIANCE_THRESHOLD.
    """
    scores = [m.impact_score for m in members]
    spread = max(scores) - min(scores)
    if spread < _SCORE_VARIANCE_THRESHOLD:
        return None
    return (
        f"[Source disagreement: importance scored {min(scores)}-{max(scores)} "
        f"across {len(members)} reports]"
    )


def _disagreement_note(members: list[CatalystEvent]) -> str | None:
    """Combine the numeric-conflict and score-variance notes, if either fires.

    Never hides a disagreement to keep the representative's reasoning tidy —
    both notes are additive and independent.
    """
    parts = [n for n in (_numeric_conflict_note(members), _score_variance_note(members)) if n]
    return " ".join(parts) if parts else None


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

    # Precompute the cross-media entity-fingerprint signal once (BACKLOG A5.1):
    # the company's own name is stripped basket-wide (see
    # _strip_dominant_entities) so it never masquerades as a shared subject
    # entity between two otherwise-unrelated headlines.
    entity_sets = _strip_dominant_entities([_headline_entities(e.headline) for e in events])

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
            if find(i) != find(j) and _is_near_duplicate(
                events[i], events[j], entity_sets[i], entity_sets[j]
            ):
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
        if len(members) > 1:
            # Merged sources may disagree — never hide it (BACKLOG A5.3).
            note = _disagreement_note([events[k] for k in members])
            if note:
                rep = rep.model_copy(update={"reasoning": f"{rep.reasoning} {note}".strip()})
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
