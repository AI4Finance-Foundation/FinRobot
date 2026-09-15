"""Tests for finrobot.engine.compute.operators.data_processor.

Hand-calculated verification for all deterministic financial computations.
"""

from __future__ import annotations


import pytest

from finrobot.engine.compute.operators.data_processor import calculate_cagr


# ---------------------------------------------------------------------------
# calculate_cagr
# ---------------------------------------------------------------------------


class TestCalculateCagr:
    def test_basic_cagr(self):
        """CAGR = (end/start)^(1/n) - 1. Source: CFA Institute.
        100 -> 150 over 5 years = (150/100)^(1/5) - 1 ~ 0.08447"""
        result = calculate_cagr(100, 150, 5)
        assert result == pytest.approx(0.08447, abs=0.001)

    def test_cagr_one_year(self):
        """100 -> 200 in 1 year = 100% growth."""
        result = calculate_cagr(100, 200, 1)
        assert result == pytest.approx(1.0)

    def test_cagr_zero_start(self):
        assert calculate_cagr(0, 100, 5) is None

    def test_cagr_negative_start(self):
        assert calculate_cagr(-100, 100, 5) is None

    def test_cagr_zero_years(self):
        assert calculate_cagr(100, 200, 0) is None

    def test_cagr_negative_years(self):
        assert calculate_cagr(100, 200, -3) is None

    def test_cagr_declining_positive_end(self):
        """Declining but still-positive end: formula valid (negative CAGR)."""
        # (50/100)^(1/3) - 1 = 0.7937.. - 1 = -0.2063
        result = calculate_cagr(100, 50, 3)
        assert result is not None
        assert result == pytest.approx(-0.2063, abs=0.001)

    def test_cagr_negative_end(self):
        """Negative end (e.g. revenue restated negative): geometric-mean growth is
        mathematically undefined — old code raised TypeError via float(complex).
        Honest missing (None), never a fabricated rate."""
        assert calculate_cagr(100, -50, 3) is None

    def test_cagr_zero_end(self):
        """Zero end is a degenerate -100% no compounding rate represents — None."""
        assert calculate_cagr(100, 0, 3) is None

    def test_cagr_inf_inputs(self):
        """Inf endpoints are upstream garbage, not a growth observation — None."""
        assert calculate_cagr(float("inf"), 100, 3) is None
        assert calculate_cagr(100, float("inf"), 3) is None

    def test_cagr_same_value(self):
        """No growth: CAGR = 0."""
        result = calculate_cagr(100, 100, 5)
        assert result == pytest.approx(0.0)
