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
        # Warnings carry the human method LABEL (_method_label), never a raw id:
        # "DCF"/"Comps" are not canonical keys → upper-cased fallback.
        assert any("DCF" in w and "$86.00" in w for w in result.warnings)
        assert any("COMPS" in w and "$221.00" in w for w in result.warnings)
        assert not any("UNRELIABLE" in w for w in result.warnings)

    def test_spread_warning_uses_method_label_not_snake_case(self):
        """The reader-facing spread warning must humanise the method id: a
        canonical key like ``ev_ebitda`` renders "EV/EBITDA", never the raw
        snake_case token (it surfaces in the report's compute-warnings list)."""
        methods = [
            ValuationMethod(name="dcf", low=70, mid=86, high=100, confidence=0.5, source="DCF"),
            ValuationMethod(
                name="ev_ebitda", low=190, mid=221, high=260, confidence=0.5, source="Comps"
            ),
        ]
        result = synthesize_valuations(methods, current_price=180.0)
        assert any("EV/EBITDA" in w for w in result.warnings)
        assert not any("ev_ebitda" in w for w in result.warnings)

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
        assert any("LBO" in w and "diverges" in w for w in result.warnings)
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

    def test_lone_comps_outlier_reanchors_to_dcf_ko_2026_06_22(self):
        """When the comps anchor is a LONE cross-method outlier — the other methods
        corroborate without it — the dial re-anchors to the corroborated DCF, never the
        outlier, so the headline isn't a biased −33%. KO 2026-06-22: comps_pe $53.51
        (peer-median P/E ignores KO's quality premium — verified low vs external analyst
        target $85 / KO fwd P/E 24.7 / our DCF $76) is the lone low end; DCF $76.32 +
        EV/EBITDA $89.67 corroborate (1.17x), so the target anchors DCF $76.32 (−3.9%),
        not comps_pe $53.51 (−32.6%). upside_downside tracks the published DCF anchor,
        never the blend ($72.68 / −8.5%) or the outlier; the full range still bounds the band."""
        methods = [
            ValuationMethod(
                name="dcf", low=61.1, mid=76.32, high=91.6, confidence=0.85, source="D"
            ),
            ValuationMethod(
                name="comps_pe", low=48.2, mid=53.51, high=58.9, confidence=0.80, source="PE"
            ),
            ValuationMethod(
                name="ev_ebitda", low=82.3, mid=89.67, high=97.1, confidence=0.72, source="EV"
            ),
        ]
        result = synthesize_valuations(methods, current_price=79.39)
        assert result.anchor_method == "dcf"  # re-anchored away from the lone comps_pe outlier
        # the FULL method range still bounds the band (the outlier stays visible)
        assert result.target_low == pytest.approx(53.51, abs=0.01)
        assert result.target_high == pytest.approx(89.67, abs=0.01)
        # upside tracks the DCF anchor (−3.9%), NOT the comps_pe outlier (−32.6%) or blend (−8.5%)
        assert result.upside_downside == pytest.approx((76.32 - 79.39) / 79.39, abs=1e-6)
        canonical = resolve_canonical_thesis(result, "KO")
        assert canonical.target == pytest.approx(76.32, abs=0.01)
        assert canonical.verdict == "HOLD"

    def test_comps_anchor_kept_when_not_lone_outlier(self):
        """The re-anchor fires ONLY when comps is the LONE extreme. When comps sits with
        the pack (not the min/max), it stays the comparability anchor — the peer-rich
        convention is unchanged for the normal divergent case (here DCF is the low
        outlier, comps_pe is mid → comps_pe kept)."""
        methods = [
            ValuationMethod(name="dcf", low=40, mid=50.0, high=60, confidence=0.85, source="D"),
            ValuationMethod(
                name="comps_pe", low=70, mid=80.0, high=90, confidence=0.80, source="PE"
            ),
            ValuationMethod(
                name="ev_ebitda", low=75, mid=85.0, high=95, confidence=0.72, source="EV"
            ),
        ]
        result = synthesize_valuations(methods, current_price=80.0)
        assert result.anchor_method == "comps_pe"

    def test_cyclical_keeps_dcf_anchor_even_if_comps_corroborate(self):
        """Cyclicals are EXEMPT from the lone-outlier re-anchor: the DCF/PB anchor is
        intentional even as an outlier (peak-EPS comps are the unreliable side). A
        cyclical whose comps corroborate away from DCF must still anchor by its cyclical
        rule, not flip to comps."""
        methods = [
            ValuationMethod(name="dcf", low=15, mid=18.9, high=23, confidence=0.85, source="D"),
            ValuationMethod(
                name="comps_pb", low=40, mid=47.0, high=54, confidence=0.6, source="PB"
            ),
            ValuationMethod(
                name="ev_ebitda", low=41, mid=48.0, high=55, confidence=0.72, source="EV"
            ),
        ]
        result = synthesize_valuations(methods, current_price=50.0, cyclical=True)
        assert (
            result.anchor_method == "dcf"
        )  # cyclical → DCF anchor regardless of comps corroboration

    def test_bimodal_lone_outlier_within_span_not_blended_aapl_2026_06_29(self):
        """AAPL v9: comps_pe $182.97 + dcf $189.27 cluster at ~$185 while ev_ebitda
        $266.01 sits +41% off the $189.27 median. max/min span = 266/183 = 1.45 ≤ 1.5,
        so the two-POINT span wrongly read the set as CORROBORATED and blended all three
        into a false-precise HIGH-confidence $210.46 — the §2 bug (the median-deviation
        gate flagged ev_ebitda an outlier while the headline priced it in). The bimodal
        guard now routes it to divergent: confidence MEDIUM (not high), anchored to the
        corroborated DCF cash-flow value $189.27 (not the blend), point SHOWN, the full
        range still bounds the band, ev_ebitda still flagged. Verdict stays HOLD —
        verdict-INVARIANT (−31.2% vs the medium −35% sell band). GOOGL at span 1.56 (same
        shape, one tick over the 1.5x cliff) already routes divergent; this makes the two
        consistent. NON-cyclical only (the cyclical DCF anchor is owned above)."""
        methods = [
            ValuationMethod(
                name="dcf", low=151.42, mid=189.27, high=227.13, confidence=0.85, source="D"
            ),
            ValuationMethod(
                name="comps_pe", low=164.67, mid=182.97, high=201.27, confidence=0.80, source="PE"
            ),
            ValuationMethod(
                name="ev_ebitda", low=239.4, mid=266.01, high=292.6, confidence=0.72, source="EV"
            ),
        ]
        result = synthesize_valuations(methods, current_price=275.15)
        # The core fix: NOT corroborated-high, NOT a three-way blend.
        assert result.confidence == "medium"
        assert result.anchor_method == "dcf"
        assert result.valuation_withheld is False  # span 1.45 < 2x → point still publishable
        # Anchored to the cluster's DCF cash-flow value, never the $210 blend.
        canonical = resolve_canonical_thesis(result, "AAPL")
        assert canonical.target == pytest.approx(189.27, abs=0.01)
        assert canonical.verdict == "HOLD"  # verdict-invariant — the boss-signed property
        # The headline and the flagged outlier no longer disagree: ev_ebitda is the
        # outlier in BOTH outlier_methods AND the basis note (the bug was the blend
        # naming ev_ebitda an outlier while pricing it into the headline).
        assert result.outlier_methods == ["ev_ebitda"]
        assert "EV/EBITDA" in (result.degradation_note or "")
        assert "comps_pe" not in (result.degradation_note or "")  # not misnamed as the outlier
        # The full method range still bounds the band (outlier stays visible).
        assert result.target_low == pytest.approx(182.97, abs=0.01)
        assert result.target_high == pytest.approx(266.01, abs=0.01)

    def test_genuinely_corroborated_trio_still_blends_high_msft(self):
        """Guard the bimodal fix does NOT over-fire: a trio where ALL three sit within
        30% of the median is genuinely corroborated and must still blend high (no anchor).
        MSFT-shape: dcf $517 + ev_ebitda $545 + comps_pe $615, median $545, every method
        ≤ 13% off it → no median-outlier → not bimodal → corroborated-high blend, exactly
        as before the fix (the fix only fires on a true tight-cluster-plus-lone-outlier)."""
        methods = [
            ValuationMethod(name="dcf", low=465, mid=517.0, high=569, confidence=0.85, source="D"),
            ValuationMethod(
                name="ev_ebitda", low=490, mid=545.0, high=600, confidence=0.72, source="EV"
            ),
            ValuationMethod(
                name="comps_pe", low=554, mid=615.0, high=677, confidence=0.80, source="PE"
            ),
        ]
        result = synthesize_valuations(methods, current_price=390.0)
        assert result.confidence == "high"
        assert result.anchor_method is None  # blended, not anchored
        assert result.outlier_methods == []  # nothing > 30% off the median

    def test_upside_downside_equals_canonical_upside_every_regime(self):
        """Mechanical gate covering EVERY regime so the stored upside_downside can't
        silently desync from the number resolve_canonical_thesis reads as the
        directional gap (the −8.5%-vs-−32.6% KO bug):

          • multi-method (blended, anchored, withheld-range-spans-market): the stored
            field EQUALS resolve's upside, asserted exactly below.
          • single-method: the documented carve-out — the stored field is None (a lone
            method has no cross-checked blend, per the weighted_price=None contract)
            while resolve STILL derives a directional upside from the lone method's mid
            (the verdict must ship). Asserted so this boundary can't drift unnoticed.
        """
        blended = synthesize_valuations(
            [
                ValuationMethod(name="dcf", low=180, mid=200, high=220, confidence=0.5, source="d"),
                ValuationMethod(
                    name="comps", low=210, mid=230, high=250, confidence=0.5, source="c"
                ),
            ],
            current_price=300.0,
        )
        anchored = synthesize_valuations(
            [
                ValuationMethod(
                    name="dcf", low=61.1, mid=76.32, high=91.6, confidence=0.85, source="D"
                ),
                ValuationMethod(
                    name="comps_pe", low=48.2, mid=53.51, high=58.9, confidence=0.80, source="PE"
                ),
                ValuationMethod(
                    name="ev_ebitda", low=82.3, mid=89.67, high=97.1, confidence=0.72, source="EV"
                ),
            ],
            current_price=79.39,
        )
        spans = synthesize_valuations(
            [
                ValuationMethod(
                    name="dcf", low=151.72, mid=189.65, high=227.58, confidence=0.85, source="d"
                ),
                ValuationMethod(
                    name="comps_pe",
                    low=438.58,
                    mid=487.31,
                    high=536.04,
                    confidence=0.55,
                    source="c",
                ),
            ],
            current_price=425.0,
        )
        for vs, tkr in ((blended, "X"), (anchored, "KO"), (spans, "MSFT")):
            assert vs.upside_downside == pytest.approx(
                resolve_canonical_thesis(vs, tkr).upside, abs=1e-9
            )
        # the withheld-range-spans case reads a neutral 0% gap, not the anchor gap
        assert spans.valuation_withheld is True
        assert spans.upside_downside == pytest.approx(0.0, abs=1e-9)

        # RI-band regime (financial_sector): synthesize and resolve both read price-vs-band
        # off the SAME _ri_band_verdict, so the stored field must mirror resolve's upside in
        # every sub-case. Pins the new regime into this gate (the −40%-single-trough-ROE
        # point the band design refuses must never re-enter via a desynced stored field).
        ri_above = synthesize_valuations(
            [
                ValuationMethod(
                    name="comps_pb", low=200, mid=235, high=270, confidence=0.5, source="pb"
                ),
                ValuationMethod(
                    name="comps_pe", low=120, mid=134, high=150, confidence=0.5, source="pe"
                ),
                ValuationMethod(
                    name="residual_income", low=87, mid=87, high=129, confidence=0.6, source="ri"
                ),
            ],
            current_price=146.0,
            financial_sector=True,
        )
        ri_below = synthesize_valuations(
            [
                ValuationMethod(
                    name="comps_pb", low=260, mid=280, high=300, confidence=0.5, source="pb"
                ),
                ValuationMethod(
                    name="comps_pe", low=280, mid=300, high=320, confidence=0.5, source="pe"
                ),
                ValuationMethod(
                    name="residual_income", low=250, mid=250, high=290, confidence=0.6, source="ri"
                ),
            ],
            current_price=220.0,
            financial_sector=True,
        )
        for vs, tkr in ((ri_above, "C"), (ri_below, "PNC")):
            assert vs.anchor_method == "residual_income"
            assert vs.upside_downside == pytest.approx(
                resolve_canonical_thesis(vs, tkr).upside, abs=1e-9
            )
        # in-band: both the stored field and resolve's upside are None (point withheld, no
        # directional gap) — the band IS the refusal to claim one cycle-point value.
        ri_in = synthesize_valuations(
            [
                ValuationMethod(
                    name="comps_pb", low=280, mid=300, high=320, confidence=0.5, source="pb"
                ),
                ValuationMethod(
                    name="comps_pe", low=290, mid=310, high=330, confidence=0.5, source="pe"
                ),
                ValuationMethod(
                    name="residual_income", low=290, mid=290, high=340, confidence=0.6, source="ri"
                ),
            ],
            current_price=331.0,
            financial_sector=True,
        )
        assert ri_in.anchor_method == "residual_income"
        assert ri_in.upside_downside is None
        assert resolve_canonical_thesis(ri_in, "JPM").upside is None

        # single-method carve-out: the stored field is None (no cross-checked blend),
        # yet resolve still ships a directional upside off the lone method's mid so the
        # verdict isn't lost — the two are intentionally asymmetric ONLY here.
        single = synthesize_valuations(
            [
                ValuationMethod(
                    name="comps_pb", low=3.46, mid=4.61, high=5.76, confidence=0.6, source="PB"
                )
            ],
            current_price=16.52,
        )
        assert single.upside_downside is None
        assert resolve_canonical_thesis(single, "RIVN").upside is not None

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
                    name="Comps",
                    low=mid * 0.92,
                    mid=mid,
                    high=mid * 1.08,
                    confidence=0.4,
                    source="Comps",
                ),
            ]
            note = (
                synthesize_valuations(methods, current_price=price).degradation_note or ""
            ).lower()
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

    def test_withheld_multimethod_reads_nearest_edge_not_extreme_anchor(self):
        """Bug-1c (2026-06-24): point withheld + published range ENTIRELY above the
        market → upside/verdict must read off the NEAREST band EDGE, never the withheld
        extreme anchor. An insurer DCF reanchor printed ALL a +460% BUY off a $1297
        anchor at 5.6x price; the honest read is the gap to the nearest edge (~+40%),
        still a directional BUY. Mirrors the RI-band path and pins
        synthesize_valuations.upside_downside == the canonical upside."""
        methods = [
            ValuationMethod(
                name="dcf", low=1038, mid=1297, high=1557, confidence=0.85, source="DCF"
            ),
            ValuationMethod(
                name="ev_ebitda", low=1086, mid=1358, high=1630, confidence=0.72, source="EV"
            ),
            ValuationMethod(
                name="comps_pe", low=260, mid=325, high=390, confidence=0.80, source="PE"
            ),
        ]
        vs = synthesize_valuations(methods, current_price=232.0)
        canonical = resolve_canonical_thesis(vs, "TESTCO")
        assert canonical.valuation_withheld is True
        assert canonical.target is None
        assert canonical.verdict == "BUY"  # price below the whole range → directional BUY
        # The de-anchored bug read (1297-232)/232 = +459%; the edge read is far smaller.
        assert canonical.upside is not None and canonical.upside < 1.0, (
            f"upside {canonical.upside} still anchored to the withheld extreme point"
        )
        # Direction reads off the nearest edge (target_low, price below the band).
        assert canonical.upside == pytest.approx((vs.target_low - 232.0) / 232.0, abs=1e-6)
        # synthesize's stored upside_downside mirrors the canonical exactly (pinned).
        assert vs.upside_downside == pytest.approx(canonical.upside, abs=1e-9)

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
        # In-band → fairly-valued framing, not the "withheld" mechanic (2026-06-24).
        assert "FAIRLY VALUED" in canonical.basis
        assert "WITHHELD" not in canonical.basis
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

    @staticmethod
    def _ri(low: float, high: float) -> ValuationMethod:
        # A residual_income method carrying an explicit value band [RI at trailing ROE,
        # RI at forward consensus ROE]; mid = the trailing (independent) end.
        return ValuationMethod(
            name="residual_income", low=low, mid=low, high=high, confidence=0.6, source="ri"
        )

    def test_financial_sector_price_in_band_holds_and_withholds_point(self):
        # Price WITHIN the realized→forward RI band: a cyclical bank's value is a range, not
        # a single perpetuity ROE — verdict HOLD, point WITHHELD, the band still published.
        # The band is our refusal to claim one value; re-stamping a point would retract it.
        methods = [self._m("comps_pb", 300), self._m("comps_pe", 310), self._ri(290, 340)]
        vs = synthesize_valuations(methods, 331.0, financial_sector=True)
        assert vs.anchor_method == "residual_income"
        thesis = resolve_canonical_thesis(vs, "JPM")
        assert thesis.verdict == "HOLD"
        assert thesis.target is None  # 撤点 ≠ 撤区间
        assert thesis.valuation_withheld is True
        assert vs.target_low is not None and vs.target_high is not None  # band published
        # Fairly-valued framing: lead with the conclusion, never "WITHHELD" (2026-06-24).
        assert thesis.basis is not None and "FAIRLY VALUED" in thesis.basis
        assert "WITHHELD" not in thesis.basis
        # Control: identical methods for a non-bank do NOT take the RI band path.
        nb = synthesize_valuations(methods, 331.0, financial_sector=False)
        assert nb.anchor_method != "residual_income"

    def test_financial_sector_price_above_band_directional_from_consensus_ceiling(self):
        # Citi-shape: price $146 ABOVE the recovery end of the band [$87 realized → $129
        # forward consensus]. The market pays more than even the bank's OWN best case (full
        # consensus recovery) justifies → independent bearish read a consensus-parroting
        # engine cannot produce. Target = the consensus ceiling (nearest edge), upside MILD
        # (~−12%), NOT the −40% a single-trough-ROE point would have stamped.
        vs = synthesize_valuations(
            [self._m("comps_pb", 235), self._m("comps_pe", 134), self._ri(87, 129)],
            146.0,
            financial_sector=True,
        )
        assert vs.anchor_method == "residual_income"
        thesis = resolve_canonical_thesis(vs, "C")
        assert thesis.verdict == "SELL"  # independent: above even the consensus ceiling
        assert thesis.target == pytest.approx(129, abs=0.5)  # the forward-consensus ceiling
        assert thesis.upside == pytest.approx(-0.116, abs=0.01)  # mild, not −40%
        assert thesis.valuation_withheld is False
        assert vs.upside_downside == pytest.approx(thesis.upside)  # pinned mirror

    def test_financial_sector_price_below_band_directional_from_realized_floor(self):
        # Price below even the realized-ROE floor of the band → cheap vs fundamentals,
        # directional from the low (realized) edge.
        vs = synthesize_valuations(
            [self._m("comps_pb", 280), self._m("comps_pe", 300), self._ri(250, 290)],
            220.0,
            financial_sector=True,
        )
        assert vs.anchor_method == "residual_income"
        thesis = resolve_canonical_thesis(vs, "PNC")
        assert thesis.verdict == "BUY"  # below even the realized-ROE floor → cheap
        assert thesis.target == pytest.approx(250, abs=0.5)  # realized-ROE floor (nearest edge)
        assert thesis.upside == pytest.approx(0.136, abs=0.01)
        assert thesis.valuation_withheld is False

    def test_financial_sector_extreme_residual_income_still_capped(self):
        # The out-of-calibration cap still guards RI: an RI in the EXTREME band (< 0.125x =
        # 1/(2·4x) the market price — the market prices something the fundamental anchor
        # can't see) withholds the point. RI anchoring banks does NOT bypass the safety net.
        vs = synthesize_valuations(
            [
                self._m("comps_pb", 6),
                self._m("comps_pe", 5),
                self._m("residual_income", 5),
            ],
            60.0,
            financial_sector=True,
        )
        assert vs.valuation_withheld is True

    def test_financial_sector_without_residual_income_blends_gracefully(self):
        # A bank whose RI failed to compute (negative book / ROE far below CoE) carries only
        # comps. With no RI row the special case does not fire — it blends like any other
        # corroborated set (anchor None), so the bank path degrades gracefully.
        vs = synthesize_valuations(
            [self._m("comps_pb", 100), self._m("comps_pe", 110)], 105.0, financial_sector=True
        )
        assert vs.anchor_method is None
        assert vs.confidence == "high"

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
            assert vs.target_low is not None and vs.target_high is not None, (
                f"dial blanked the range for {names} @ {price} (withheld={vs.valuation_withheld})"
            )
            assert vs.target_high >= vs.target_low


class TestMnaTransitionGate:
    """A just-closed stock-funded acquisition leaves the TTM snapshot mixing a
    post-deal share count with mostly-pre-deal earnings → every method reads
    spuriously bearish (FITB/Comerica: ddm/comps all ~−30% vs a Buy sell-side).
    On the mna_transition flag the synthesis withholds the poisoned point and the
    verdict is held neutral (HOLD), NOT a fabricated SELL. Data-lineage degradation,
    not calibration."""

    @staticmethod
    def _fitb_methods() -> list[ValuationMethod]:
        # All three methods corroborated and ~30% below market → would normally
        # anchor a confident SELL; the transition flag must neutralise that.
        return [
            ValuationMethod(name="comps_pb", low=33, mid=37, high=41, confidence=0.4, source="PB"),
            ValuationMethod(name="comps_pe", low=29, mid=32, high=35, confidence=0.4, source="PE"),
            ValuationMethod(name="ddm", low=33, mid=36, high=39, confidence=0.5, source="DDM"),
        ]

    def test_transition_withholds_point_and_holds_verdict_neutral(self):
        vs = synthesize_valuations(self._fitb_methods(), 53.61, mna_transition=True)
        assert vs.mna_transition is True
        assert vs.valuation_withheld is True
        assert vs.upside_downside is None  # mirrors canonical (no usable direction)
        assert "acquisition" in (vs.degradation_note or "")
        thesis = resolve_canonical_thesis(vs, "FITB")
        assert thesis.verdict == "HOLD"
        assert thesis.target is None
        assert thesis.upside is None
        assert thesis.valuation_withheld is True
        # methods still surfaced for transparency — as human-readable labels
        # (_method_label), the same labels the football field shows.
        assert "Comps (P/E)" in (thesis.basis or "") and "DDM" in (thesis.basis or "")

    def test_same_methods_without_flag_ship_the_bearish_call(self):
        """Variable isolation: the ONLY thing the flag changes is the gate. Without
        it, the identical corroborated-low methods publish a real SELL with a point."""
        vs = synthesize_valuations(self._fitb_methods(), 53.61, mna_transition=False)
        assert vs.mna_transition is False
        thesis = resolve_canonical_thesis(vs, "FITB")
        assert thesis.verdict == "SELL"
        assert thesis.target is not None  # a confident (poisoned, pre-fix) point

    def test_default_off_is_regression_safe(self):
        """Default (no flag) must be byte-identical to the pre-change behaviour."""
        methods = self._fitb_methods()
        with_default = synthesize_valuations(methods, 53.61)
        explicit_off = synthesize_valuations(methods, 53.61, mna_transition=False)
        assert with_default.mna_transition is False
        assert with_default.model_dump() == explicit_off.model_dump()

    def test_single_method_transition_also_gated(self):
        vs = synthesize_valuations(
            [ValuationMethod(name="ddm", low=33, mid=36, high=39, confidence=0.5, source="DDM")],
            53.61,
            mna_transition=True,
        )
        assert vs.mna_transition is True and vs.valuation_withheld is True
        assert resolve_canonical_thesis(vs, "FITB").verdict == "HOLD"


class TestReratingDominanceGate:
    """P0-1.2 (2026-07-07, lead-signed K=1.3 / M=15%): a corroborated blend whose
    multiples methods (a) bet on a multiple shift beyond RERATING_GAP_RATIO_K and
    (b) drag the blend more than RERATING_ANCHOR_DISPLACEMENT_M off the DCF anchor
    is re-rating-LED — cap confidence at medium and put the DCF-only anchor beside
    the blend. Changes no number, drops no method, never touches the verdict
    directly, and (红线) stays orthogonal to market distance: a corroborated
    SELL/deep-value BUY has near-zero blend-vs-DCF displacement and never trips."""

    @staticmethod
    def _m(name: str, mid: float, conf: float, rerating: float | None = None) -> ValuationMethod:
        return ValuationMethod(
            name=name,
            low=mid * 0.9,
            mid=mid,
            high=mid * 1.1,
            confidence=conf,
            source=name,
            rerating_ratio=rerating,
        )

    def _msft_shape(self) -> list[ValuationMethod]:
        # The 2026-07-07 archetype (post-liveness artifact 64dda9), re-based to the
        # batch2 TTM denominator: dcf $451.22 / comps_pe $534.23 (re-rate 1.38×) /
        # ev_ebitda $605.15 (1.57×). The ev row WAS $632.34/1.64× on the old FMP
        # forward denominator; folding it back to TTM operating EBITDA scales both the
        # mid and the re-rating ratio by MSFT's measured ~0.957 trailing/forward EBITDA
        # ratio (632.34×0.957≈605.15, 1.64×0.957≈1.57 — live-probed 2026-07-08). The
        # gate is about the GEOMETRY, not the exact old value: span 1.34 and a DCF still
        # inside the median cluster slip BOTH existing gates, and the blend lands +16.6%
        # off the DCF anchor → the re-rating-dominance gate caps confidence to medium.
        return [
            self._m("dcf", 451.22, 0.85),
            self._m("comps_pe", 534.23, 0.80, rerating=1.38),
            self._m("ev_ebitda", 605.15, 0.72, rerating=1.57),
        ]

    def test_rerating_led_blend_caps_confidence_shows_dcf_anchor_msft_2026_07_07(self):
        vs = synthesize_valuations(self._msft_shape(), 386.74)
        assert vs.confidence == "medium"  # capped from high
        # The blend itself is untouched (gate re-grades, never re-prices) and the
        # point still publishes — not a withhold.
        assert vs.weighted_price == pytest.approx(526.00, abs=0.05)
        assert vs.valuation_withheld is False
        assert vs.anchor_method is None
        note = vs.degradation_note or ""
        assert "capped at medium" in note.lower()
        assert "$451" in note  # the DCF-only anchor shown alongside (a method mid)
        assert "re-rating" in note
        # note must GRADE, never CLASSIFY the gap's nature (reverse-DCF owns that).
        assert "option value" not in note.lower()
        # Verdict ships from the medium bands: +38% ≥ 30% buy bar → still BUY.
        thesis = resolve_canonical_thesis(vs, "MSFT")
        assert thesis.verdict == "BUY"
        assert thesis.confidence == "medium"
        assert thesis.target == pytest.approx(vs.weighted_price, abs=0.01)
        assert "capped at medium" in (thesis.basis or "").lower()

    def test_corroborated_sell_with_derate_premise_is_not_capped(self):
        # 红线 lock: dcf $60 + comps_pe $55 both far BELOW the $100 market — the
        # comps de-rate premise breaches K (0.55 < 1/1.3) but the methods AGREE, so
        # the blend sits ~4% off DCF and condition (b) never fires. Two methods
        # both saying rich stays a HIGH-confidence SELL.
        vs = synthesize_valuations(
            [self._m("dcf", 60.0, 0.85), self._m("comps_pe", 55.0, 0.80, rerating=0.55)],
            100.0,
        )
        assert vs.confidence == "high"
        assert "capped" not in (vs.degradation_note or "").lower()
        assert resolve_canonical_thesis(vs, "T").verdict == "SELL"

    def test_corroborated_deep_value_buy_is_not_capped(self):
        # Mirror red-line: both methods far ABOVE market, agreeing with each other.
        vs = synthesize_valuations(
            [self._m("dcf", 150.0, 0.85), self._m("comps_pe", 140.0, 0.80, rerating=1.40)],
            100.0,
        )
        assert vs.confidence == "high"
        assert "capped" not in (vs.degradation_note or "").lower()

    def test_ratios_inside_gap_do_not_cap_even_with_displacement(self):
        # Condition (a) independent: all premises within K=1.3 → the blend's
        # displacement alone (here +23%) is corroborated method disagreement-of-
        # degree, not a premise bet — stays high.
        vs = synthesize_valuations(
            [
                self._m("dcf", 100.0, 0.85),
                self._m("comps_pe", 129.0, 0.80, rerating=1.29),
                self._m("ev_ebitda", 145.0, 0.72, rerating=1.29),
            ],
            100.0,
        )
        assert vs.confidence == "high"

    def test_gate_inert_without_dcf_cash_flow_reference(self):
        # No DCF in the set → no cash-flow anchor to displace from → inert (the
        # per-method re-rating warnings still disclose the premise upstream).
        vs = synthesize_valuations(
            [
                self._m("comps_pe", 140.0, 0.80, rerating=1.40),
                self._m("ev_ebitda", 150.0, 0.72, rerating=1.50),
            ],
            100.0,
        )
        assert vs.confidence == "high"
        assert "capped" not in (vs.degradation_note or "").lower()

    def test_derate_dominant_blend_caps_symmetrically(self):
        # Symmetric side: a breaching DE-rate premise (comps_pe 0.70× < 1/1.3)
        # drags the blend −18% below a DCF that reads the name roughly fair — the
        # bearish tilt rests on the premise, not on corroborated cash flow → cap.
        # Geometry deliberately keeps DCF INSIDE the 30% median cluster (deviation
        # 22%, span 1.43): a deeper de-rate would route to the bimodal branch
        # first (DCF becomes the lone median-outlier), which already grades
        # medium and anchors the cluster — the gate owns only the blend branch.
        vs = synthesize_valuations(
            [
                self._m("dcf", 100.0, 0.60),
                self._m("comps_pe", 70.0, 0.90, rerating=0.70),
                self._m("ev_ebitda", 82.0, 0.90, rerating=0.82),
            ],
            100.0,
        )
        assert vs.confidence == "medium"
        assert "capped at medium" in (vs.degradation_note or "").lower()

    def test_displacement_below_m_with_breach_is_not_capped(self):
        # Breach present but the blend hugs the DCF anchor (≤15%) → the premise
        # is disclosed upstream yet does not LEAD the headline — stays high.
        vs = synthesize_valuations(
            [
                self._m("dcf", 100.0, 0.85),
                self._m("comps_pe", 112.0, 0.80, rerating=1.38),
                self._m("ev_ebitda", 108.0, 0.72, rerating=1.35),
            ],
            100.0,
        )
        assert vs.confidence == "high"


class TestStreetRangeDisclosure:
    """Standing street-context fact line (boss-approved 2026-07-08, widened
    2026-07-09 — BACKLOG A9/B1): pure fact whenever the sell-side distribution is
    available; the out-of-consensus clause only APPENDS when OUR 12-month target
    sits entirely outside the sell-side range — never a gate."""

    def test_in_band_shows_pure_fact_line_no_judgment(self):
        from finrobot.engine.compute.operators.valuation_synthesis import (
            STREET_CONTEXT_MARKER,
            street_range_disclosure,
        )

        note = street_range_disclosure(400.0, 360.0, 480.0, analyst_count=45, consensus=420.0)
        assert note is not None
        assert note.startswith(STREET_CONTEXT_MARKER)
        assert "$360.00" in note and "$480.00" in note
        assert "$420.00" in note and "45 analysts" in note
        # Pure fact — no judgment words, no out-of-consensus clause.
        assert "below" not in note and "above" not in note
        assert "out-of-consensus" not in note
        assert "does not alter the verdict or confidence" not in note

    def test_below_entire_range_appends_out_of_consensus_clause(self):
        from finrobot.engine.compute.operators.valuation_synthesis import (
            STREET_CONTEXT_MARKER,
            street_range_disclosure,
        )

        note = street_range_disclosure(274.32, 360.0, 480.0, analyst_count=42, consensus=420.0)
        assert note is not None
        assert "below" in note
        assert "$274.32" in note and "$360.00" in note and "$480.00" in note
        assert "42 analysts" in note
        # Disclosure, not degradation — the sentence itself must say so.
        assert "does not alter the verdict or confidence" in note
        # Stable marker the frontend routes on (relocates this line from the ⚠
        # pile to the valuation box). Reword only through STREET_CONTEXT_MARKER.
        assert note.startswith(STREET_CONTEXT_MARKER)

    def test_above_entire_range_appends_out_of_consensus_clause(self):
        from finrobot.engine.compute.operators.valuation_synthesis import (
            street_range_disclosure,
        )

        note = street_range_disclosure(500.0, 360.0, 480.0)
        assert note is not None and "above" in note
        assert "does not alter the verdict or confidence" in note
        assert "analysts" not in note  # count unavailable → omitted, not fabricated
        assert "consensus $" not in note  # consensus unavailable → omitted, not fabricated

    def test_missing_or_nonpositive_inputs_return_none(self):
        from finrobot.engine.compute.operators.valuation_synthesis import (
            street_range_disclosure,
        )

        assert street_range_disclosure(None, 360.0, 480.0) is None
        assert street_range_disclosure(274.0, None, 480.0) is None
        assert street_range_disclosure(274.0, 360.0, None) is None
        assert street_range_disclosure(274.0, 0.0, 480.0) is None
        assert street_range_disclosure(-5.0, 360.0, 480.0) is None

    def test_degenerate_band_returns_none(self):
        from finrobot.engine.compute.operators.valuation_synthesis import (
            street_range_disclosure,
        )

        assert street_range_disclosure(274.0, 480.0, 360.0) is None  # low > high
