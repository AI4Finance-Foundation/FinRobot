"""NumericClaim / Finding — the report numeric-audit ledger leaf model.

Findings are produced by compute/operators/audit verifiers; the field_status
rollup turns a list of findings into one gate verdict (worst severity wins).
"""

from __future__ import annotations

import pytest

from finrobot.engine.models.numeric_claim import Finding, NumericClaim, rollup_status


def _f(severity: str, check: str = "c") -> Finding:
    return Finding(field_key="x", check=check, severity=severity, evidence="e")


class TestRollup:
    def test_no_findings_is_pass(self):
        assert rollup_status([]) == "pass"

    def test_info_only_is_pass(self):
        # info is advisory — it never gates.
        assert rollup_status([_f("info")]) == "pass"

    def test_review_is_review(self):
        assert rollup_status([_f("review")]) == "review"

    def test_blocked_field_dominates_review(self):
        assert rollup_status([_f("review", "a"), _f("blocked_field", "b")]) == "blocked_field"

    def test_review_dominates_info(self):
        assert rollup_status([_f("info", "a"), _f("review", "b")]) == "review"


class TestNumericClaim:
    def test_defaults_to_pass(self):
        assert NumericClaim(field_key="pe_ratio", value=20.0).field_status == "pass"

    def test_field_status_reflects_worst_finding(self):
        claim = NumericClaim(
            field_key="ev_ebitda",
            value=3.2,
            findings=[
                Finding(
                    field_key="ev_ebitda",
                    check="financial_sector_ev_meaningless",
                    severity="blocked_field",
                    evidence="bank",
                )
            ],
        )
        assert claim.field_status == "blocked_field"

    def test_value_may_be_none(self):
        # A withheld number is still a claim (e.g. ADR P/E rendered N/A).
        assert NumericClaim(field_key="pe_ratio", value=None).field_status == "pass"


class TestFindingImmutable:
    def test_finding_is_frozen(self):
        f = _f("info")
        with pytest.raises(Exception):  # noqa: B017 - pydantic frozen raises ValidationError
            f.field_key = "y"
