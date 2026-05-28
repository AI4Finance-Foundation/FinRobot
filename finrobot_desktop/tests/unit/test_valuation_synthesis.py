"""Tests for valuation synthesis with confidence-weighted averaging."""

import pytest
from finrobot.engine.models.financial import ValuationMethod
from finrobot.engine.compute.valuation_synthesis import synthesize_valuations


class TestSynthesizeValuations:
    def test_weighted_average_three_methods(self):
        """DCF: mid=245, conf=0.5. EV/EBITDA: mid=250, conf=0.3. P/E: mid=240, conf=0.2
        Weighted = (245×0.5 + 250×0.3 + 240×0.2) / 1.0 = (122.5 + 75 + 48) / 1.0 = 245.5
        upside = (245.5 - 230) / 230 = 0.06739"""
        methods = [
            ValuationMethod(name="DCF", low=210, mid=245, high=290, confidence=0.5, source="DCF"),
            ValuationMethod(
                name="EV/EBITDA", low=220, mid=250, high=280, confidence=0.3, source="Comps"
            ),
            ValuationMethod(name="P/E", low=210, mid=240, high=260, confidence=0.2, source="PE"),
        ]
        result = synthesize_valuations(methods, current_price=230.0)
        assert result.weighted_price == pytest.approx(245.5, abs=0.01)
        assert result.upside_downside == pytest.approx(0.06739, abs=0.001)
        assert len(result.methods) == 3

    def test_single_method_returns_none_weighted_price(self):
        """Single-method synthesis has no cross-check — weighted_price must be None."""
        methods = [
            ValuationMethod(name="DCF", low=200, mid=250, high=300, confidence=1.0, source="DCF")
        ]
        result = synthesize_valuations(methods, current_price=200.0)
        assert result.weighted_price is None
        assert result.upside_downside is None
        assert len(result.methods) == 1

    def test_empty_methods_raises(self):
        with pytest.raises(ValueError):
            synthesize_valuations([], current_price=200.0)

    def test_downside_case(self):
        """When weighted < current with ≥2 methods, upside_downside is negative."""
        methods = [
            ValuationMethod(name="DCF", low=150, mid=180, high=200, confidence=0.7, source="DCF"),
            ValuationMethod(name="Comps", low=155, mid=185, high=215, confidence=0.5, source="PE"),
        ]
        result = synthesize_valuations(methods, current_price=200.0)
        # weighted = (180*0.7 + 185*0.5) / 1.2 = (126 + 92.5) / 1.2 = 182.08...
        assert result.weighted_price is not None
        assert result.upside_downside is not None
        assert result.upside_downside < 0

    def test_no_outlier_when_spread_within_threshold(self):
        """Methods within 30% of each other: outlier_methods empty, warnings empty."""
        methods = [
            ValuationMethod(name="DCF", low=200, mid=245, high=290, confidence=0.5, source="DCF"),
            ValuationMethod(
                name="EV/EBITDA", low=220, mid=250, high=280, confidence=0.3, source="Comps"
            ),
        ]
        # median = 247.5; DCF deviation = |245-247.5|/247.5 = 1.0% < 30%
        result = synthesize_valuations(methods, current_price=230.0)
        assert result.outlier_methods == []
        assert result.warnings == []

    def test_outlier_flagged_aapl_spread(self):
        """DCF $86 vs Comps $221 — AAPL-like 157% spread.

        median = ($86 + $221) / 2 = $153.50
        DCF deviation  = |86  - 153.5| / 153.5 = 43.98% > 30% → outlier
        Comps deviation = |221 - 153.5| / 153.5 = 43.98% > 30% → outlier
        Both methods should be flagged.
        """
        methods = [
            ValuationMethod(name="DCF", low=70, mid=86, high=100, confidence=0.5, source="DCF"),
            ValuationMethod(
                name="Comps", low=190, mid=221, high=260, confidence=0.5, source="Comps"
            ),
        ]
        result = synthesize_valuations(methods, current_price=180.0)
        assert "DCF" in result.outlier_methods
        assert "Comps" in result.outlier_methods
        assert len(result.warnings) == 2
        # Both warning strings must mention the method name and dollar figure
        assert any("DCF" in w and "$86.00" in w for w in result.warnings)
        assert any("Comps" in w and "$221.00" in w for w in result.warnings)

    def test_outlier_flagged_dcf_only(self):
        """When only one method is the outlier, only that one appears in outlier_methods.

        Three methods: $100, $120, $200.
        median = $120
        $100 deviation = 16.7% < 30% → clean
        $120 deviation = 0%   < 30% → clean
        $200 deviation = 66.7% > 30% → outlier
        """
        methods = [
            ValuationMethod(name="DDM", low=85, mid=100, high=115, confidence=0.3, source="DDM"),
            ValuationMethod(
                name="Comps", low=110, mid=120, high=130, confidence=0.4, source="Comps"
            ),
            ValuationMethod(
                name="LBO", low=175, mid=200, high=225, confidence=0.3, source="LBO"
            ),
        ]
        result = synthesize_valuations(methods, current_price=150.0)
        assert result.outlier_methods == ["LBO"]
        assert len(result.warnings) == 1
        assert "LBO" in result.warnings[0]

    def test_single_method_no_outlier_check(self):
        """Single-method synthesis skips outlier logic; outlier_methods/warnings empty."""
        methods = [
            ValuationMethod(name="DCF", low=200, mid=250, high=300, confidence=1.0, source="DCF")
        ]
        result = synthesize_valuations(methods, current_price=200.0)
        assert result.outlier_methods == []
        assert result.warnings == []
