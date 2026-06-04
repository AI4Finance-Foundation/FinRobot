"""Tests for earnings surprise compute module.

Reference (Livnat & Mendenhall 2006): ≥ 2% EPS surprise = statistically significant beat.

Test cases:
  eps_actual=1.64, eps_estimated=1.60 → surprise=2.5% → BEAT
  eps_actual=1.55, eps_estimated=1.60 → surprise=-3.125% → MISS
  eps_actual=1.61, eps_estimated=1.60 → surprise=0.625% → INLINE
"""

import pytest
from finrobot.engine.models.financial import EarningsSurprise
from finrobot.engine.compute.operators.earnings import (
    calculate_earnings_surprises,
    _classify_surprise,
    _count_consecutive_beats,
)


class TestSurpriseFormula:
    def test_beat(self):
        """2.5% → BEAT (above +2% threshold)."""
        result = calculate_earnings_surprises(
            "TEST",
            [
                {
                    "date": "2024-10-31",
                    "eps_actual": 1.64,
                    "eps_estimated": 1.60,
                    "revenue_actual": 94_930e6,
                    "revenue_estimated": 94_210e6,
                }
            ],
        )
        assert len(result.surprises) == 1
        s = result.surprises[0]
        assert s.eps_surprise_pct == pytest.approx(2.5, rel=1e-4)
        assert s.eps_direction == "beat"

    def test_miss(self):
        """-3.125% → MISS (below -2% threshold)."""
        result = calculate_earnings_surprises(
            "TEST",
            [
                {
                    "date": "2024-07-31",
                    "eps_actual": 1.55,
                    "eps_estimated": 1.60,
                    "revenue_actual": 85e9,
                    "revenue_estimated": 90e9,
                }
            ],
        )
        s = result.surprises[0]
        assert s.eps_surprise_pct == pytest.approx(-3.125, rel=1e-4)
        assert s.eps_direction == "miss"

    def test_inline(self):
        """0.625% → INLINE (within ±2% band)."""
        result = calculate_earnings_surprises(
            "TEST",
            [
                {
                    "date": "2024-04-30",
                    "eps_actual": 1.61,
                    "eps_estimated": 1.60,
                    "revenue_actual": 90e9,
                    "revenue_estimated": 90e9,
                }
            ],
        )
        s = result.surprises[0]
        assert s.eps_surprise_pct == pytest.approx(0.625, rel=1e-4)
        assert s.eps_direction == "inline"

    def test_zero_estimated_yields_undefined_surprise_not_inline(self):
        """eps_estimated=0 → surprise is undefined (None / 'n/a'), NOT 0% inline.

        A beat against a zero consensus (expected breakeven, actual +$1.00) is a
        genuine event; reporting 0.0/inline masked it and polluted beat_rate and
        avg_eps_surprise_pct (BUG-026).
        """
        result = calculate_earnings_surprises(
            "TEST",
            [
                {
                    "date": "2024-01-31",
                    "eps_actual": 1.00,
                    "eps_estimated": 0.0,
                    "revenue_actual": 1e9,
                    "revenue_estimated": 1e9,
                }
            ],
        )
        s = result.surprises[0]
        assert s.eps_surprise_pct is None
        assert s.eps_direction == "n/a"
        # The lone undefined quarter must not be counted as a non-beat: with no
        # defined quarters, beat_rate / avg are 0.0, not skewed by a fake inline.
        assert result.beat_rate == 0.0
        assert result.avg_eps_surprise_pct == 0.0

    def test_zero_estimate_quarter_excluded_from_aggregates(self):
        """A zero-estimate quarter is dropped from beat_rate/avg denominators."""
        result = calculate_earnings_surprises(
            "TEST",
            [
                # defined beat: +3%
                {
                    "date": "Q2",
                    "eps_actual": 1.03,
                    "eps_estimated": 1.00,
                    "revenue_actual": 1e9,
                    "revenue_estimated": 1e9,
                },
                # undefined (est 0) — must be excluded, not treated as a non-beat
                {
                    "date": "Q1",
                    "eps_actual": 0.50,
                    "eps_estimated": 0.0,
                    "revenue_actual": 1e9,
                    "revenue_estimated": 1e9,
                },
            ],
        )
        # 1 beat out of 1 *defined* quarter → 1.0, not 1/2.
        assert result.beat_rate == pytest.approx(1.0)
        assert result.avg_eps_surprise_pct == pytest.approx(3.0, rel=1e-4)

    def test_none_revenue_preserved_not_fabricated_zero(self):
        """BUG-013: a present-but-None revenue must NOT crash (float(None)) nor be
        fabricated as $0 (false -100% surprise). It stays None / 'n/a' and is
        excluded from the revenue-surprise average."""
        result = calculate_earnings_surprises(
            "TEST",
            [
                {
                    "date": "Q1",
                    "eps_actual": 1.10,
                    "eps_estimated": 1.00,
                    "revenue_actual": None,  # provider omitted revenue
                    "revenue_estimated": 1e9,
                },
            ],
        )
        s = result.surprises[0]
        assert s.revenue_actual is None
        assert s.revenue_surprise_pct is None  # not -100%
        assert s.revenue_direction == "n/a"
        # eps side still computes normally
        assert s.eps_surprise_pct == pytest.approx(10.0, rel=1e-4)
        # undefined revenue quarter excluded → avg stays 0.0 (no defined samples)
        assert result.avg_revenue_surprise_pct == 0.0


class TestClassifySurprise:
    def test_positive_above_threshold(self):
        assert _classify_surprise(2.1) == "beat"

    def test_positive_exactly_threshold(self):
        assert _classify_surprise(2.0) == "beat"

    def test_negative_above_threshold(self):
        assert _classify_surprise(-2.0) == "miss"

    def test_negative_below_threshold(self):
        assert _classify_surprise(-2.1) == "miss"

    def test_inline_positive(self):
        assert _classify_surprise(1.9) == "inline"

    def test_inline_negative(self):
        assert _classify_surprise(-1.9) == "inline"

    def test_zero(self):
        assert _classify_surprise(0.0) == "inline"

    def test_none_is_na(self):
        """Undefined surprise (None, from a zero estimate) → 'n/a', not 'inline'."""
        assert _classify_surprise(None) == "n/a"


class TestBeatRate:
    def test_beat_rate_three_of_five(self):
        """[BEAT, BEAT, MISS, BEAT, INLINE] = 3/5 = 0.6"""
        history = [
            # Most recent first
            {
                "date": f"2024-Q{5 - i}",
                "eps_actual": a,
                "eps_estimated": 1.0,
                "revenue_actual": 1e9,
                "revenue_estimated": 1e9,
            }
            for i, a in enumerate([1.03, 1.03, 0.96, 1.03, 1.01])
            # 3%, 3%, -4%, 3%, 1% → BEAT, BEAT, MISS, BEAT, INLINE
        ]
        result = calculate_earnings_surprises("TEST", history)
        assert result.beat_rate == pytest.approx(3 / 5)

    def test_beat_rate_empty(self):
        """Empty history → beat_rate=0, no crash."""
        result = calculate_earnings_surprises("TEST", [])
        assert result.beat_rate == 0.0
        assert result.consecutive_beats == 0


class TestConsecutiveBeats:
    def test_one_consecutive(self):
        """[BEAT, BEAT, MISS, BEAT] (most recent first) → streak=2."""
        # Most recent = index 0
        surprises = [
            _make_surprise("beat"),
            _make_surprise("beat"),
            _make_surprise("miss"),
            _make_surprise("beat"),
        ]
        assert _count_consecutive_beats(surprises) == 2

    def test_all_beats(self):
        surprises = [_make_surprise("beat")] * 4
        assert _count_consecutive_beats(surprises) == 4

    def test_starts_with_miss(self):
        surprises = [_make_surprise("miss"), _make_surprise("beat"), _make_surprise("beat")]
        assert _count_consecutive_beats(surprises) == 0

    def test_empty(self):
        assert _count_consecutive_beats([]) == 0


class TestEarningsResult:
    def test_avg_eps_surprise(self):
        history = [
            {
                "date": "2024-Q4",
                "eps_actual": 1.10,
                "eps_estimated": 1.00,
                "revenue_actual": 1e9,
                "revenue_estimated": 1e9,
            },  # +10%
            {
                "date": "2024-Q3",
                "eps_actual": 0.94,
                "eps_estimated": 1.00,
                "revenue_actual": 1e9,
                "revenue_estimated": 1e9,
            },  # -6%
        ]
        result = calculate_earnings_surprises("TEST", history)
        assert result.avg_eps_surprise_pct == pytest.approx(2.0)  # (10 + -6) / 2

    def test_ticker_preserved(self):
        result = calculate_earnings_surprises("AAPL", [])
        assert result.ticker == "AAPL"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_surprise(direction: str) -> EarningsSurprise:
    pct = 3.0 if direction == "beat" else (-3.0 if direction == "miss" else 0.5)
    return EarningsSurprise(
        date="2024-01-01",
        eps_actual=1.0,
        eps_estimated=1.0,
        eps_surprise_pct=pct,
        eps_direction=direction,
        revenue_actual=1e9,
        revenue_estimated=1e9,
        revenue_surprise_pct=0.0,
        revenue_direction="inline",
    )
