"""Recent corporate-action (M&A / large secondary) transition detection.

Pure, zero-I/O. Lives in ``primitives/`` (not ``compute/operators/``) so both the
data layer and the compute layer can reach it without a data↔compute cycle, the
same placement rationale as ``is_bank`` (ADR-0005 §2.2).

A company that has just closed a stock-funded acquisition (or a large secondary)
carries a TTM snapshot that mixes two share bases: point-in-time shares reflect the
post-deal combined entity, while trailing earnings were largely earned on the old,
smaller share count (plus a charge-laden stub quarter). Every per-share / return
metric built off that TTM snapshot — DDM growth ``g = ROE×(1−payout)``, comps EPS,
ROE — is then understated, producing a spuriously bearish valuation the market and
sell-side (pricing the pro-forma entity) do not share. The right response is NOT to
reconstruct a pro-forma value here — the reported book is also goodwill-inflated, so
ROE and ROTCE diverge and a clean per-share value needs the residual-income model —
but to RECOGNISE the transition so the synthesis degrades gracefully (withhold the
poisoned point, hold the verdict neutral, surface the reason).

Signal: the current diluted share count materially exceeds the most recent annual
weighted-average diluted count, implied as ``net_income / EPS`` for the latest year
with positive earnings (the stable pre-disruption baseline). Goodwill only ever
grows from acquisitions and never revalues up under GAAP, so a goodwill jump is the
most *specific* M&A signal — but the share-count break is the more *direct* measure
of the per-share poison and needs no extra balance-sheet plumbing, so it is the
primary signal here. (Gap: an all-cash acquisition lifts goodwill without issuing
shares and would be missed; its per-share metrics are not share-mismatch-poisoned,
only goodwill-inflated — left to the residual-income work.)

Live-validated 2026-06: FITB (Comerica) and HBAN both read ≈1.27× their pre-deal
baseline; every non-merger control — including heavy buyers-back, whose current
count sits BELOW baseline — reads ≤1.00×, so the threshold has wide margin.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

# A 15% jump in the diluted share count over ~a year is not organic (stock comp /
# ATM issuance runs ≲5%/yr); it is a transformative stock-funded acquisition or a
# large secondary. The live basket separates cleanly here — mergers ≈1.27×, every
# non-merger ≤1.00× — so the line has comfortable margin on both sides.
MNA_SHARE_JUMP_THRESHOLD: Final[float] = 1.15


def detect_mna_transition(
    current_shares: float | None,
    annual_net_income: Sequence[float],
    annual_eps: Sequence[float],
    *,
    threshold: float = MNA_SHARE_JUMP_THRESHOLD,
) -> bool:
    """True when current shares materially exceed the most recent annual diluted
    baseline — the signature of a just-closed stock acquisition / large secondary
    whose TTM per-share metrics are not yet representative of the combined entity.

    ``annual_net_income`` / ``annual_eps`` are parallel, oldest→newest (the
    ``HistoricalMetrics`` convention). The baseline is the most recent year with
    BOTH net income and EPS positive — implied diluted shares = net_income / EPS;
    a loss year is skipped so a one-off negative EPS cannot poison the divisor.
    Returns False when no clean baseline or share count is available (graceful: no
    false gate where the data can't support one).
    """
    if current_shares is None or current_shares <= 0:
        return False
    for ni, eps in zip(reversed(list(annual_net_income)), reversed(list(annual_eps))):
        if ni > 0 and eps > 0:
            baseline_shares = ni / eps
            if baseline_shares > 0:
                return current_shares / baseline_shares > threshold
    return False
