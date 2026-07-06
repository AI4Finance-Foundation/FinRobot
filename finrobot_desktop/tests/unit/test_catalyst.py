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
) -> CatalystEvent:
    pub = datetime.now(tz=timezone.utc) - timedelta(days=days_ago)
    return CatalystEvent(
        category=category,  # type: ignore[arg-type]  # narrow Literal in test helper
        headline=headline,
        sentiment=sentiment,  # type: ignore[arg-type]
        impact_score=impact_score,
        probability=probability,
        reasoning=headline,
        published=pub,
        url=url,
    )


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
