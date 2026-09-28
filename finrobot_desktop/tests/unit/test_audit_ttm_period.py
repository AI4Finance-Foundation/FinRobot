"""Family-4 verifier: TTM period completeness / non-overlap.

A trailing-twelve-month snapshot is Σ of four consecutive quarters. If the
provider's quarter set overlaps (a restated quarter double-counted), gaps (a
quarter missing), or is short (<4 quarters), the TTM aggregate — and every
ratio built on it (P/E, EV/EBITDA, margins) and the DCF growth fed from it —
is silently wrong, and code review cannot see it.

This is a DEFINITIONAL check, not a calibrated one: a fiscal quarter is 13-14
weeks (≈91 days; 90-96 observed live, incl. KO's 52/53-week retail calendar).
The gap band [45, 135] days flags only the physically impossible — an overlap
(<45, two "quarters" too close) or a missing quarter (>135, ≈182 in practice) —
so a clean 4-quarter sequence can never false-positive.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from finrobot.engine.compute.operators.audit.ttm_period import audit_ttm_period
from finrobot.engine.models.financial import (
    FinancialData,
    IncomeStatement,
    MarketData,
)


def _fd(ends: list[date]) -> FinancialData:
    return FinancialData(
        ticker="X",
        timestamp=datetime.now(tz=timezone.utc),
        income=IncomeStatement(revenue=100e9, net_income=20e9),
        market=MarketData(market_cap=500e9, shares_outstanding=5e9, current_price=100.0),
        ttm_quarter_ends=ends,
    )


def _checks(findings) -> set[tuple[str, str, str]]:
    return {(f.field_key, f.check, f.severity) for f in findings}


class TestCleanSequences:
    def test_clean_four_quarters_no_finding(self):
        # Real AAPL quarter-ends (FMP, 2026-06-06), gaps 91/91/91.
        ends = [date(2026, 3, 28), date(2025, 12, 27), date(2025, 9, 27), date(2025, 6, 28)]
        assert audit_ttm_period(_fd(ends)) == []

    def test_53_week_retail_calendar_no_finding(self):
        # Real KO quarter-ends — a 96-day gap on the 52/53-week calendar must NOT
        # trip the guard (the zero-false-positive requirement).
        ends = [date(2026, 4, 3), date(2025, 12, 31), date(2025, 9, 26), date(2025, 6, 27)]
        assert audit_ttm_period(_fd(ends)) == []

    def test_order_independent(self):
        # The provider carries newest-first; oldest-first must give the same verdict.
        ends = [date(2025, 6, 28), date(2025, 9, 27), date(2025, 12, 27), date(2026, 3, 28)]
        assert audit_ttm_period(_fd(ends)) == []


class TestDefects:
    def test_missing_quarter_blocked(self):
        # Dec-2025 quarter missing → a 182-day gap between Mar-2026 and Sep-2025.
        ends = [date(2026, 3, 31), date(2025, 9, 30), date(2025, 6, 30), date(2025, 3, 31)]
        f = audit_ttm_period(_fd(ends))
        assert ("ttm_period", "ttm_quarter_gap", "blocked_field") in _checks(f)

    def test_duplicate_quarter_overlap_blocked(self):
        # Same end date twice (a restatement double-counted) → gap 0 → overlap.
        ends = [date(2026, 3, 31), date(2026, 3, 31), date(2025, 12, 31), date(2025, 9, 30)]
        f = audit_ttm_period(_fd(ends))
        assert ("ttm_period", "ttm_quarter_overlap", "blocked_field") in _checks(f)

    def test_restatement_near_duplicate_overlap_blocked(self):
        # Two ends 31 days apart — too close to be distinct quarters.
        ends = [date(2026, 3, 31), date(2026, 2, 28), date(2025, 11, 30), date(2025, 8, 31)]
        f = audit_ttm_period(_fd(ends))
        assert ("ttm_period", "ttm_quarter_overlap", "blocked_field") in _checks(f)

    def test_incomplete_count_review(self):
        # Only 3 quarters built into the "TTM" — incomplete, can be legit (recent
        # IPO / provider lag), so REVIEW (flag + keep caveated target), not blocked.
        ends = [date(2026, 3, 31), date(2025, 12, 31), date(2025, 9, 30)]
        f = audit_ttm_period(_fd(ends))
        assert ("ttm_period", "ttm_quarters_incomplete", "review") in _checks(f)
        assert all(sev == "review" for _, _, sev in _checks(f))

    def test_single_quarter_review_only(self):
        ends = [date(2026, 3, 31)]
        f = audit_ttm_period(_fd(ends))
        assert _checks(f) == {("ttm_period", "ttm_quarters_incomplete", "review")}


class TestSemiAnnualCadence:
    def test_clean_two_half_years_no_finding(self):
        # UL / RIO / BHP live: a semi-annual filer's TTM is 2 six-month periods
        # (~184d apart). Must NOT flag "missing quarter" (184d gap) or "incomplete"
        # (2 periods) — the cadence is read from the spacing.
        ends = [date(2025, 12, 31), date(2025, 6, 30)]
        assert audit_ttm_period(_fd(ends)) == []

    def test_missing_half_year_incomplete_review(self):
        # A lone half-year end → incomplete against the 2-period semi-annual cadence.
        # (One end alone can't classify cadence → defaults to quarterly's expected 4,
        # still incomplete → review; the point is it stays review, never blocked.)
        ends = [date(2025, 12, 31)]
        f = audit_ttm_period(_fd(ends))
        assert all(sev == "review" for _, _, sev in _checks(f))

    def test_three_half_years_excess_blocked(self):
        # Three 6-month ends (~18 months) overstate the trailing twelve → excess.
        ends = [date(2025, 12, 31), date(2025, 6, 30), date(2024, 12, 31)]
        f = audit_ttm_period(_fd(ends))
        assert ("ttm_period", "ttm_quarters_excess", "blocked_field") in _checks(f)


class TestNoData:
    def test_empty_quarter_ends_no_finding(self):
        # yfinance / annual snapshots carry no per-quarter dates — nothing to audit.
        assert audit_ttm_period(_fd([])) == []


class TestExcessQuarters:
    def test_five_normally_spaced_quarters_blocked(self):
        """Restatement drift: the provider ships old+new rows side by side —
        five quarter-ends, every pairwise gap a normal ~91d. The pairwise
        checks pass, but the TTM aggregate sums 15 months into the "trailing
        twelve" (~25% overstated). The count check must defend BOTH sides,
        not only the short one."""
        ends = [
            date(2026, 3, 31),
            date(2025, 12, 31),
            date(2025, 9, 30),
            date(2025, 6, 30),
            date(2025, 3, 31),
        ]
        findings = audit_ttm_period(_fd(ends))
        assert ("ttm_period", "ttm_quarters_excess", "blocked_field") in _checks(findings)

    def test_exactly_four_quarters_not_flagged_as_excess(self):
        ends = [date(2026, 3, 31), date(2025, 12, 31), date(2025, 9, 30), date(2025, 6, 30)]
        findings = audit_ttm_period(_fd(ends))
        assert not any(f.check == "ttm_quarters_excess" for f in findings)
