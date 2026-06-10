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
