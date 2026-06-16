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
        Both methods flagged as outliers, each with a soft cross-method spread
        warning. The spread no longer appends a separate "UNRELIABLE" banner (the
        binary reliable gate is deleted); the graded call (anchored point + tier)
        is the confidence dial's job — see TestConfidenceDial / TestResolveCanonicalThesis.
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
        # Exactly the two soft per-method spread warnings — no UNRELIABLE banner.
        assert len(result.warnings) == 2
        assert any("DCF" in w and "$86.00" in w for w in result.warnings)
        assert any("Comps" in w and "$221.00" in w for w in result.warnings)
        assert not any("UNRELIABLE" in w for w in result.warnings)

    def test_outlier_flagged_dcf_only(self):
        """When only one method is the outlier, only that one appears in outlier_methods.

        Three methods: $100, $120, $200.
        median = $120
        $100 deviation = 16.7% < 30% → clean
        $120 deviation = 0%   < 30% → clean
        $200 deviation = 66.7% > 30% → soft outlier (disclosure only)
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
        # Just the one soft per-method spread warning — no UNRELIABLE banner.
        assert len(result.warnings) == 1
        assert any("LBO" in w and "deviates" in w for w in result.warnings)
        assert not any("UNRELIABLE" in w for w in result.warnings)

    def test_single_method_no_outlier_check(self):
        """Single-method synthesis skips outlier logic; outlier_methods/warnings empty."""
        methods = [
            ValuationMethod(name="DCF", low=200, mid=250, high=300, confidence=1.0, source="DCF")
        ]
        result = synthesize_valuations(methods, current_price=200.0)
        assert result.outlier_methods == []
        assert result.warnings == []

    def test_divergent_pair_anchors_msft_2026_06_05(self):
        """Regression for the 2026-06-05 MSFT bug: DCF $189.65 (c=0.85) vs
        comps_pe $487.31 (c=0.55), 2.57x apart. The deleted binary `reliable`
        gate withheld the whole call; the dial now keeps the call and range, but
        withholds the point because the methods do not corroborate (>2x span).
        The comparability anchor is still comps (for explanation), never the
        phantom $306.59 blended midpoint."""
        methods = [
            ValuationMethod(
                name="dcf", low=151.72, mid=189.65, high=227.58, confidence=0.85, source="DCF"
            ),
            ValuationMethod(
                name="comps_pe", low=438.58, mid=487.31, high=536.04, confidence=0.55, source="PE"
            ),
        ]
        result = synthesize_valuations(methods, current_price=425.0)
        # weighted_price is still computed for the audit trail, but the headline
        # point anchors comps — never the meaningless $306.59 blend.
        assert result.weighted_price == pytest.approx(306.59, abs=0.05)
        assert result.anchor_method == "comps_pe"
        assert result.confidence == "medium"
        assert result.valuation_withheld is True
        assert result.target_low == pytest.approx(189.65, abs=0.01)
        assert result.target_high == pytest.approx(487.31, abs=0.01)

    def test_corroborating_pair_within_2x_blends_high_confidence(self):
        """Two methods within the 1.5x corroboration band blend into a high-tier
        call (no anchor). DCF $200 vs Comps $230 = 1.15x ratio, target $215 vs
        $300 market is in-band → not withheld; soft 30% outlier flags do not
        fire (both within 30% of the $215 median)."""
        methods = [
            ValuationMethod(name="DCF", low=180, mid=200, high=220, confidence=0.5, source="DCF"),
            ValuationMethod(
                name="Comps", low=210, mid=230, high=250, confidence=0.5, source="Comps"
            ),
        ]
        result = synthesize_valuations(methods, current_price=300.0)
        assert result.confidence == "high"
        assert result.anchor_method is None
        assert result.valuation_withheld is False
        assert result.warnings == []

    def test_methods_agree_far_below_market_withholds_point_tsla(self):
        """The 2026-05-28 / 2026-06-05 TSLA option-value regime: DCF + Comps agree
        with each other but all sit ~24x below the $418 market. The deleted gate
        flagged reliable=False; the dial now withholds the POINT (very_low) while
        the directional verdict still ships — never a confident SELL @ $11.25."""
        methods = [
            ValuationMethod(
                name="DCF", low=10.0, mid=11.80, high=14.0, confidence=0.85, source="DCF"
            ),
            ValuationMethod(
                name="Comps", low=21.0, mid=25.54, high=30.0, confidence=0.55, source="Comps"
            ),
        ]
        result = synthesize_valuations(methods, current_price=418.45)
        # weighted_price still computed (audit trail) but the POINT is withheld.
        # The method span survives as the disclosed range even when the point is
        # withheld (the analyst still sees what the methods said).
        assert result.weighted_price == pytest.approx(17.20, abs=0.05)
        assert result.confidence == "very_low"
        assert result.valuation_withheld is True
        canonical = resolve_canonical_thesis(result, "TSLA")
        assert canonical.target is None  # the published POINT is withheld
        assert canonical.verdict in ("BUY", "HOLD", "SELL")

    def test_target_near_market_keeps_point_high_confidence(self):
        """A blended target inside the [0.25x, 4x] band of the market is NOT
        capped by the out-of-calibration rule. $245.50 vs $230 market = 1.07x →
        high tier, point kept."""
        methods = [
            ValuationMethod(name="DCF", low=210, mid=245, high=290, confidence=0.5, source="DCF"),
            ValuationMethod(
                name="EV/EBITDA", low=220, mid=250, high=280, confidence=0.3, source="Comps"
            ),
        ]
        result = synthesize_valuations(methods, current_price=230.0)
        assert result.confidence == "high"
        assert result.valuation_withheld is False

    def test_2x_undervaluation_in_band_still_publishes(self):
        """A genuine deep-value BUY worth ~2x the market (ratio 2.0, inside the
        [0.25x, 4x] band) MUST still publish its point. Methods agree tightly
        (1.025x) → high tier, point kept."""
        methods = [
            ValuationMethod(name="DCF", low=180, mid=200, high=220, confidence=0.6, source="DCF"),
            ValuationMethod(
                name="Comps", low=190, mid=205, high=225, confidence=0.4, source="Comps"
            ),
        ]
        result = synthesize_valuations(methods, current_price=100.0)
        assert result.weighted_price == pytest.approx(202.0, abs=0.5)
        assert result.confidence == "high"
        assert result.valuation_withheld is False

    def test_overvalued_model_above_4x_caps_confidence(self):
        """Symmetry with the downside: a model worth > 4x the market is out of
        calibration. $450 vs $100 market = 4.5x → out-of-band but not extreme
        (< 8x) → confidence capped to low, point kept (range spans the methods)."""
        methods = [
            ValuationMethod(name="DCF", low=420, mid=450, high=480, confidence=0.6, source="DCF"),
            ValuationMethod(
                name="Comps", low=430, mid=450, high=470, confidence=0.4, source="Comps"
            ),
        ]
        result = synthesize_valuations(methods, current_price=100.0)
        assert result.confidence == "low"
        assert any("calibration band" in w for w in [result.degradation_note or ""])

    def test_band_cap_note_discloses_breach_but_never_claims_option_value(self):
        """The out-of-calibration cap GRADES the gap's SIZE (confidence ↓) — it must
        NOT classify its NATURE. 'Option value' is the reverse-DCF's verdict
        (classify_market_implied_nature), not this band's: the [0.25x, 4x] band fires
        for MU at 0.17x while MU's price is REACHABLE at ~37% growth, so a hardcoded
        'option value' here contradicted the reverse-DCF read in shipped MU output
        (price_target_basis vs valuation_overview, 2026-06-16). Lock both sides of the
        band: the breach IS disclosed, its nature is never asserted."""
        for mid, price in ((188.0, 1088.0), (450.0, 100.0)):  # 0.17x (MU) and 4.5x
            methods = [
                ValuationMethod(
                    name="DCF", low=mid * 0.9, mid=mid, high=mid * 1.1, confidence=0.6, source="DCF"
                ),
                ValuationMethod(
                    name="Comps", low=mid * 0.92, mid=mid, high=mid * 1.08, confidence=0.4, source="Comps"
                ),
            ]
            note = (synthesize_valuations(methods, current_price=price).degradation_note or "").lower()
            assert "calibration band" in note  # the size-of-gap breach IS disclosed
            assert "option value" not in note  # …but its NATURE is never claimed here
            assert "optionality" not in note


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
        midpoint. Verdict directional, NOT REVIEW, but the point is withheld
        because >2x method span means no single publishable headline target."""
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
        # needs +40%, so HOLD. The point is withheld; the range still discloses
        # both methods instead of publishing either endpoint as false precision.
        assert vs.anchor_method == "comps_pe"
        assert canonical.target is None
        assert canonical.verdict == "HOLD"
        assert canonical.valuation_withheld is True
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
        # not extreme → low; point withheld because methods do not corroborate, and
        # range spans both methods.
        vs = synthesize_valuations(
            [self._m("dcf", 188), self._m("comps_pb", 1332)], 982.0, cyclical=True
        )
        assert vs.confidence == "low"
        assert vs.anchor_method == "dcf"
        assert vs.valuation_withheld is True
        assert vs.target_low == pytest.approx(188) and vs.target_high == pytest.approx(1332)
        anchor = next(m for m in vs.methods if m.name == vs.anchor_method)
        assert abs(anchor.mid - (188 + 1332) / 2) > 100  # decisively not the midpoint

    def test_noncyclical_divergence_anchors_comps(self):
        # AAPL: dcf $104 vs comps_pe $303 (2.9x), rich peers → anchor comps for
        # the explanation, but withhold the point because span >2x.
        vs = synthesize_valuations(
            [self._m("dcf", 104), self._m("comps_pe", 303)], 291.0, cyclical=False
        )
        assert vs.confidence == "medium"
        assert vs.anchor_method == "comps_pe"
        assert vs.valuation_withheld is True

    def test_run_5ae06f55_mu_wide_range_spanning_market_is_hold_without_point(self):
        """Regression for run_5ae06f55b2ce: DCF $188, EV/EBITDA $803, comps P/B
        $1415, current $1088. A low-confidence range that spans market must not
        publish the DCF endpoint as a naked SELL target."""
        vs = synthesize_valuations(
            [
                self._m("dcf", 188.12, 0.85),
                self._m("ev_ebitda", 803.15, 0.72),
                self._m("comps_pb", 1414.52, 0.60),
            ],
            1087.99,
            cyclical=True,
        )
        canonical = resolve_canonical_thesis(vs, "MU")
        assert vs.confidence == "low"
        assert vs.anchor_method == "dcf"
        assert vs.valuation_withheld is True
        assert canonical.target is None
        assert canonical.verdict == "HOLD"
        assert canonical.upside == pytest.approx(0.0)
        assert canonical.basis is not None
        assert "range spans the current market price" in canonical.basis
        assert vs.target_low == pytest.approx(188.12)
        assert vs.target_high == pytest.approx(1414.52)

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

    def test_single_method_off_market_withholds_point_but_keeps_band(self):
        # RIVN: single dcf $6 vs $17 (0.36x, out of [0.5x,2x] single band) → very_low
        # + POINT withheld (no false-precise headline stamped on a lone far-from-market
        # method). The BAND still ships (contract ②: 单方法→给区间、标低置信、不撤回;
        # 交付物永远 100% 完整字段, never a None range that blanks the UI) — and this
        # mirrors the multi-method extreme-withhold path, which also emits lo/hi while
        # withholding the point. The band is the lone method's mid ± single-method frac.
        vs = synthesize_valuations([self._m("dcf", 6)], 17.0, cyclical=False)
        assert vs.confidence == "very_low"
        assert vs.valuation_withheld is True
        assert vs.target_low == pytest.approx(6 * (1 - 0.25))
        assert vs.target_high == pytest.approx(6 * (1 + 0.25))
        # The POINT is still withheld even though the band is present.
        assert resolve_canonical_thesis(vs, "RIVN").target is None

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

    def test_dial_always_emits_a_band_never_blanks_the_range(self):
        """机械闸门(契约② 单方法→给区间不撤回 + 新规矩 交付物永远 100% 完整字段):
        _confidence_dial 对任何非空方法集都必须给出 target_low/high — 撤的只是 POINT,
        区间永不为 None。这样 UI <TargetRange> 永远有带可画、绝不渲染空白(masked-or-not
        the deliverable's range field is complete). Covers every dial branch incl. the
        two withhold paths (single off-market + multi extreme), which must be symmetric."""
        cases = [
            ([self._m("dcf", 6)], 17.0, False),  # single off-market → POINT withheld
            ([self._m("dcf", 300)], 240.0, False),  # single in-band
            ([self._m("dcf", 33), self._m("comps_pe", 24)], 406.0, False),  # multi extreme withheld
            ([self._m("dcf", 100), self._m("comps_pe", 120)], 110.0, False),  # multi corroborate
            ([self._m("dcf", 188), self._m("comps_pb", 1332)], 982.0, True),  # cyclical divergence
        ]
        for methods, price, cyc in cases:
            vs = synthesize_valuations(methods, price, cyclical=cyc)
            names = [m.name for m in methods]
            assert (
                vs.target_low is not None and vs.target_high is not None
            ), f"dial blanked the range for {names} @ {price} (withheld={vs.valuation_withheld})"
            assert vs.target_high >= vs.target_low
