"""Family-4 verifier: TTM period completeness / non-overlap.

A TTM snapshot is Σ of four consecutive quarters. If the provider's quarter set
overlaps (a restated quarter double-counted), gaps (a quarter missing), or is
short (<4 quarters), the TTM aggregate — and every ratio built on it (P/E,
EV/EBITDA, margins) plus the DCF growth fed from it — is silently wrong, and
code review cannot see it (the gate's founding defect class: provider drift).

DEFINITIONAL, not calibrated: a fiscal quarter is 13-14 weeks (≈91 days; 90-96
observed live across the basket, including KO's 52/53-week retail calendar). The
gap band below flags only the physically impossible, so a clean 4-quarter
sequence can never false-positive (zero-FP, design doc §5 family-4 "定义型边界").
"""

from __future__ import annotations

from finrobot.engine.models.financial import FinancialData
from finrobot.engine.models.numeric_claim import Finding

_EXPECTED_QUARTERS = 4
# A fiscal quarter is ~91 days. Two consecutive quarter-ends closer than this are
# not distinct quarters (a restatement double-counted); farther than this means a
# quarter is missing (≈182 in practice). The wide margin around the 90-96 live
# band guarantees no false positive on a genuine 4-quarter sequence.
_MIN_QUARTER_GAP_DAYS = 45
_MAX_QUARTER_GAP_DAYS = 135

_FIELD_KEY = "ttm_period"


def audit_ttm_period(fin: FinancialData) -> list[Finding]:
    ends = fin.ttm_quarter_ends
    if not ends:
        # yfinance / annual snapshots carry no per-quarter dates — abstain rather
        # than fabricate a verdict on data we don't have.
        return []

    # Newest-first as carried by the provider; sort descending to be order-robust.
    ordered = sorted(ends, reverse=True)
    findings: list[Finding] = []

    for newer, older in zip(ordered, ordered[1:]):
        gap = (newer - older).days
        if gap < _MIN_QUARTER_GAP_DAYS:
            findings.append(
                Finding(
                    field_key=_FIELD_KEY,
                    check="ttm_quarter_overlap",
                    severity="blocked_field",
                    evidence=(
                        f"{fin.ticker}: TTM quarter-ends {older.isoformat()} and "
                        f"{newer.isoformat()} are {gap}d apart (< {_MIN_QUARTER_GAP_DAYS}d) — "
                        f"not distinct quarters; a restated quarter is double-counted, so the "
                        f"trailing-twelve-month aggregate (and every ratio built on it) overstates."
                    ),
                )
            )
        elif gap > _MAX_QUARTER_GAP_DAYS:
            findings.append(
                Finding(
                    field_key=_FIELD_KEY,
                    check="ttm_quarter_gap",
                    severity="blocked_field",
                    evidence=(
                        f"{fin.ticker}: TTM quarter-ends {older.isoformat()} and "
                        f"{newer.isoformat()} are {gap}d apart (> {_MAX_QUARTER_GAP_DAYS}d) — "
                        f"a quarter is missing, so the trailing-twelve-month aggregate "
                        f"understates and every ratio built on it is wrong."
                    ),
                )
            )

    if len(ordered) < _EXPECTED_QUARTERS:
        findings.append(
            Finding(
                field_key=_FIELD_KEY,
                check="ttm_quarters_incomplete",
                severity="review",
                evidence=(
                    f"{fin.ticker}: TTM built from {len(ordered)} quarter(s), not "
                    f"{_EXPECTED_QUARTERS} — the trailing-twelve-month figure is incomplete "
                    f"(can be a recent IPO or provider lag); verify before relying on it."
                ),
            )
        )
    elif len(ordered) > _EXPECTED_QUARTERS:
        # The verifier's founding defect class cuts BOTH ways: five normally
        # spaced quarter-ends (a restatement shipping old+new rows side by
        # side) pass every pairwise gap check yet sum 15 months into the
        # "trailing twelve" — overstating TTM ~25% with zero warning. Counting
        # only the short side defended half the invariant.
        findings.append(
            Finding(
                field_key=_FIELD_KEY,
                check="ttm_quarters_excess",
                severity="blocked_field",
                evidence=(
                    f"{fin.ticker}: TTM built from {len(ordered)} quarter-ends, not "
                    f"{_EXPECTED_QUARTERS} — an extra period is summed into the "
                    f"trailing-twelve-month aggregate (provider restatement drift), "
                    f"overstating it and every ratio built on it."
                ),
            )
        )

    return findings
