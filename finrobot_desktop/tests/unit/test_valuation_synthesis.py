"""Tests for valuation synthesis with confidence-weighted averaging."""

import pytest
from finrobot.engine.models.financial import ValuationMethod
from finrobot.engine.compute.operators.valuation_synthesis import (
    VERDICT_BUY_THRESHOLD,
    VERDICT_SELL_THRESHOLD,
    resolve_canonical_thesis,
    synthesize_valuations,
    verdict_from_upside,
)


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
        """DCF $86 vs Comps $221 — AAPL-like 157% spread (2.57x ratio).

        median = ($86 + $221) / 2 = $153.50
        DCF deviation  = |86  - 153.5| / 153.5 = 43.98% > 30% → soft outlier
        Comps deviation = |221 - 153.5| / 153.5 = 43.98% > 30% → soft outlier
        Both methods flagged as outliers. The 2.57x mid spread (221/86) ALSO
        trips the pairwise-ratio reliability gate (> 2.0x), so a third UNRELIABLE
        banner is appended and reliable=False — a 2.57x disagreement has no
        honest midpoint to publish.
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
        assert result.reliable is False
        assert len(result.warnings) == 3
        # Both soft-outlier warnings must mention the method name and dollar figure
        assert any("DCF" in w and "$86.00" in w for w in result.warnings)
        assert any("Comps" in w and "$221.00" in w for w in result.warnings)
        # ...plus the pairwise-ratio UNRELIABLE banner.
        assert any("UNRELIABLE" in w and "2.6x" in w for w in result.warnings)

    def test_outlier_flagged_dcf_only(self):
        """When only one method is the outlier, only that one appears in outlier_methods.

        Three methods: $100, $120, $200.
        median = $120
        $100 deviation = 16.7% < 30% → clean
        $120 deviation = 0%   < 30% → clean
        $200 deviation = 66.7% > 30% → outlier (and > 50% → trips reliability gate)
        """
        methods = [
            ValuationMethod(name="DDM", low=85, mid=100, high=115, confidence=0.3, source="DDM"),
            ValuationMethod(
                name="Comps", low=110, mid=120, high=130, confidence=0.4, source="Comps"
            ),
            ValuationMethod(name="LBO", low=175, mid=200, high=225, confidence=0.3, source="LBO"),
        ]
        result = synthesize_valuations(methods, current_price=150.0)
        assert result.outlier_methods == ["LBO"]
        # LBO's 66.7% deviation exceeds the 50% reliability gate too, so the
        # synthesis flags itself unreliable and appends the UNRELIABLE banner
        # on top of the per-method spread warning.
        assert result.reliable is False
        assert len(result.warnings) == 2
        assert any("LBO" in w and "deviates" in w for w in result.warnings)
        assert any("UNRELIABLE" in w for w in result.warnings)

    def test_single_method_no_outlier_check(self):
        """Single-method synthesis skips outlier logic; outlier_methods/warnings empty."""
        methods = [
            ValuationMethod(name="DCF", low=200, mid=250, high=300, confidence=1.0, source="DCF")
        ]
        result = synthesize_valuations(methods, current_price=200.0)
        assert result.outlier_methods == []
        assert result.warnings == []

    def test_reliable_false_msft_2_method_disagreement_2026_06_05(self):
        """Regression for the 2026-06-05 MSFT bug: DCF $189.65 (c=0.85) vs
        comps_pe $487.31 (c=0.55) → weighted $306.59. The two methods disagree
        by 2.57x (487.31/189.65).

        The OLD median gate was structurally blind here: with two methods the
        median is their midpoint ($338.48), so each deviates only 44% — under the
        50% gate — and the pipeline shipped a confident 'SELL $306.59' built on
        the average of two numbers that don't corroborate. The pairwise-ratio
        gate (max/min = 2.57x > 2.0x) now trips reliable=False so the headline
        target/verdict is withheld.
        """
        methods = [
            ValuationMethod(
                name="dcf", low=151.72, mid=189.65, high=227.58, confidence=0.85, source="DCF"
            ),
            ValuationMethod(
                name="comps_pe", low=438.58, mid=487.31, high=536.04, confidence=0.55, source="PE"
            ),
        ]
        result = synthesize_valuations(methods, current_price=425.0)
        # weighted = (189.65*0.85 + 487.31*0.55)/1.40 = 306.59 — still computed
        # for the audit trail, but must NOT be published as a headline target.
        assert result.weighted_price == pytest.approx(306.59, abs=0.05)
        assert result.reliable is False
        assert any("UNRELIABLE" in w and "corroboration limit" in w for w in result.warnings)

    def test_reliable_true_when_methods_corroborate_within_2x(self):
        """Two methods within the 2x corroboration band stay RELIABLE — a soft
        30% outlier flag does not by itself withhold the target. DCF $200 vs
        Comps $380 = 1.9x ratio (just under the 2.0x gate): both deviate 31%
        from the $290 median so both are soft outliers, yet reliable=True, so a
        target still publishes."""
        methods = [
            ValuationMethod(name="DCF", low=180, mid=200, high=220, confidence=0.5, source="DCF"),
            ValuationMethod(
                name="Comps", low=350, mid=380, high=410, confidence=0.5, source="Comps"
            ),
        ]
        result = synthesize_valuations(methods, current_price=300.0)
        assert result.reliable is True
        # Two soft outlier warnings (both 31% > 30%), no UNRELIABLE banner.
        assert len(result.warnings) == 2
        assert not any("UNRELIABLE" in w for w in result.warnings)

    def test_reliable_false_tsla_dcf_comps_54pct_spread(self):
        """Reproduces the 2026-05-28 TSLA gate failure: DCF $5.88 vs Comps
        $19.54 → median $12.71, both deviate 54% > 50%. The synthesis must
        flag itself UNRELIABLE so the pipeline withholds the headline
        target/verdict instead of shipping SELL @ $11.25."""
        methods = [
            ValuationMethod(name="DCF", low=4.0, mid=5.88, high=8.0, confidence=0.85, source="DCF"),
            ValuationMethod(
                name="Comps", low=15.0, mid=19.54, high=24.0, confidence=0.55, source="Comps"
            ),
        ]
        result = synthesize_valuations(methods, current_price=440.36)
        assert result.reliable is False
        # weighted_price is still computed (audit trail) but must not be
        # presented as a headline target — that's the pipeline's job.
        assert result.weighted_price is not None
        assert any("UNRELIABLE" in w for w in result.warnings)

    def test_reliable_false_market_divergence_tsla_2026_06_05(self):
        """The 2026-06-05 TSLA screenshot: DCF $11.80 (c=0.85) + Comps $25.54
        (c=0.55) → weighted $17.20, current $418.45.

        The two methods deviate only 36.8% from their $18.67 median — UNDER the
        50% median gate — so the ORIGINAL logic shipped 'SELL $17.20'. This test
        pins the model-vs-market gate: the weighted target is 95.9% below the
        market price, both methods corroborate at ~24x below the market, which
        prices option value (FSD/robotaxi/energy) a cash-flow DCF cannot capture
        (the Amazon-1999 failure). reliable must be False with a market-price
        banner. (The $11.80/$25.54 pair is also 2.16x apart, so the pairwise-ratio
        gate independently fires too — both signals are correct here; the assert
        below targets the market-price banner specifically.)"""
        methods = [
            ValuationMethod(
                name="DCF", low=10.0, mid=11.80, high=14.0, confidence=0.85, source="DCF"
            ),
            ValuationMethod(
                name="Comps", low=21.0, mid=25.54, high=30.0, confidence=0.55, source="Comps"
            ),
        ]
        result = synthesize_valuations(methods, current_price=418.45)
        # Method-vs-method spread alone does NOT trip the 50% gate (36.8% < 50%).
        # Only the new model-vs-market check makes this unreliable.
        assert result.weighted_price == pytest.approx(17.20, abs=0.05)
        assert result.reliable is False
        assert any("market price" in w and "UNRELIABLE" in w for w in result.warnings)

    def test_reliable_true_when_target_near_market(self):
        """A weighted target inside the [0.25x, 4x] band of the market price is
        NOT tripped by the model-vs-market gate. $245.50 vs $230 market = 1.07x."""
        methods = [
            ValuationMethod(name="DCF", low=210, mid=245, high=290, confidence=0.5, source="DCF"),
            ValuationMethod(
                name="EV/EBITDA", low=220, mid=250, high=280, confidence=0.3, source="Comps"
            ),
        ]
        result = synthesize_valuations(methods, current_price=230.0)
        assert result.reliable is True
        assert not any("market price" in w for w in result.warnings)

    def test_reliable_true_2x_undervaluation_still_publishes(self):
        """A genuine deep-value BUY worth 2x the market (ratio 2.0, inside the
        [0.25x, 4x] band) MUST still publish. The earlier abs(upside)>0.75 gate
        wrongly killed this (+100% upside), trusting an over-priced model far
        more readily than an under-priced one — the log-asymmetry the ratio gate
        fixes. Methods agree tightly so the spread gate stays clean too."""
        methods = [
            ValuationMethod(name="DCF", low=180, mid=200, high=220, confidence=0.6, source="DCF"),
            ValuationMethod(
                name="Comps", low=190, mid=205, high=225, confidence=0.4, source="Comps"
            ),
        ]
        # weighted = (200*0.6 + 205*0.4)/1.0 = 202 → 2.02x the $100 market
        result = synthesize_valuations(methods, current_price=100.0)
        assert result.weighted_price == pytest.approx(202.0, abs=0.5)
        assert result.reliable is True
        assert not any("market price" in w for w in result.warnings)

    def test_reliable_false_overvalued_model_above_4x(self):
        """Symmetry with the downside: a model worth > 4x the market is just as
        'out of calibration' as one worth < 1/4x. $450 weighted vs $100 market =
        4.5x → outside the [0.25x, 4x] band → reliable=False. Divergence
        MAGNITUDE matters, not direction."""
        methods = [
            ValuationMethod(name="DCF", low=420, mid=450, high=480, confidence=0.6, source="DCF"),
            ValuationMethod(
                name="Comps", low=430, mid=450, high=470, confidence=0.4, source="Comps"
            ),
        ]
        result = synthesize_valuations(methods, current_price=100.0)
        assert result.reliable is False
        assert any("market price" in w and "UNRELIABLE" in w for w in result.warnings)

    def test_single_method_is_reliable_by_default(self):
        """A lone method has no cross-check to fail — reliable stays True
        (the weighted_price=None path already withholds a target)."""
        methods = [
            ValuationMethod(name="DCF", low=200, mid=250, high=300, confidence=1.0, source="DCF")
        ]
        result = synthesize_valuations(methods, current_price=200.0)
        assert result.reliable is True


class TestVerdictFromUpside:
    """The Buy/Hold/Sell band classifier (±15% around fair value)."""

    def test_buy_at_and_above_threshold(self):
        assert verdict_from_upside(VERDICT_BUY_THRESHOLD) == "BUY"
        assert verdict_from_upside(0.30) == "BUY"

    def test_hold_inside_band(self):
        assert verdict_from_upside(0.0) == "HOLD"
        assert verdict_from_upside(VERDICT_BUY_THRESHOLD - 0.001) == "HOLD"
        assert verdict_from_upside(VERDICT_SELL_THRESHOLD + 0.001) == "HOLD"

    def test_sell_at_and_below_threshold(self):
        assert verdict_from_upside(VERDICT_SELL_THRESHOLD) == "SELL"
        assert verdict_from_upside(-0.40) == "SELL"


class TestResolveCanonicalThesis:
    """Pure unit tests for the headline target/verdict decision tree.

    These exercise the SAME data-health gates that
    test_equity_research_pipeline.py covers through the async ``_execute_thesis``
    shell (mock_agent + mock_deps), but directly on the pure operator — the
    payoff of extracting the decision out of the orchestration layer.
    """

    def test_non_synthesis_input_yields_empty_canonical(self):
        """Any non-ValuationSynthesis value (missing key, wrong type) → nothing
        published, no gate tripped."""
        for bad in (None, {"not": "a synthesis"}, "STRING"):
            canonical = resolve_canonical_thesis(bad, "AAPL")
            assert canonical.target is None
            assert canonical.verdict is None
            assert canonical.basis is None
            assert canonical.upside is None
            assert canonical.gate_failed is False

    def test_multi_method_converge_publishes_weighted_target(self):
        """≥2 corroborating methods → weighted target + a HOLD (upside 6.7% < 15%)."""
        methods = [
            ValuationMethod(name="DCF", low=210, mid=245, high=290, confidence=0.5, source="DCF"),
            ValuationMethod(
                name="EV/EBITDA", low=220, mid=250, high=280, confidence=0.3, source="Comps"
            ),
            ValuationMethod(name="P/E", low=210, mid=240, high=260, confidence=0.2, source="PE"),
        ]
        vs = synthesize_valuations(methods, current_price=230.0)
        canonical = resolve_canonical_thesis(vs, "AAPL")
        assert canonical.target == pytest.approx(245.5, abs=0.01)
        assert canonical.verdict == "HOLD"
        assert canonical.gate_failed is False
        assert canonical.basis is not None and "Method-weighted average of 3" in canonical.basis

    def test_multi_method_strong_upside_is_buy(self):
        """Same converge path, upside 22.8% ≥ 15% → BUY."""
        methods = [
            ValuationMethod(name="DCF", low=260, mid=280, high=300, confidence=0.5, source="DCF"),
            ValuationMethod(
                name="Comps", low=265, mid=285, high=305, confidence=0.5, source="Comps"
            ),
        ]
        vs = synthesize_valuations(methods, current_price=230.0)
        canonical = resolve_canonical_thesis(vs, "AAPL")
        assert canonical.target == pytest.approx(282.5, abs=0.01)
        assert canonical.verdict == "BUY"
        assert canonical.gate_failed is False

    def test_reliability_gate_withholds_target(self):
        """2.57x method disagreement (MSFT 2026-06-05) → REVIEW, target withheld."""
        methods = [
            ValuationMethod(
                name="dcf", low=151.72, mid=189.65, high=227.58, confidence=0.85, source="DCF"
            ),
            ValuationMethod(
                name="comps_pe", low=438.58, mid=487.31, high=536.04, confidence=0.55, source="PE"
            ),
        ]
        vs = synthesize_valuations(methods, current_price=425.0)
        canonical = resolve_canonical_thesis(vs, "MSFT")
        assert canonical.gate_failed is True
        assert canonical.verdict == "REVIEW"
        assert canonical.target is None
        assert canonical.basis is not None
        assert canonical.basis.startswith("DATA-HEALTH GATE: target withheld.")

    def test_single_method_in_band_publishes_its_mid(self):
        """Lone method whose mid sits inside the [0.25x, 4x] band → that mid is
        the canonical target (banks legitimately run comps-only)."""
        vs = synthesize_valuations(
            [ValuationMethod(name="DCF", low=270, mid=300, high=330, confidence=1.0, source="DCF")],
            current_price=240.0,
        )
        canonical = resolve_canonical_thesis(vs, "JPM")
        assert canonical.target == pytest.approx(300.0, abs=0.01)
        assert canonical.verdict == "BUY"  # upside 25% ≥ 15%
        assert canonical.gate_failed is False
        assert canonical.basis is not None and "Single valuation method" in canonical.basis

    def test_single_method_out_of_band_withholds_target(self):
        """Lone method 0.05x the market (the TSLA 'SELL $20.38' bug) → REVIEW,
        target withheld — a single uncorroborated method this far from the
        market must not stamp a headline."""
        vs = synthesize_valuations(
            [ValuationMethod(name="DCF", low=15, mid=20.38, high=26, confidence=1.0, source="DCF")],
            current_price=418.45,
        )
        canonical = resolve_canonical_thesis(vs, "TSLA")
        assert canonical.gate_failed is True
        assert canonical.verdict == "REVIEW"
        assert canonical.target is None
        assert canonical.basis is not None and "Only one valuation method" in canonical.basis

    def test_single_method_2_5x_market_withholds_target_mu(self):
        """The 2026-06-07 MU bug: DCF died (non-positive terminal-year FCF on a
        memory cyclical at peak), leaving a lone comps_pe at $2172 — 2.5x the
        $864 market — which shipped as a confident +151% BUY. A single
        uncorroborated method's only cross-check is the market; a 2.5x divergence
        is past the 2x corroboration limit (the same bar a 2-method disagreement
        must clear), so the gate now withholds the headline → REVIEW. This is the
        single-method analogue of the MSFT 2.57x method-vs-method gate."""
        vs = synthesize_valuations(
            [
                ValuationMethod(
                    name="comps_pe",
                    low=1954.85,
                    mid=2172.06,
                    high=2389.26,
                    confidence=0.8,
                    source="PE",
                )
            ],
            current_price=864.01,
        )
        canonical = resolve_canonical_thesis(vs, "MU")
        assert canonical.gate_failed is True
        assert canonical.verdict == "REVIEW"
        assert canonical.target is None
        assert canonical.basis is not None and "Only one valuation method" in canonical.basis
        # The withheld basis must cite the ratio against the market, not invent a target.
        assert "2.5x" in canonical.basis and "$864.01" in canonical.basis

    def test_single_method_just_under_2x_still_publishes(self):
        """Boundary lock for the single-method band: a lone method at 1.8x the
        market (under the 2x corroboration limit) is a real call, not an
        uncorroboratable outlier — it still publishes its mid. Banks legitimately
        run comps-only; sub-2x divergence must not be gated."""
        vs = synthesize_valuations(
            [
                ValuationMethod(
                    name="comps_pe", low=160, mid=180, high=200, confidence=1.0, source="PE"
                )
            ],
            current_price=100.0,
        )
        canonical = resolve_canonical_thesis(vs, "XYZ")
        assert canonical.gate_failed is False
        assert canonical.target == pytest.approx(180.0, abs=0.01)
        assert canonical.verdict == "BUY"
        assert canonical.basis is not None and "Single valuation method" in canonical.basis
