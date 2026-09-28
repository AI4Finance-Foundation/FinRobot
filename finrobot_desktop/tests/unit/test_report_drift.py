"""Report narrative drift detector — detect-and-flag, NEVER rewrite.

The report step is a pure LLM assembly of already-computed numbers, so every
$-amount it prints should trace to SOME numeric leaf of the structured snapshot
it was given. An unmatched amount is either an LLM-derived restatement or a
fabricated figure — indistinguishable mechanically, which is exactly why this
guard only flags (a false-positive REWRITE would corrupt a legitimate $391B
revenue into a price target; a false-positive WARNING costs one triage glance).
"""

from __future__ import annotations

from finrobot.engine.compute.operators.report_drift import (
    collect_numeric_leaves,
    detect_report_drift,
)
from finrobot.engine.models.reconcile_tolerances import NARRATIVE_DRIFT_TOLERANCE


class TestCollectNumericLeaves:
    def test_walks_nested_dicts_lists_and_scalars(self):
        payload = {
            "thesis": {"price_target": 276.43, "mids": [250.0, 300.0]},
            "income": {"revenue": 391_035_000_000.0},
            "label": "not a number",
            "flag": True,  # bools are NOT numbers (True == 1 would poison matching)
            "none": None,
        }
        leaves = collect_numeric_leaves(payload)
        assert 276.43 in leaves
        assert 250.0 in leaves and 300.0 in leaves
        assert 391_035_000_000.0 in leaves
        assert 1.0 not in leaves  # the bool must not leak in
        assert len(leaves) == 4

    def test_non_finite_leaves_are_dropped(self):
        leaves = collect_numeric_leaves({"a": float("nan"), "b": float("inf"), "c": 5.0})
        assert leaves == {5.0}


class TestDetectReportDrift:
    LEAVES = {276.43, 391_035_000_000.0, 96_995_000_000.0, 425.10}

    def test_exact_and_rounded_amounts_match(self):
        # "$276" vs canonical 276.43 is a display rounding (0.16% < 1% shared
        # tolerance), not drift — same rule as the thesis-side reconcile.
        report = "Target price $276 (vs market $425.10). Revenue USD 391B."
        drift = detect_report_drift(report, self.LEAVES)
        assert drift.unmatched_count == 0
        assert drift.total_dollar_amounts == 3

    def test_unit_suffixes_scale_before_matching(self):
        # B/M suffixes scale to absolute before matching the raw leaves.
        report = "EBITDA of $96,995M and revenue of $391.0B."
        drift = detect_report_drift(report, self.LEAVES)
        assert drift.unmatched_count == 0

    def test_fabricated_amount_is_flagged_not_rewritten(self):
        report = "We see fair value near $280.00 on FY1 earnings."
        drift = detect_report_drift(report, self.LEAVES)
        assert drift.unmatched_count == 1
        assert drift.unmatched[0].token == "$280.00"
        assert drift.unmatched[0].value == 280.0
        # Detector is pure — the report text is not part of the result at all,
        # so there is nothing it COULD have rewritten.

    def test_amount_within_tolerance_of_no_leaf_but_near_two(self):
        # 280 sits between 276.43 (+1.3%) and 285 — outside 1% of both → drift.
        leaves = {276.43, 285.0}
        drift = detect_report_drift("prose says $280", leaves)
        assert drift.unmatched_count == 1
        assert NARRATIVE_DRIFT_TOLERANCE < abs(280 - 276.43) / 276.43

    def test_percent_tokens_are_not_dollar_amounts(self):
        # "$" regex must not pick up bare percents; mixed text only flags the
        # genuinely unmatched dollar amount.
        report = "Margin 45.2% and growth 12%; one-off charge of $123.45."
        drift = detect_report_drift(report, self.LEAVES)
        assert drift.total_dollar_amounts == 1
        assert drift.unmatched_count == 1

    def test_degenerate_empty_report_and_empty_leaves(self):
        assert detect_report_drift("", self.LEAVES).unmatched_count == 0
        # No registry at all → every amount is unmatched (honest signal that the
        # builder failed to hand the detector a snapshot, not silently green).
        drift = detect_report_drift("price $10.00", set())
        assert drift.unmatched_count == 1

    def test_findings_are_capped_but_count_is_honest(self):
        report = " ".join(f"${i}.77" for i in range(1000, 1030))
        drift = detect_report_drift(report, self.LEAVES, max_findings=5)
        assert len(drift.unmatched) == 5
        assert drift.unmatched_count == 30

    def test_comma_grouped_amounts_parse(self):
        drift = detect_report_drift("debt of $1,234.50M", {1_234_500_000.0})
        assert drift.unmatched_count == 0


class TestNegativeAmounts:
    """Negative leaves are legitimate (negative FCF, loss-quarter NI, net-cash
    net debt); the parser must round-trip every written negative shape back to
    the signed leaf instead of dropping the sign and flagging the citation."""

    def test_leading_minus_matches_negative_leaf(self):
        # -$5.00B citing FCF leaf -5e9: sign-aware round trip, no flag.
        drift = detect_report_drift("FY1 FCF of -$5.00B on heavy capex.", {-5_000_000_000.0})
        assert drift.unmatched_count == 0
        assert drift.total_dollar_amounts == 1

    def test_unicode_minus_matches_negative_leaf(self):
        drift = detect_report_drift("FCF of −$5.00B.", {-5_000_000_000.0})
        assert drift.unmatched_count == 0

    def test_post_symbol_minus_matches_negative_leaf(self):
        # The shape live narratives actually printed: "implies $-1512.42" (BUG-074).
        drift = detect_report_drift("implies $-1512.42 per share", {-1512.42})
        assert drift.unmatched_count == 0

    def test_accounting_parens_match_either_sign(self):
        # ($5.00B) is accounting-negative in tables but a plain parenthetical in
        # prose — flag-only guard accepts either sign rather than false-flagging.
        drift_neg = detect_report_drift("net loss ($5.00B) for FY1", {-5_000_000_000.0})
        assert drift_neg.unmatched_count == 0
        drift_pos = detect_report_drift("revenue ($5.00B) grew 12%", {5_000_000_000.0})
        assert drift_pos.unmatched_count == 0

    def test_explicit_minus_does_not_match_positive_leaf(self):
        # Sign contradiction IS drift: prose "-$5.00B" with only +5e9 computed.
        drift = detect_report_drift("FCF of -$5.00B.", {5_000_000_000.0})
        assert drift.unmatched_count == 1
        assert drift.unmatched[0].value == -5_000_000_000.0
        assert drift.unmatched[0].token == "-$5.00B"

    def test_minus_with_iso_code(self):
        drift = detect_report_drift("net debt of USD -3.2B (net cash).", {-3_200_000_000.0})
        assert drift.unmatched_count == 0

    def test_unclosed_paren_is_not_negative(self):
        # "(see $5.00B above)" — paren not closed adjacent to the amount; the
        # value stays positive-only and matches the positive leaf.
        drift = detect_report_drift("(see $5.00B above for detail)", {5_000_000_000.0})
        assert drift.unmatched_count == 0


class TestSpelledOutMagnitudes:
    """The deterministic ``format_summary`` narrative prints magnitudes as WORDS
    ("$451.442 Billion USD"), not single-letter suffixes. The detector must scale
    the word forms exactly like B/M/T, else every spelled-out figure (= nearly
    every line of a DCF/DDM narrative) is parsed at 1e9-too-small and flagged as
    drift against the absolute leaf — the systematic false positive that flooded
    49/50 live artifacts (DDM/DCF up to 80% unmatched) with a real number behind
    every flag."""

    def test_billion_word_scales_and_matches(self):
        # The exact AAPL live shape: "$451.442 Billion USD (TTM)" vs leaf 451.442e9.
        drift = detect_report_drift("Revenue: $451.442 Billion USD (TTM)", {451_442_000_000.0})
        assert drift.total_dollar_amounts == 1
        assert drift.unmatched_count == 0

    def test_trillion_word_scales_and_matches(self):
        # Market cap "$4.041 Trillion USD" vs a 1%-near leaf (price×shares).
        drift = detect_report_drift(
            "Market Capitalization: $4.041 Trillion USD", {4_057_430_003_400.0}
        )
        assert drift.unmatched_count == 0

    def test_million_and_thousand_words_scale(self):
        drift = detect_report_drift(
            "D&A of $12.61 Million and a $250 Thousand one-off.",
            {12_610_000.0, 250_000.0},
        )
        assert drift.unmatched_count == 0

    def test_lowercase_word_and_letter_forms(self):
        # LLM prose freely mixes "$391b", "USD 391 billion", "$96,995 mn".
        drift = detect_report_drift(
            "rev $391b, or USD 391 billion; ebitda $96,995 mn.",
            {391_000_000_000.0, 96_995_000_000.0},
        )
        assert drift.unmatched_count == 0

    def test_bn_tn_abbreviations_scale(self):
        drift = detect_report_drift(
            "debt $84.711bn, cap $4.04tn.", {84_711_000_000.0, 4_040_000_000_000.0}
        )
        assert drift.unmatched_count == 0

    def test_word_magnitude_still_flags_genuine_drift(self):
        # The fix scales the unit — it must NOT mask a real contradiction: a
        # fabricated "$500 Billion" with no leaf near 5e11 still flags.
        drift = detect_report_drift(
            "We model revenue reaching $500 Billion next year.", {451_442_000_000.0}
        )
        assert drift.unmatched_count == 1
        assert drift.unmatched[0].value == 500_000_000_000.0

    def test_negative_billion_word_round_trips(self):
        # Sign-aware parsing composes with word suffixes (net-cash net debt).
        drift = detect_report_drift("net debt of -$17.93 Billion (net cash).", {-17_930_000_000.0})
        assert drift.unmatched_count == 0


class TestApproximationBand:
    """Unmatched amounts split by distance to the nearest leaf: within the band
    ⇒ approximation (kept — a legit LLM rounding of a real computed value),
    beyond ⇒ orphan (the ONLY redaction candidates). Band calibrated on the
    stored-artifact corpus — see reconcile_tolerances.NARRATIVE_APPROXIMATION_BAND."""

    def test_near_leaf_amount_is_approximation_not_orphan(self):
        # "roughly $400B" against the 391.035B revenue leaf: 2.3% off — outside
        # the 1% match, inside the 10% band. Kept, never in the redaction set.
        drift = detect_report_drift("revenue of roughly $400B", {391_035_000_000.0})
        assert drift.unmatched_count == 1
        assert drift.approximate_count == 1
        assert drift.orphan_count == 0
        assert drift.orphan_tokens == []
        gap = drift.unmatched[0].nearest_gap
        assert gap is not None and 0.02 < gap < 0.03

    def test_far_from_every_leaf_is_orphan(self):
        drift = detect_report_drift("a $120B charge", {391_035_000_000.0, 425.10})
        assert drift.approximate_count == 0
        assert drift.orphan_count == 1
        assert drift.orphan_tokens == ["$120B"]

    def test_band_boundary_splits_kept_vs_orphan(self):
        # Leaf 100: $109 (9% off) stays; $115 (15% off) is an orphan.
        drift = detect_report_drift("levels near $109 then $115", {100.0})
        assert drift.unmatched_count == 2
        assert drift.approximate_count == 1
        assert drift.orphan_tokens == ["$115"]

    def test_empty_registry_makes_every_amount_an_orphan(self):
        # No snapshot handed over must stay a LOUD signal — nothing to be
        # "approximately near", so nothing is spared from the redaction set.
        drift = detect_report_drift("price $10.00", set())
        assert drift.orphan_count == 1
        assert drift.orphan_tokens == ["$10.00"]
        assert drift.unmatched[0].nearest_gap is None

    def test_orphan_tokens_are_complete_beyond_the_findings_cap(self):
        # The findings list is capped for provenance readability, but the
        # redaction set must be COMPLETE — a capped set once let unmatched
        # tokens past the window ship unredacted.
        report = " ".join(f"${i}.77" for i in range(1000, 1030))
        drift = detect_report_drift(report, {276.43}, max_findings=5)
        assert len(drift.unmatched) == 5
        assert drift.orphan_count == 30
        assert len(drift.orphan_tokens) == 30
