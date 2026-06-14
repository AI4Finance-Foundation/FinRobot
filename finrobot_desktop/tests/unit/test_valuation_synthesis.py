"""Tests for valuation synthesis with confidence-weighted averaging."""

import pytest
from finrobot.engine.models.financial import ValuationMethod
from finrobot.engine.compute.operators.valuation_synthesis import (
    _VERDICT_BANDS,
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

    def test_market_divergence_warning_cites_real_spread_not_vague_corroboration(self):
        """The market-divergence banner must CITE the cross-method spread, not
        flatly assert 'the methods corroborate each other'. 2026-06-09 TSLA: DCF
        $27.83 + comps $46.78 (1.68x apart, within the 2x bar) at $408.95 market.
        They agree within the limit, so the banner should say so AND show the
        $27.83–$46.78 span — the old text claimed corroboration with no number
        even though the two ranges did not overlap."""
        methods = [
            ValuationMethod(
                name="dcf", low=22.27, mid=27.83, high=33.40, confidence=0.85, source="DCF"
            ),
            ValuationMethod(
                name="comps_pe", low=42.10, mid=46.78, high=51.46, confidence=0.80, source="Comps"
            ),
        ]
        result = synthesize_valuations(methods, current_price=408.95)
        assert result.reliable is False
        banner = next(w for w in result.warnings if "market price" in w and "UNRELIABLE" in w)
        # Cites the actual spread (low–high and the ratio), not a bare claim.
        assert "27.83" in banner and "46.78" in banner
        assert "1.7x" in banner  # hi/lo formatted at 2 sig figs
        assert "agree with each other" in banner

    def test_market_divergence_does_not_claim_agreement_when_methods_disagree(self):
        """When the methods are >2x apart AND far from market, the banner must NOT
        say they 'agree' — it must state they do not even agree with each other."""
        methods = [
            ValuationMethod(name="dcf", low=8, mid=10.0, high=12, confidence=0.85, source="DCF"),
            ValuationMethod(
                name="comps_pe", low=28, mid=30.0, high=33, confidence=0.80, source="Comps"
            ),
        ]  # 3x apart
        result = synthesize_valuations(methods, current_price=500.0)
        banner = next(w for w in result.warnings if "market price" in w and "UNRELIABLE" in w)
        assert "do not even agree" in banner
        assert "agree with each other" not in banner.replace("do not even agree", "")

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
    """The Buy/Hold/Sell classifier: confidence-tiered, asymmetric bands.

    Expected boundaries are DERIVED from ``_VERDICT_BANDS`` (the named-constant
    table), not hand-invented: BUY when upside ≥ buy_discount, SELL when upside ≤
    −sell_premium, else HOLD. Within each tier the sell premium exceeds the buy
    discount (asymmetric), and both widen as confidence drops.
    """

    @pytest.mark.parametrize("tier", list(_VERDICT_BANDS))
    def test_buy_at_and_above_tier_discount(self, tier):
        buy, _sell = _VERDICT_BANDS[tier]
        assert verdict_from_upside(buy, tier) == "BUY"
        assert verdict_from_upside(buy + 0.10, tier) == "BUY"

    @pytest.mark.parametrize("tier", list(_VERDICT_BANDS))
    def test_sell_at_and_below_tier_premium(self, tier):
        _buy, sell = _VERDICT_BANDS[tier]
        assert verdict_from_upside(-sell, tier) == "SELL"
        assert verdict_from_upside(-sell - 0.10, tier) == "SELL"

    @pytest.mark.parametrize("tier", list(_VERDICT_BANDS))
    def test_hold_strictly_inside_band(self, tier):
        buy, sell = _VERDICT_BANDS[tier]
        assert verdict_from_upside(0.0, tier) == "HOLD"
        assert verdict_from_upside(buy - 0.001, tier) == "HOLD"
        assert verdict_from_upside(-sell + 0.001, tier) == "HOLD"

    def test_bands_are_asymmetric_sell_premium_exceeds_buy_discount(self):
        # Morningstar-style: overvaluation must be more pronounced than
        # undervaluation before a call fires, in EVERY tier.
        for buy, sell in _VERDICT_BANDS.values():
            assert sell > buy

    def test_bands_widen_as_confidence_drops(self):
        # The less trustworthy the anchor, the further price must sit from fair
        # value before a directional call — both sides widen monotonically.
        order = ["high", "medium", "low", "very_low"]
        buys = [_VERDICT_BANDS[t][0] for t in order]
        sells = [_VERDICT_BANDS[t][1] for t in order]
        assert buys == sorted(buys)
        assert sells == sorted(sells)

    def test_low_confidence_holds_where_high_confidence_calls(self):
        # +22% upside: a BUY at high confidence (≥ +20%), only a HOLD at low (< +40%).
        assert verdict_from_upside(0.22, "high") == "BUY"
        assert verdict_from_upside(0.22, "low") == "HOLD"
        # −30% downside: a SELL at high confidence (≤ −25%), only HOLD at low (> −55%).
        assert verdict_from_upside(-0.30, "high") == "SELL"
        assert verdict_from_upside(-0.30, "low") == "HOLD"

    def test_default_confidence_is_high(self):
        assert verdict_from_upside(0.20) == verdict_from_upside(0.20, "high")


class TestResolveCanonicalThesis:
    """Pure unit tests for the headline verdict (+ maybe target) decision.

    The verdict is ALWAYS directional (BUY/HOLD/SELL — the REVIEW state is
    deleted); uncertainty is expressed by the confidence tier (widening the
    asymmetric verdict bands) and by withholding the POINT (valuation_withheld)
    while the verdict still ships. These exercise the pure operator directly;
    test_equity_research_pipeline.py covers the same paths through the async
    ``_execute_thesis`` shell.
    """

    def test_non_synthesis_input_yields_empty_canonical(self):
        """Any non-ValuationSynthesis value (missing key, wrong type) → nothing
        published, not withheld (there is simply no synthesis)."""
        for bad in (None, {"not": "a synthesis"}, "STRING"):
            canonical = resolve_canonical_thesis(bad, "AAPL")
            assert canonical.target is None
            assert canonical.verdict is None
            assert canonical.basis is None
            assert canonical.upside is None
            assert canonical.valuation_withheld is False
            assert canonical.confidence is None

    def test_never_returns_review_across_the_basket(self):
        """Hard invariant: resolve_canonical_thesis must NEVER emit 'REVIEW' for
        any synthesis — including the cases that historically tripped the gate
        (2-method 2.57x disagreement, single-method 2.5x off-market, methods that
        agree far below market). Every one yields a directional BUY/HOLD/SELL."""
        cases = [
            # MSFT 2026-06-05: DCF $189.65 vs comps_pe $487.31 (2.57x apart).
            ([("dcf", 189.65, 0.85), ("comps_pe", 487.31, 0.55)], 425.0, False),
            # TSLA: methods agree far below market (option-value regime).
            ([("dcf", 11.80, 0.85), ("comps_pe", 25.54, 0.55)], 418.45, False),
            # MU 2026-06-07: lone comps_pe $2172 = 2.5x the $864 market.
            ([("comps_pe", 2172.06, 0.8)], 864.01, False),
            # RIVN: lone DCF far below market.
            ([("dcf", 6.0, 1.0)], 17.0, False),
            # Clean converging pair.
            ([("dcf", 245, 0.5), ("comps_pe", 250, 0.5)], 230.0, False),
        ]
        for raw, price, cyc in cases:
            methods = [
                ValuationMethod(name=n, low=m * 0.9, mid=m, high=m * 1.1, confidence=c, source=n)
                for n, m, c in raw
            ]
            vs = synthesize_valuations(methods, current_price=price, cyclical=cyc)
            canonical = resolve_canonical_thesis(vs, "X")
            assert canonical.verdict in (
                "BUY",
                "HOLD",
                "SELL",
            ), f"non-directional verdict {canonical.verdict!r} for {raw}"
            assert "REVIEW" not in (canonical.basis or "")

    def test_multi_method_converge_publishes_weighted_target_hold(self):
        """≥2 corroborating methods (span 1.04x ≤ 1.5x → high tier, blended) →
        weighted target + HOLD: upside +6.7% is below the high-tier BUY band
        (+20%) and above the SELL band (−25%)."""
        methods = [
            ValuationMethod(name="DCF", low=210, mid=245, high=290, confidence=0.5, source="DCF"),
            ValuationMethod(
                name="EV/EBITDA", low=220, mid=250, high=280, confidence=0.3, source="Comps"
            ),
            ValuationMethod(name="P/E", low=210, mid=240, high=260, confidence=0.2, source="PE"),
        ]
        vs = synthesize_valuations(methods, current_price=230.0)
        assert vs.confidence == "high"
        canonical = resolve_canonical_thesis(vs, "AAPL")
        # Blended weighted price (anchor None) → round(weighted_price).
        assert canonical.target == pytest.approx(245.5, abs=0.01)
        assert canonical.verdict == "HOLD"  # +6.7% < high-tier BUY +20%
        assert canonical.valuation_withheld is False
        assert canonical.confidence == "high"
        assert canonical.basis is not None and "method-weighted blend" in canonical.basis

    def test_multi_method_strong_upside_is_buy(self):
        """Converging pair (span 1.018x → high tier), upside +22.8% ≥ high-tier
        BUY band (+20%) → BUY."""
        methods = [
            ValuationMethod(name="DCF", low=260, mid=280, high=300, confidence=0.5, source="DCF"),
            ValuationMethod(
                name="Comps", low=265, mid=285, high=305, confidence=0.5, source="Comps"
            ),
        ]
        vs = synthesize_valuations(methods, current_price=230.0)
        assert vs.confidence == "high"
        canonical = resolve_canonical_thesis(vs, "AAPL")
        assert canonical.target == pytest.approx(282.5, abs=0.01)
        assert canonical.verdict == "BUY"  # +22.8% ≥ +20%
        assert canonical.valuation_withheld is False

    def test_divergent_pair_anchors_not_blends(self):
        """2.57x method disagreement (MSFT 2026-06-05): the dial anchors comps
        (rich-peer rule, non-cyclical) instead of blending into a phantom
        midpoint. Verdict directional, NOT REVIEW. Point at the anchor (in-band,
        not withheld). medium confidence (1.5x < span 2.57x ≤ 3x mild band)."""
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
        assert canonical.verdict in ("BUY", "HOLD", "SELL")
        # comps_pe $487.31 anchored (rich-peer rule), upside +14.7% — low-tier BUY
        # needs +40%, so HOLD. The point sits AT the anchor, not a blended midpoint.
        assert vs.anchor_method == "comps_pe"
        assert canonical.target == pytest.approx(487.31, abs=0.01)
        assert canonical.verdict == "HOLD"
        assert canonical.valuation_withheld is False
        assert canonical.confidence == "medium"

    def test_methods_agree_far_below_market_withholds_point_keeps_direction(self):
        """TSLA option-value regime: DCF $11.80 + comps $25.54 agree (2.16x) but
        all sit ~0.04x the market → extreme out-of-band → POINT withheld while the
        directional verdict still ships. NOT 'REVIEW', NOT a naked target."""
        methods = [
            ValuationMethod(
                name="dcf", low=10.0, mid=11.80, high=14.0, confidence=0.85, source="DCF"
            ),
            ValuationMethod(
                name="comps_pe", low=21.0, mid=25.54, high=30.0, confidence=0.55, source="Comps"
            ),
        ]
        vs = synthesize_valuations(methods, current_price=418.45)
        canonical = resolve_canonical_thesis(vs, "TSLA")
        assert canonical.valuation_withheld is True
        assert canonical.target is None
        assert canonical.verdict in ("BUY", "HOLD", "SELL")  # directional, not REVIEW
        assert canonical.confidence == "very_low"
        assert canonical.basis is not None and "WITHHELD" in canonical.basis

    def test_single_method_in_band_publishes_its_mid(self):
        """Lone method inside the single-method calibration band → that mid is the
        canonical target (banks legitimately run comps-only). medium tier; upside
        +25% is below the medium-tier BUY band (+30%) → HOLD."""
        vs = synthesize_valuations(
            [ValuationMethod(name="DCF", low=270, mid=300, high=330, confidence=1.0, source="DCF")],
            current_price=240.0,
        )
        canonical = resolve_canonical_thesis(vs, "JPM")
        assert canonical.target == pytest.approx(300.0, abs=0.01)
        assert canonical.confidence == "medium"
        assert canonical.verdict == "HOLD"  # +25% < medium-tier BUY +30%
        assert canonical.valuation_withheld is False

    def test_single_method_out_of_band_withholds_point(self):
        """Lone method 0.05x the market (the TSLA 'SELL $20.38' bug) → POINT
        withheld (very_low) — a single uncorroborated method this far from the
        market must not stamp a headline number — but the verdict is directional."""
        vs = synthesize_valuations(
            [ValuationMethod(name="DCF", low=15, mid=20.38, high=26, confidence=1.0, source="DCF")],
            current_price=418.45,
        )
        canonical = resolve_canonical_thesis(vs, "TSLA")
        assert canonical.valuation_withheld is True
        assert canonical.target is None
        assert canonical.verdict in ("BUY", "HOLD", "SELL")
        assert canonical.confidence == "very_low"

    def test_single_method_2_5x_market_withholds_point_mu(self):
        """The 2026-06-07 MU bug: a lone comps_pe at $2172 = 2.5x the $864 market.
        The dial withholds the POINT (very_low) so no phantom +151% BUY ships, but
        a directional verdict still comes out (BUY from the +151% read)."""
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
        assert canonical.valuation_withheld is True
        assert canonical.target is None
        assert canonical.verdict in ("BUY", "HOLD", "SELL")
        assert canonical.confidence == "very_low"
        assert canonical.basis is not None and "WITHHELD" in canonical.basis

    def test_single_method_just_under_2x_still_publishes(self):
        """A lone method at 1.8x the market (under the 2x single-method band) is a
        real call — it publishes its mid. medium tier; upside +80% ≥ medium-tier
        BUY band (+30%) → BUY."""
        vs = synthesize_valuations(
            [
                ValuationMethod(
                    name="comps_pe", low=160, mid=180, high=200, confidence=1.0, source="PE"
                )
            ],
            current_price=100.0,
        )
        canonical = resolve_canonical_thesis(vs, "XYZ")
        assert canonical.valuation_withheld is False
        assert canonical.target == pytest.approx(180.0, abs=0.01)
        assert canonical.confidence == "medium"
        assert canonical.verdict == "BUY"


class TestConfidenceDial:
    """The graded-call dial (REVIEW deleted): synthesize_valuations always yields a
    confidence tier + a target band, and withholds the POINT (never the call) only
    when the sole available number would be fabricated. Cases mirror the live basket
    (MU/AAPL/KO/NVDA/TSLA/RIVN/F) — the empirical calibration regression guard."""

    @staticmethod
    def _m(name: str, mid: float, conf: float = 0.7) -> ValuationMethod:
        return ValuationMethod(
            name=name, low=mid * 0.9, mid=mid, high=mid * 1.1, confidence=conf, source=name
        )

    def test_cyclical_divergence_anchors_dcf_not_midpoint(self):
        # MU: dcf $188 vs comps_pb $1332 (7x), cyclical → anchor the cycle-stable DCF,
        # NEVER the ~$760 midpoint no method produced. 0.19x market → out-of-band but
        # not extreme → low, point kept; range spans both methods.
        vs = synthesize_valuations(
            [self._m("dcf", 188), self._m("comps_pb", 1332)], 982.0, cyclical=True
        )
        assert vs.confidence == "low"
        assert vs.anchor_method == "dcf"
        assert vs.valuation_withheld is False
        assert vs.target_low == pytest.approx(188) and vs.target_high == pytest.approx(1332)
        anchor = next(m for m in vs.methods if m.name == vs.anchor_method)
        assert abs(anchor.mid - (188 + 1332) / 2) > 100  # decisively not the midpoint

    def test_noncyclical_divergence_anchors_comps(self):
        # AAPL: dcf $104 vs comps_pe $303 (2.9x), rich peers → anchor comps.
        vs = synthesize_valuations(
            [self._m("dcf", 104), self._m("comps_pe", 303)], 291.0, cyclical=False
        )
        assert vs.confidence == "medium"
        assert vs.anchor_method == "comps_pe"
        assert vs.valuation_withheld is False

    def test_market_distance_within_band_does_not_lower_confidence(self):
        # KO: dcf $27 + comps_pe $49, both below $83 market but within [0.25x,4x] →
        # NOT capped. Confidence reflects method agreement, not distance-to-market.
        vs = synthesize_valuations(
            [self._m("dcf", 27), self._m("comps_pe", 49)], 83.0, cyclical=False
        )
        assert vs.confidence == "medium"
        assert vs.valuation_withheld is False

    def test_methods_agree_far_below_market_withholds_point_keeps_direction(self):
        # TSLA: dcf $33 + comps_pe $24 agree (1.4x) but ~0.07x market (extreme
        # out-of-band, option-value regime) → very_low + POINT withheld; the verdict
        # still ships from the market-implied read. NOT a naked high-conf -93% SELL.
        vs = synthesize_valuations(
            [self._m("dcf", 33), self._m("comps_pe", 24)], 406.0, cyclical=False
        )
        assert vs.confidence == "very_low"
        assert vs.valuation_withheld is True

    def test_single_method_off_market_withholds_point(self):
        # RIVN: single dcf $6 vs $17 (0.36x, out of [0.5x,2x] single band) → very_low
        # + withheld (the only number would be the market price in costume).
        vs = synthesize_valuations([self._m("dcf", 6)], 17.0, cyclical=False)
        assert vs.confidence == "very_low"
        assert vs.valuation_withheld is True
        assert vs.target_low is None

    def test_single_method_in_band_medium_with_widened_range(self):
        # F: single comps_pe $12 vs $15 (0.8x, in band) → medium, point kept, band widened.
        vs = synthesize_valuations([self._m("comps_pe", 12)], 15.0, cyclical=False)
        assert vs.confidence == "medium"
        assert vs.valuation_withheld is False
        assert vs.target_low is not None and vs.target_high is not None

    def test_methods_corroborate_blend_high_confidence(self):
        # Two methods within 1.5x and in-band → high confidence, blended (anchor None).
        vs = synthesize_valuations(
            [self._m("dcf", 100), self._m("comps_pe", 120)], 110.0, cyclical=False
        )
        assert vs.confidence == "high"
        assert vs.anchor_method is None
        assert vs.valuation_withheld is False
