import pytest
from finagent.engine.models.financial import CatalystEvent
from finagent.engine.compute.catalyst import rank_catalysts, filter_by_impact


def _make_events() -> list[CatalystEvent]:
    return [
        CatalystEvent(category="earnings", headline="Q4 beat", sentiment="positive", impact_score=4, probability=0.9, reasoning="Strong"),
        CatalystEvent(category="regulatory", headline="EU fine", sentiment="negative", impact_score=3, probability=0.6, reasoning="Pending"),
        CatalystEvent(category="product_launch", headline="New chip", sentiment="positive", impact_score=5, probability=0.7, reasoning="M4 launch"),
        CatalystEvent(category="market", headline="Rate cut", sentiment="positive", impact_score=2, probability=0.4, reasoning="Fed"),
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
