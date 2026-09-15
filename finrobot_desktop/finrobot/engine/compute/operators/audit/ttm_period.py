"""Family-4 verifier: TTM period completeness / non-overlap.

A TTM snapshot is Σ of consecutive periods covering twelve months — FOUR quarters
for a quarterly filer, or TWO half-years for a semi-annual one (UL and many UK /
EU / AU issuers). If the provider's period set overlaps (a restated period double-
counted), gaps (a period missing), or has the wrong count for its cadence, the TTM
aggregate — and every ratio built on it (P/E, EV/EBITDA, margins) plus the DCF
growth fed from it — is silently wrong, and code review cannot see it (the gate's
founding defect class: provider drift, e.g. the semi-annual 2× — UL TTM ~127B vs a
~50B fiscal year — that summing four 6-month rows produced before the provider's
window went cadence-aware).

DEFINITIONAL, not calibrated: a fiscal quarter is 13-14 weeks (≈91 days; 90-96
observed live, incl. KO's 52/53-week retail calendar); a fiscal half is ≈182 days.
The cadence is read from the inter-period spacing itself, so a clean 4-quarter OR
2-half-year sequence never false-positives, while a ~182d gap sitting AMONG ~91d
siblings (a quarterly filer with one quarter missing) still flags.
"""

from __future__ import annotations

from datetime import date

from finrobot.engine.models.financial import FinancialData
from finrobot.engine.models.numeric_claim import Finding

# A fiscal quarter is ~91 days, a fiscal half ~182. Two consecutive period-ends
# closer than the quarterly floor are not distinct periods (a restatement double-
# counted). The two cadence bands are disjoint (a ~136-149d "dead-zone" gap belongs
# to neither and is flagged as a missing period), each wide enough that the live
# 90-96d / 181-184d spreads never false-positive.
_MIN_QUARTER_GAP_DAYS = 45
_MAX_QUARTER_GAP_DAYS = 135
_MIN_SEMIANNUAL_GAP_DAYS = 150
_MAX_SEMIANNUAL_GAP_DAYS = 225

_EXPECTED_QUARTERS = 4
_EXPECTED_SEMIANNUAL_PERIODS = 2

_FIELD_KEY = "ttm_period"


def _classify_cadence(non_overlap_gaps: list[int]) -> str:
    """Report the filing cadence implied by the (non-overlap) inter-period gaps.

    ``"semiannual"`` only when EVERY gap is ~182d — a single ~91d gap (or a mixed
    set: a quarterly filer with one quarter missing → a lone ~182d gap among ~91d
    siblings) stays ``"quarterly"`` so the anomalous gap is still caught and the
    count is checked against 4, never silently halved to 2.
    """
    if non_overlap_gaps and all(
        _MIN_SEMIANNUAL_GAP_DAYS <= g <= _MAX_SEMIANNUAL_GAP_DAYS for g in non_overlap_gaps
    ):
        return "semiannual"
    return "quarterly"


def audit_ttm_period(fin: FinancialData) -> list[Finding]:
    ends: list[date] = fin.ttm_quarter_ends
    if not ends:
        # yfinance / annual snapshots carry no per-period dates — abstain rather
        # than fabricate a verdict on data we don't have.
        return []

    # Newest-first as carried by the provider; sort descending to be order-robust.
    ordered = sorted(ends, reverse=True)
    findings: list[Finding] = []

    gaps = [(newer - older).days for newer, older in zip(ordered, ordered[1:])]
    cadence = _classify_cadence([g for g in gaps if g >= _MIN_QUARTER_GAP_DAYS])
    period_word = "half-year" if cadence == "semiannual" else "quarter"
    expected = _EXPECTED_SEMIANNUAL_PERIODS if cadence == "semiannual" else _EXPECTED_QUARTERS
    legit_max = _MAX_SEMIANNUAL_GAP_DAYS if cadence == "semiannual" else _MAX_QUARTER_GAP_DAYS

    for newer, older in zip(ordered, ordered[1:]):
        gap = (newer - older).days
        if gap < _MIN_QUARTER_GAP_DAYS:
            findings.append(
                Finding(
                    field_key=_FIELD_KEY,
                    check="ttm_quarter_overlap",
                    severity="blocked_field",
                    evidence=(
                        f"{fin.ticker}: TTM period-ends {older.isoformat()} and "
                        f"{newer.isoformat()} are {gap}d apart (< {_MIN_QUARTER_GAP_DAYS}d) — "
                        f"not distinct periods; a restated period is double-counted, so the "
                        f"trailing-twelve-month aggregate (and every ratio built on it) overstates."
                    ),
                )
            )
        elif gap > legit_max:
            findings.append(
                Finding(
                    field_key=_FIELD_KEY,
                    check="ttm_quarter_gap",
                    severity="blocked_field",
                    evidence=(
                        f"{fin.ticker}: TTM {period_word}-ends {older.isoformat()} and "
                        f"{newer.isoformat()} are {gap}d apart (> {legit_max}d for a "
                        f"{cadence} filer) — a {period_word} is missing, so the "
                        f"trailing-twelve-month aggregate understates and every ratio built "
                        f"on it is wrong."
                    ),
                )
            )

    if len(ordered) < expected:
        findings.append(
            Finding(
                field_key=_FIELD_KEY,
                check="ttm_quarters_incomplete",
                severity="review",
                evidence=(
                    f"{fin.ticker}: TTM built from {len(ordered)} {period_word}(s), not "
                    f"{expected} — the trailing-twelve-month figure is incomplete "
                    f"(can be a recent IPO or provider lag); verify before relying on it."
                ),
            )
        )
    elif len(ordered) > expected:
        # The verifier's founding defect class cuts BOTH ways: an extra normally
        # spaced period (a restatement shipping old+new rows side by side) passes
        # every pairwise gap check yet sums >12 months into the "trailing twelve"
        # (five quarters ≈ 15 months, ~25% overstated). Counting only the short
        # side defended half the invariant.
        findings.append(
            Finding(
                field_key=_FIELD_KEY,
                check="ttm_quarters_excess",
                severity="blocked_field",
                evidence=(
                    f"{fin.ticker}: TTM built from {len(ordered)} {period_word}-ends, not "
                    f"{expected} — an extra period is summed into the trailing-twelve-month "
                    f"aggregate (provider restatement drift), overstating it and every ratio "
                    f"built on it."
                ),
            )
        )

    return findings
