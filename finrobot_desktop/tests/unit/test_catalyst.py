from datetime import datetime, timedelta, timezone

from finrobot.engine.models.financial import CatalystEvent
from finrobot.engine.compute.operators.catalyst import (
    rank_catalysts,
    filter_by_impact,
    classify_catalyst_type,
    extract_catalysts_from_news,
    cluster_near_duplicates,
    filter_fresh_news,
    compute_expected_impact,
    summarize_catalyst_outlook,
)
from finrobot.engine.compute.coordinators.news import NewsItem


def _make_events() -> list[CatalystEvent]:
    return [
        CatalystEvent(
            category="earnings",
            headline="Q4 beat",
            sentiment="positive",
            impact_score=4,
            probability=0.9,
            reasoning="Strong",
        ),
        CatalystEvent(
            category="regulatory",
            headline="EU fine",
            sentiment="negative",
            impact_score=3,
            probability=0.6,
            reasoning="Pending",
        ),
        CatalystEvent(
            category="product_launch",
            headline="New chip",
            sentiment="positive",
            impact_score=5,
            probability=0.7,
            reasoning="M4 launch",
        ),
        CatalystEvent(
            category="market",
            headline="Rate cut",
            sentiment="positive",
            impact_score=2,
            probability=0.4,
            reasoning="Fed",
        ),
    ]


class TestRankCatalysts:
    def test_ranks_by_impact_times_probability(self):
        """Q4 beat: 4×0.9=3.6, New chip: 5×0.7=3.5, EU fine: 3×0.6=1.8, Rate cut: 2×0.4=0.8"""
        events = _make_events()
        ranked = rank_catalysts(events)
        assert ranked[0].headline == "Q4 beat"
        assert ranked[1].headline == "New chip"
        assert ranked[-1].headline == "Rate cut"

    def test_top_n(self):
        ranked = rank_catalysts(_make_events(), top_n=2)
        assert len(ranked) == 2

    def test_empty_list(self):
        assert rank_catalysts([]) == []

    def test_neutral_catalyst_sinks_by_signed_impact(self):
        """rank_catalysts ranks by abs(signed expected impact) = impact × prob ×
        sentiment, so a NEUTRAL headline (sentiment_mult 0 → 0 expected impact)
        sinks below a real directional catalyst even when its raw impact × prob
        is higher. Otherwise a no-signal item ranks above a genuine driver, and
        the /data route's redundant second sort silently overrides the sign-aware
        order (the two sorts disagreed only on neutral events)."""
        high_impact_neutral = CatalystEvent(
            category="market",
            headline="Index reshuffle",
            sentiment="neutral",
            impact_score=5,
            probability=0.9,  # raw 4.5, but signed |0|
            reasoning="mechanical",
        )
        real_positive = CatalystEvent(
            category="earnings",
            headline="Q4 beat",
            sentiment="positive",
            impact_score=3,
            probability=0.8,  # raw 2.4, signed |2.4|
            reasoning="strong",
        )
        ranked = rank_catalysts([high_impact_neutral, real_positive])
        assert [e.headline for e in ranked] == ["Q4 beat", "Index reshuffle"]


class TestFilterByImpact:
    def test_filter_minimum_impact(self):
        filtered = filter_by_impact(_make_events(), min_score=4)
        assert len(filtered) == 2
        assert all(e.impact_score >= 4 for e in filtered)

    def test_filter_by_sentiment(self):
        filtered = filter_by_impact(_make_events(), sentiment="positive")
        assert len(filtered) == 3

    def test_filter_combined(self):
        filtered = filter_by_impact(_make_events(), min_score=4, sentiment="positive")
        assert len(filtered) == 2


class TestCatalystAnalysisNewFields:
    def test_catalyst_analysis_new_fields_defaulted(self):
        from finrobot.engine.models.financial import CatalystAnalysis

        ca = CatalystAnalysis(events=[], overall_sentiment="neutral", key_catalysts=[])
        assert ca.net_sentiment == 0.0
        assert ca.category_breakdown == {}
        assert ca.top_positive == []
        assert ca.top_negative == []


class TestClassifyCatalystType:
    def test_all_categories(self):
        assert classify_catalyst_type("earnings") == "earnings"
        assert classify_catalyst_type("product") == "product_launch"
        assert classify_catalyst_type("regulatory") == "regulatory"
        assert classify_catalyst_type("management") == "management"
        assert classify_catalyst_type("analyst") == "market"
        assert classify_catalyst_type("macro") == "market"
        assert classify_catalyst_type("other") == "market"
        assert classify_catalyst_type("unknown") == "market"  # fallback

    def test_acquisition_news_category_routes_to_acquisition_catalyst(self):
        """BACKLOG A8: news had no M&A bucket, so M&A stories fell into 'other'
        -> catalyst 'market', indistinguishable from generic competitive noise.
        The new 'acquisition' news category must route to the catalyst
        taxonomy's PRE-EXISTING 'acquisition' category (already reachable from
        8-K items 1.01/1.02/2.01 via _sec_8k_to_catalyst — just unreachable
        from news classification before this fix)."""
        assert classify_catalyst_type("acquisition") == "acquisition"


class TestExtractCatalystsFromNews:
    def test_filters_by_importance(self):
        items = [
            NewsItem(
                title="Big Earnings",
                source="WSJ",
                published=datetime.now(tz=timezone.utc),
                url="http://x",
                category="earnings",
                sentiment="positive",
                importance=5,
                summary="Beat estimates",
            ),
            NewsItem(
                title="Minor Update",
                source="Blog",
                published=datetime.now(tz=timezone.utc),
                url="http://y",
                category="other",
                sentiment="neutral",
                importance=1,
                summary="Nothing important",
            ),
        ]
        events = extract_catalysts_from_news(items, min_importance=3)
        assert len(events) == 1
        assert events[0].category == "earnings"
        assert events[0].headline == "Big Earnings"
        assert events[0].probability == 0.7

    def test_empty_input(self):
        assert extract_catalysts_from_news([]) == []

    def test_all_below_threshold(self):
        items = [
            NewsItem(
                title="Low",
                source="Blog",
                published=datetime.now(tz=timezone.utc),
                url="http://z",
                category="other",
                sentiment="neutral",
                importance=2,
                summary="Low importance",
            ),
        ]
        assert extract_catalysts_from_news(items, min_importance=3) == []

    def test_extract_preserves_published_and_url(self):
        """CatalystEvent must carry published + url from NewsItem (traceability)."""
        pub = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
        item = NewsItem(
            title="AAPL Earnings Beat",
            source="Reuters",
            published=pub,
            url="https://reuters.com/aapl-q1",
            category="earnings",
            sentiment="positive",
            importance=5,
            summary="Record quarter",
        )
        events = extract_catalysts_from_news([item], min_importance=3)
        assert len(events) == 1
        assert events[0].published == pub
        assert events[0].url == "https://reuters.com/aapl-q1"


class TestSourceAuthorityWeighting:
    """BACKLOG A5.2: news-derived catalysts get a flat probability=0.7 weight
    UNLESS the source is objectively primary (SEC) or a plaintiff-solicitation
    law-firm PR pattern — no hand-curated 'authoritative outlet' whitelist."""

    def test_standard_source_keeps_prior_default_weight(self):
        """Regression: ordinary journalism (mainstream OR generic/unclassified
        alike) must NOT change from the pre-A5.2 flat 0.7 baseline."""
        item = NewsItem(
            title="Microsoft posts record cloud revenue in Q4",
            source="Reuters",
            published=datetime.now(tz=timezone.utc),
            url="https://reuters.com/msft-q4",
            category="earnings",
            sentiment="positive",
            importance=5,
            summary="Beat estimates",
        )
        events = extract_catalysts_from_news([item], min_importance=3)
        assert events[0].probability == 0.7

    def test_sec_domain_gets_primary_weight(self):
        """A news item that cites back to an SEC filing URL gets the same
        primary-source standing as an 8-K-derived catalyst (1.0)."""
        item = NewsItem(
            title="Microsoft files 8-K on executive transition",
            source="SEC EDGAR",
            published=datetime.now(tz=timezone.utc),
            url="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany",
            category="management",
            sentiment="neutral",
            importance=4,
            summary="Filed 8-K",
        )
        events = extract_catalysts_from_news([item], min_importance=3)
        assert events[0].probability == 1.0

    def test_law_firm_solicitation_headline_downweighted(self):
        """The plaintiff-recruitment boilerplate pattern law firms use to
        solicit class members — must be downweighted regardless of firm name
        (structural pattern, not a name list)."""
        item = NewsItem(
            title=(
                "Rosen Law Firm Encourages Microsoft Corporation Investors to "
                "Inquire About Securities Class Action Investigation - MSFT"
            ),
            source="GlobeNewswire",
            published=datetime.now(tz=timezone.utc),
            url="https://globenewswire.com/news-release/rosen-msft",
            category="regulatory",
            sentiment="negative",
            importance=3,
            summary="Law firm investigation announcement",
        )
        events = extract_catalysts_from_news([item], min_importance=3)
        assert events[0].probability == 0.25

    def test_law_firm_solicitation_downweights_any_firm_name(self):
        """A DIFFERENT firm, same solicitation pattern -- proves this is a
        structural detector, not a hard-coded roster of firm names."""
        item = NewsItem(
            title=(
                "Pomerantz LLP Announces Investigation of Microsoft Corporation "
                "Regarding Possible Securities Fraud"
            ),
            source="PRNewswire",
            published=datetime.now(tz=timezone.utc),
            url="https://prnewswire.com/pomerantz-msft",
            category="regulatory",
            sentiment="negative",
            importance=3,
            summary="Law firm investigation announcement",
        )
        events = extract_catalysts_from_news([item], min_importance=3)
        assert events[0].probability == 0.25

    def test_bare_llp_mention_without_solicitation_language_not_downweighted(self):
        """A law firm named in ORDINARY M&A-advisory coverage (no investor-
        solicitation phrasing) must NOT be downgraded -- a bare 'LLP' mention
        alone is not evidence of a plaintiff-recruitment press release."""
        item = NewsItem(
            title="Skadden Arps LLP advises Microsoft on $2B acquisition of startup",
            source="Bloomberg",
            published=datetime.now(tz=timezone.utc),
            url="https://bloomberg.com/msft-deal",
            category="acquisition",
            sentiment="positive",
            importance=4,
            summary="Advisory role on acquisition",
        )
        events = extract_catalysts_from_news([item], min_importance=3)
        assert events[0].probability == 0.7


class TestComputeExpectedImpact:
    def test_sorts_by_abs_impact(self):
        events = [
            CatalystEvent(
                category="earnings",
                headline="A",
                sentiment="positive",
                impact_score=3,
                probability=0.5,
                reasoning="",
            ),
            CatalystEvent(
                category="regulatory",
                headline="B",
                sentiment="negative",
                impact_score=5,
                probability=0.8,
                reasoning="",
            ),
        ]
        sorted_events = compute_expected_impact(events)
        # B has higher abs impact (5*0.8=4.0) vs A (3*0.5=1.5)
        assert sorted_events[0].headline == "B"
        assert sorted_events[1].headline == "A"

    def test_neutral_events_sort_last(self):
        events = [
            CatalystEvent(
                category="market",
                headline="Neutral",
                sentiment="neutral",
                impact_score=5,
                probability=1.0,
                reasoning="",
            ),
            CatalystEvent(
                category="earnings",
                headline="Positive",
                sentiment="positive",
                impact_score=1,
                probability=0.5,
                reasoning="",
            ),
        ]
        sorted_events = compute_expected_impact(events)
        # Neutral has 0 expected impact, so Positive (0.5) comes first
        assert sorted_events[0].headline == "Positive"

    def test_empty_list(self):
        assert compute_expected_impact([]) == []


class TestSummarizeCatalystOutlook:
    def test_structure(self):
        events = [
            CatalystEvent(
                category="earnings",
                headline="A",
                sentiment="positive",
                impact_score=4,
                probability=0.8,
                reasoning="Good",
            ),
            CatalystEvent(
                category="regulatory",
                headline="B",
                sentiment="negative",
                impact_score=3,
                probability=0.6,
                reasoning="Bad",
            ),
        ]
        summary = summarize_catalyst_outlook(events)
        assert summary["total_catalysts"] == 2
        assert isinstance(summary["net_sentiment"], float)
        assert len(summary["top_positive"]) == 1
        assert len(summary["top_negative"]) == 1
        assert summary["category_breakdown"] == {"earnings": 1, "regulatory": 1}

    def test_net_sentiment_calculation(self):
        events = [
            CatalystEvent(
                category="earnings",
                headline="A",
                sentiment="positive",
                impact_score=4,
                probability=0.8,
                reasoning="Good",
            ),
            CatalystEvent(
                category="regulatory",
                headline="B",
                sentiment="negative",
                impact_score=3,
                probability=0.6,
                reasoning="Bad",
            ),
        ]
        summary = summarize_catalyst_outlook(events)
        # mean = (4*0.8*1.0 + 3*0.6*(-1.0)) / 2 = (3.2 - 1.8) / 2 = 0.7
        assert summary["net_sentiment"] == 0.7

    def test_net_sentiment_natural_ceiling(self):
        """27 all-bullish events: mean stays ~5.0, not collapsed to clamp ceiling."""
        events = [
            CatalystEvent(
                category="earnings",
                headline=f"E{i}",
                sentiment="positive",
                impact_score=5,
                probability=1.0,
                reasoning="Huge",
            )
            for i in range(27)
        ]
        summary = summarize_catalyst_outlook(events)
        # mean per event = 5*1.0*1.0 = 5.0 → net = 5.0 (natural, not force-clamped)
        # Must be in meaningful range and NOT simply 5.0 by clamp trick
        net = summary["net_sentiment"]
        assert 3.0 < net <= 5.0, f"Expected net in (3, 5], got {net}"
        # With mean formula, 27 events all at 5.0 → mean = 5.0 (no information loss)
        assert net == 5.0

    def test_empty_events(self):
        summary = summarize_catalyst_outlook([])
        assert summary["total_catalysts"] == 0
        assert summary["net_sentiment"] == 0.0
        assert summary["top_positive"] == []
        assert summary["top_negative"] == []
        assert summary["category_breakdown"] == {}

    def test_top_3_limit(self):
        """top_positive/top_negative are limited to 3."""
        events = [
            CatalystEvent(
                category="earnings",
                headline=f"Pos{i}",
                sentiment="positive",
                impact_score=i + 1,
                probability=0.5,
                reasoning="",
            )
            for i in range(5)
        ]
        summary = summarize_catalyst_outlook(events)
        assert len(summary["top_positive"]) == 3
        assert len(summary["top_negative"]) == 0


def _make_news_item(
    title: str,
    days_ago: int,
    importance: int = 4,
    sentiment: str = "positive",
) -> NewsItem:
    pub = datetime.now(tz=timezone.utc) - timedelta(days=days_ago)
    return NewsItem(
        title=title,
        source="Test",
        published=pub,
        url=f"http://test/{title.lower().replace(' ', '-')}",
        category="earnings",
        sentiment=sentiment,  # type: ignore[arg-type]  # narrow Literal in test helper
        importance=importance,
        summary=title,
    )


class TestFilterFreshNews:
    def test_drops_stale_items_beyond_30_days(self):
        fresh_item = _make_news_item("Fresh", days_ago=5)
        stale_item = _make_news_item("Stale", days_ago=90)
        result, stale_count = filter_fresh_news([fresh_item, stale_item], max_age_days=30)
        assert len(result) == 1
        assert result[0].title == "Fresh"
        assert stale_count == 1

    def test_keeps_all_within_window(self):
        items = [_make_news_item(f"News{i}", days_ago=i) for i in range(30)]
        result, stale_count = filter_fresh_news(items, max_age_days=30)
        assert len(result) == 30
        assert stale_count == 0

    def test_empty_input(self):
        result, stale_count = filter_fresh_news([], max_age_days=30)
        assert result == []
        assert stale_count == 0

    def test_naive_datetime_treated_as_utc(self):
        """Timezone-naive published should not raise; treated as UTC."""
        naive_pub = datetime.now() - timedelta(days=5)  # no tzinfo
        item = NewsItem(
            title="Naive DT",
            source="Test",
            published=naive_pub,
            url="http://test",
            category="earnings",
            sentiment="positive",
            importance=4,
            summary="Test",
        )
        result, stale_count = filter_fresh_news([item], max_age_days=30)
        assert len(result) == 1
        assert stale_count == 0

    def test_undated_item_dropped_as_stale(self):
        """An item with no publish date (``published is None``) cannot be proven
        fresh, so it must be dropped and counted as stale — never silently kept
        as if recent. Previously the provider fabricated ``now()`` for undated
        news, which let it masquerade as just-published and punch through the
        30-day freshness window into catalyst extraction."""
        fresh = _make_news_item("Fresh", days_ago=2)
        undated = NewsItem(
            title="Undated",
            source="PR-wire",
            published=None,
            url="http://test/undated",
            category="other",
            sentiment="neutral",
            importance=3,
            summary="No date on this one.",
        )
        result, stale_count = filter_fresh_news([fresh, undated], max_age_days=30)
        assert [i.title for i in result] == ["Fresh"]
        assert stale_count == 1


def _cat_event(
    headline: str,
    category: str = "regulatory",
    sentiment: str = "negative",
    impact_score: int = 4,
    probability: float = 0.7,
    days_ago: int = 0,
    url: str | None = None,
    reasoning: str | None = None,
) -> CatalystEvent:
    pub = datetime.now(tz=timezone.utc) - timedelta(days=days_ago)
    return CatalystEvent(
        category=category,  # type: ignore[arg-type]  # narrow Literal in test helper
        headline=headline,
        sentiment=sentiment,  # type: ignore[arg-type]
        impact_score=impact_score,
        probability=probability,
        reasoning=reasoning if reasoning is not None else headline,
        published=pub,
        url=url,
    )


def _msft_distractor_events(n: int = 4) -> list[CatalystEvent]:
    """N unrelated Microsoft-only catalyst events — different categories, no
    shared story-specific entity, far outside any 3-day window.

    cluster_near_duplicates is ALWAYS invoked on the full per-ticker catalyst
    list in production (never an isolated pair) — a real run typically has
    a dozen-plus events across earnings/product/regulatory/management/etc.
    That basket size is what lets the entity-fingerprint signal's basket-wide
    majority vote (_strip_dominant_entities in catalyst.py) correctly single
    out "Microsoft" as the dominant/company token while a story-specific
    entity (e.g. "Activision", "Copilot", "Xbox") stays a MINORITY of the
    basket and is left alone. Tests that isolate just the near-duplicate pair
    with nothing else in the basket are testing an unrealistically small
    input for that mechanism, so they mix in this pool.
    """
    pool = [
        _cat_event(
            "Microsoft posts record cloud revenue in Q4 results",
            category="earnings",
            sentiment="positive",
            days_ago=20,
        ),
        _cat_event(
            "Microsoft unveils new Surface laptop lineup",
            category="product_launch",
            sentiment="positive",
            days_ago=21,
        ),
        _cat_event(
            "Microsoft names new chief financial officer",
            category="management",
            sentiment="neutral",
            days_ago=22,
        ),
        _cat_event(
            "Microsoft completes acquisition of AI startup",
            category="acquisition",
            sentiment="positive",
            days_ago=23,
        ),
    ]
    return pool[:n]


class TestClusterNearDuplicates:
    def test_msft_same_lawsuit_four_law_firms_merge_to_one(self):
        """POSITIVE case: one antitrust suit covered by 4 different law-firm press
        releases — different headlines, SAME entity (one ticker)/category, within
        the 3-day window — must collapse to ONE catalyst with source_count == 4.
        Headlines share the company + action nouns, so token Jaccard clears 0.6."""
        events = [
            _cat_event(
                "Microsoft hit with shareholder antitrust lawsuit over Activision deal",
                days_ago=0,
                url="https://lawfirm-a.com/microsoft-antitrust",
            ),
            _cat_event(
                "Microsoft faces shareholder antitrust lawsuit over Activision deal",
                days_ago=1,
                url="https://lawfirm-b.com/microsoft-antitrust",
            ),
            _cat_event(
                "Shareholder antitrust lawsuit filed against Microsoft over Activision deal",
                days_ago=1,
                url="https://lawfirm-c.com/msft-suit",
            ),
            _cat_event(
                "Microsoft shareholder antitrust lawsuit over Activision deal advances",
                days_ago=2,
                url="https://lawfirm-d.com/msft-antitrust",
            ),
        ]
        clustered = cluster_near_duplicates(events)
        assert len(clustered) == 1
        assert clustered[0].source_count == 4

    def test_distinct_events_never_false_merge(self):
        """NEGATIVE case (the hard门): three GENUINELY distinct same-ticker events
        — earnings beat, product launch, regulatory suit — must stay 3 separate
        catalysts. Different categories alone block merging; even if they shared a
        window they describe different facts. false-merge == 0 is the cardinal rule."""
        events = [
            _cat_event(
                "Microsoft posts record Q4 earnings beat on cloud strength",
                category="earnings",
                sentiment="positive",
                days_ago=0,
            ),
            _cat_event(
                "Microsoft launches new Surface Pro and Copilot+ PCs",
                category="product_launch",
                sentiment="positive",
                days_ago=1,
            ),
            _cat_event(
                "Microsoft faces shareholder antitrust lawsuit over Activision deal",
                category="regulatory",
                sentiment="negative",
                days_ago=1,
            ),
        ]
        clustered = cluster_near_duplicates(events)
        assert len(clustered) == 3
        assert all(e.source_count == 1 for e in clustered)

    def test_same_category_distinct_events_not_merged(self):
        """Even within ONE category, two DIFFERENT regulatory matters (EU antitrust
        probe vs DOJ privacy suit) share too few title tokens (Jaccard < 0.6) and
        different domains — must NOT merge despite same category + window."""
        events = [
            _cat_event(
                "Microsoft faces EU antitrust probe over Teams bundling",
                category="regulatory",
                days_ago=0,
                url="https://reuters.com/eu-teams",
            ),
            _cat_event(
                "Microsoft sued by DOJ over consumer data privacy violations",
                category="regulatory",
                days_ago=1,
                url="https://bloomberg.com/doj-privacy",
            ),
        ]
        clustered = cluster_near_duplicates(events)
        assert len(clustered) == 2

    def test_net_sentiment_not_amplified_by_duplicate_coverage(self):
        """Before/after contrast: the SAME negative event repeated by N sources
        must not drag net_sentiment N times harder than a single offsetting
        positive event. With dedup, one positive + one (deduped) negative of equal
        magnitude net to ~0; without dedup the 4× negative coverage would swamp it."""
        # One positive earnings event.
        positive = _cat_event(
            "Microsoft posts record Q4 earnings beat",
            category="earnings",
            sentiment="positive",
            impact_score=4,
            probability=0.7,
            days_ago=0,
        )
        # Same negative lawsuit reported 4× (equal magnitude to the positive).
        negatives = [
            _cat_event(
                "Microsoft hit with shareholder antitrust lawsuit over Activision deal",
                category="regulatory",
                sentiment="negative",
                impact_score=4,
                probability=0.7,
                days_ago=i,
                url=f"https://lawfirm-{i}.com/msft-antitrust",
            )
            for i in range(4)
        ]
        raw_events = [positive, *negatives]

        # WITHOUT dedup: 1 positive vs 4 identical negatives → net pulled negative.
        raw_net = summarize_catalyst_outlook(raw_events)["net_sentiment"]
        assert raw_net < 0, f"sanity: undeduped net should skew negative, got {raw_net}"

        # WITH dedup: negatives collapse to ONE event → 1 pos + 1 neg of equal
        # magnitude net to ~0 (not dragged 4× negative).
        deduped = cluster_near_duplicates(raw_events)
        assert len(deduped) == 2  # positive + one representative negative
        deduped_net = summarize_catalyst_outlook(deduped)["net_sentiment"]
        assert abs(deduped_net) < 1e-9, f"deduped net should be ~0, got {deduped_net}"
        # And the deduped magnitude is strictly less negative than the inflated one.
        assert deduped_net > raw_net

    def test_undated_events_never_merge(self):
        """An event with no publish date cannot prove temporal proximity, so it is
        never merged even with an otherwise-identical headline (false-merge guard)."""
        a = _cat_event("Microsoft antitrust lawsuit over Activision deal")
        a = a.model_copy(update={"published": None})
        b = _cat_event("Microsoft antitrust lawsuit over Activision deal")
        b = b.model_copy(update={"published": None})
        clustered = cluster_near_duplicates([a, b])
        assert len(clustered) == 2

    def test_singleton_and_empty_normalize_source_count(self):
        assert cluster_near_duplicates([]) == []
        single = cluster_near_duplicates([_cat_event("Lone event")])
        assert len(single) == 1
        assert single[0].source_count == 1

    def test_representative_is_highest_signal(self):
        """The kept representative is the cluster member with the highest
        impact_score × probability, not just the first seen."""
        weak = _cat_event(
            "Microsoft antitrust lawsuit over Activision deal filed",
            impact_score=3,
            probability=0.5,
            days_ago=0,
            url="https://a.com/x",
        )
        strong = _cat_event(
            "Microsoft antitrust lawsuit over Activision deal expands",
            impact_score=5,
            probability=0.9,
            days_ago=1,
            url="https://b.com/y",
        )
        clustered = cluster_near_duplicates([weak, strong])
        assert len(clustered) == 1
        assert clustered[0].headline == strong.headline
        assert clustered[0].source_count == 2

    def test_same_domain_same_day_clusters_low_jaccard(self):
        """Even when titles share few tokens, same URL domain + same calendar day
        is treated as duplicate coverage (a wire re-running the same story under a
        reworded headline)."""
        a = _cat_event(
            "Regulators open formal review of acquisition",
            category="regulatory",
            days_ago=0,
            url="https://wire.example.com/story1",
        )
        b = _cat_event(
            "Deal scrutiny intensifies as officials weigh in",
            category="regulatory",
            days_ago=0,
            url="https://wire.example.com/story2",
        )
        clustered = cluster_near_duplicates([a, b])
        assert len(clustered) == 1
        assert clustered[0].source_count == 2

    def test_outside_window_not_merged(self):
        """Identical headlines >3 days apart are distinct re-occurrences, not
        duplicate coverage of one dated event."""
        a = _cat_event("Microsoft antitrust lawsuit over Activision deal", days_ago=0)
        b = _cat_event("Microsoft antitrust lawsuit over Activision deal", days_ago=10)
        clustered = cluster_near_duplicates([a, b])
        assert len(clustered) == 2


class TestCrossMediaEventFingerprintSignal:
    """BACKLOG A5.1: MSFT M3 target case — cross-media rewrites of ONE real
    event fall below the 0.6 title-Jaccard bar (unlike the boilerplate
    same-lawsuit law-firm re-wording TestClusterNearDuplicates already
    covers), so they escaped clustering entirely: a Copilot-related
    investigation counted 3x, an Xbox layoffs story counted 2x."""

    def test_msft_copilot_investigation_three_law_firms_low_jaccard_still_merges(self):
        """Three different law firms' headlines about ONE Copilot-related
        investigation, deliberately phrased so title Jaccard stays BELOW 0.6
        (unlike the verbatim-boilerplate case already covered) — the
        event-type-bucket + shared-entity signal must still collapse them."""
        events = [
            _cat_event(
                "Rosen Law Firm Investigates Microsoft Corporation on Behalf of "
                "Investors Following Copilot Concerns",
                category="regulatory",
                days_ago=0,
                url="https://globenewswire.com/rosen-msft",
            ),
            _cat_event(
                "Pomerantz LLP Announces Investigation of Microsoft Regarding "
                "Possible Securities Fraud Tied to Copilot",
                category="regulatory",
                days_ago=1,
                url="https://prnewswire.com/pomerantz-msft",
            ),
            _cat_event(
                "Bragar Eagel & Squire Encourages Microsoft Investors With Losses "
                "to Contact the Firm Amid Copilot Probe",
                category="regulatory",
                days_ago=2,
                url="https://accesswire.com/bragar-msft",
            ),
        ]
        # Sanity: confirm this fixture is genuinely a hard case for the OLD
        # signals alone (title Jaccard < 0.6, different domains/days) — if
        # this assertion ever fails the fixture stopped being a real test of
        # the NEW signal and must be reworded harder.
        from finrobot.engine.compute.operators.catalyst import (
            _DEDUP_JACCARD_MIN,
            _jaccard,
            _title_tokens,
        )

        assert (
            _jaccard(_title_tokens(events[0].headline), _title_tokens(events[1].headline))
            < _DEDUP_JACCARD_MIN
        )
        # Mixed into a realistic-size basket (see _msft_distractor_events) so
        # the basket-wide majority vote correctly treats "Microsoft" as the
        # dominant/company token while "Copilot" (present in only 3/7 events)
        # stays a minority and is NOT stripped.
        basket = events + _msft_distractor_events(4)
        clustered = cluster_near_duplicates(basket)
        assert len(clustered) == 5  # 1 merged Copilot cluster + 4 distractors
        merged = next(e for e in clustered if e.category == "regulatory")
        assert merged.source_count == 3

    def test_xbox_layoffs_two_outlets_different_wording_still_merges(self):
        """Two outlets independently reporting ONE Xbox layoffs story with
        substantially different headlines (real cross-media rewrite, not a
        wire re-run) must collapse to one catalyst, not double-count."""
        events = [
            _cat_event(
                "Microsoft plans job cuts in Xbox division amid broader "
                "restructuring, Bloomberg reports",
                category="market",
                sentiment="negative",
                days_ago=0,
                url="https://bloomberg.com/msft-xbox-cuts",
            ),
            _cat_event(
                "Microsoft layoffs hit Xbox unit amid gaming reorganization",
                category="market",
                sentiment="negative",
                days_ago=1,
                url="https://theverge.com/msft-xbox-layoffs",
            ),
        ]
        basket = events + _msft_distractor_events(3)
        clustered = cluster_near_duplicates(basket)
        assert len(clustered) == 4  # 1 merged Xbox pair + 3 distractors
        merged = next(e for e in clustered if e.category == "market")
        assert merged.source_count == 2

    def test_same_bucket_different_subject_still_not_merged(self):
        """Two DIFFERENT layoffs stories at two DIFFERENT units, same window
        and category — same event-type bucket ('layoffs') alone must NOT be
        enough; they share no subject entity beyond the company name, so this
        is the false-merge guard for the new signal specifically."""
        events = [
            _cat_event(
                "Microsoft cuts jobs in Xbox division amid restructuring",
                category="market",
                days_ago=0,
                url="https://a.example.com/xbox",
            ),
            _cat_event(
                "Microsoft announces layoffs in Azure cloud unit",
                category="market",
                days_ago=1,
                url="https://b.example.com/azure",
            ),
        ]
        clustered = cluster_near_duplicates(events)
        assert len(clustered) == 2


class TestDisagreementDisclosure:
    """BACKLOG A5.3: merged sources may report conflicting numbers or wildly
    different importance scores — the representative must disclose that, not
    silently keep only the strongest signal's number."""

    def test_conflicting_dollar_figures_disclosed_not_hidden(self):
        a = _cat_event(
            "Microsoft settles antitrust lawsuit over Activision deal",
            category="regulatory",
            days_ago=0,
            url="https://reuters.com/msft-settle",
            reasoning="Settlement reported at $700 million",
        )
        b = _cat_event(
            "Microsoft reaches settlement in Activision antitrust lawsuit",
            category="regulatory",
            days_ago=1,
            url="https://bloomberg.com/msft-settle",
            reasoning="Sources say the settlement totals $500 million",
        )
        # Realistic-size basket (see _msft_distractor_events docstring) so the
        # basket-wide majority vote leaves "Activision" (2/6 events) unstripped
        # while correctly treating "Microsoft" (6/6) as the dominant token.
        basket = [a, b, *_msft_distractor_events(4)]
        clustered = cluster_near_duplicates(basket)
        merged = next(e for e in clustered if e.category == "regulatory")
        assert merged.source_count == 2
        note = merged.reasoning
        assert "differing figures" in note
        assert "$700 million" in note
        assert "$500 million" in note

    def test_synonymous_dollar_phrasing_is_not_a_false_conflict(self):
        """'$700 million' and '$700M' are the SAME value in different units —
        must NOT be flagged as a conflict (data-lineage lesson: a detector
        with a high false-positive rate on synonymous phrasing is worse than
        useless — see data-lineage-recall on false-positive audit guards)."""
        a = _cat_event(
            "Microsoft settles antitrust lawsuit over Activision deal",
            category="regulatory",
            days_ago=0,
            url="https://reuters.com/msft-settle",
            reasoning="Settlement reported at $700 million",
        )
        b = _cat_event(
            "Microsoft reaches settlement in Activision antitrust lawsuit",
            category="regulatory",
            days_ago=1,
            url="https://bloomberg.com/msft-settle",
            reasoning="Sources say the settlement totals $700M",
        )
        basket = [a, b, *_msft_distractor_events(4)]
        clustered = cluster_near_duplicates(basket)
        merged = next(e for e in clustered if e.category == "regulatory")
        assert merged.source_count == 2
        assert "differing figures" not in merged.reasoning

    def test_rounding_noise_within_tolerance_is_not_a_false_conflict(self):
        """'$1.2 billion' vs '$1.18 billion' is rounding noise (<5% relative
        difference), not a real reported disagreement."""
        a = _cat_event(
            "Microsoft settles antitrust lawsuit over Activision deal",
            category="regulatory",
            days_ago=0,
            url="https://reuters.com/msft-settle",
            reasoning="Settlement reported at $1.2 billion",
        )
        b = _cat_event(
            "Microsoft reaches settlement in Activision antitrust lawsuit",
            category="regulatory",
            days_ago=1,
            url="https://bloomberg.com/msft-settle",
            reasoning="Sources say the settlement totals $1.18 billion",
        )
        basket = [a, b, *_msft_distractor_events(4)]
        clustered = cluster_near_duplicates(basket)
        merged = next(e for e in clustered if e.category == "regulatory")
        assert merged.source_count == 2
        assert "differing figures" not in merged.reasoning

    def test_wide_importance_score_spread_disclosed(self):
        a = _cat_event(
            "Microsoft hit with shareholder antitrust lawsuit over Activision deal",
            category="regulatory",
            impact_score=5,
            days_ago=0,
            url="https://lawfirm-a.com/msft",
        )
        b = _cat_event(
            "Microsoft faces shareholder antitrust lawsuit over Activision deal",
            category="regulatory",
            impact_score=2,
            days_ago=1,
            url="https://lawfirm-b.com/msft",
        )
        clustered = cluster_near_duplicates([a, b])
        assert len(clustered) == 1
        note = clustered[0].reasoning
        assert "Source disagreement" in note
        assert "importance scored 2-5" in note

    def test_narrow_importance_score_spread_not_flagged(self):
        """A 1-point spread is normal LLM classifier jitter across
        independently-classified sources, not real disagreement."""
        a = _cat_event(
            "Microsoft hit with shareholder antitrust lawsuit over Activision deal",
            category="regulatory",
            impact_score=4,
            days_ago=0,
            url="https://lawfirm-a.com/msft",
        )
        b = _cat_event(
            "Microsoft faces shareholder antitrust lawsuit over Activision deal",
            category="regulatory",
            impact_score=3,
            days_ago=1,
            url="https://lawfirm-b.com/msft",
        )
        clustered = cluster_near_duplicates([a, b])
        assert len(clustered) == 1
        assert "Source disagreement" not in clustered[0].reasoning


class TestFreezeValidationRealBasket:
    """2026-07-06 threshold freeze — locks false-merge == 0 on REAL headlines.

    Fixtures are verbatim headlines from the hand-labeled freeze basket (real news
    pulled live via fetch_news for TSLA/LLY/JPM/NVDA/AAPL; blind-labeled BEFORE
    running the clusterer). The full confusion matrix (0 false-merge, 0.50 Jaccard
    margin on the tightest distinct pair) is recorded in the freezing commit. These
    cases are the tightest real stressors: two genuinely-distinct product events in
    the same category + 3-day window (must NOT merge), and a verbatim wire re-run
    (must merge). Headlines come from external news, not from the operator's own
    logic, so a same-source bug can't make this pass spuriously.
    """

    def test_distinct_product_events_same_window_never_merge_tsla(self):
        """TSLA Model Y L (product positioning) vs Robotaxi Miami launch — both map
        to product_launch, both published the same day, different outlets/domains.
        Genuinely distinct developments (Jaccard 0.06); the freeze MUST keep them
        apart. This is the cardinal false-merge guard on real same-category events."""
        model_y = _cat_event(
            "Tesla Takes a Page From Ford, GM and Toyota's Playbook With the Model Y L",
            category="product_launch",
            days_ago=0,
            url="https://www.benzinga.com/trading-ideas/long-ideas/tesla-model-y-l",
        )
        robotaxi = _cat_event(
            "Tesla launches Robotaxi operations in Miami amid growing competition",
            category="product_launch",
            days_ago=0,
            url="https://invezz.com/news/tesla-robotaxi-miami/",
        )
        clustered = cluster_near_duplicates([model_y, robotaxi])
        assert len(clustered) == 2
        assert all(e.source_count == 1 for e in clustered)

    def test_distinct_product_reports_within_window_never_merge_aapl(self):
        """AAPL iPhone-lineup report vs a separate foldable-iPhone report two days
        apart — same category, inside the 3-day window, different domains. Distinct
        reports on one ongoing storyline (Jaccard 0.10); MUST stay separate."""
        lineup = _cat_event(
            "Apple Is Reportedly Planning 5 New iPhones -- Including a $2,500 Foldable. "
            "Here's What It Means for the Stock.",
            category="product_launch",
            days_ago=0,
            url="https://www.fool.com/investing/apple-5-new-iphones/",
        )
        foldable_push = _cat_event(
            "Apple's Foldable iPhone Push Gets Bigger",
            category="product_launch",
            days_ago=2,
            url="https://www.gurufocus.com/news/apples-foldable-iphone-push/",
        )
        clustered = cluster_near_duplicates([lineup, foldable_push])
        assert len(clustered) == 2

    def test_verbatim_wire_rerun_still_merges_jpm(self):
        """The true-merge path stays intact: the SAME Zacks commentary republished a
        day later under an identical title (Jaccard 1.0) collapses to one catalyst.
        Freezing for false-merge=0 must NOT have broken legitimate de-duplication."""
        day1 = _cat_event(
            "Q2 Earnings Season Nears Kickoff: Bank Earnings in Focus",
            category="earnings",
            days_ago=0,
            url="https://www.zacks.com/commentary/2947431/q2-bank-earnings",
        )
        day2 = _cat_event(
            "Q2 Earnings Season Nears Kickoff: Bank Earnings in Focus",
            category="earnings",
            days_ago=1,
            url="https://www.zacks.com/commentary/2947430/q2-bank-earnings",
        )
        clustered = cluster_near_duplicates([day1, day2])
        assert len(clustered) == 1
        assert clustered[0].source_count == 2
