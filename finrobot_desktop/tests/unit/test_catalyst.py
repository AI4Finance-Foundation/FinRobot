from datetime import datetime, timedelta, timezone

from finrobot.engine.models.financial import CatalystEvent
from finrobot.engine.compute.operators.catalyst import (
    rank_catalysts,
    filter_by_impact,
    classify_catalyst_type,
    extract_catalysts_from_news,
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
