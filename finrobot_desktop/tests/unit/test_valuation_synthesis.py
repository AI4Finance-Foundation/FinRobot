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
