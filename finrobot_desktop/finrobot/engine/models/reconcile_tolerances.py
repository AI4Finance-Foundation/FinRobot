"""Shared reconciliation tolerance — leaf constant (ADR-0005 leaf layer,
importable by compute / pipeline / artifact alike, same as ``numeric_claim`` and
``valuation_thresholds``).

The relative tolerance below decides when two dollar amounts that *should* be the
same number (a prose $-amount vs the canonical weighted target; a basis
conclusion amount vs the headline price target) are close enough to be the same
versus a real contradiction. It lives here — not inside
``pipelines/equity_research`` — because two layers consume the SAME calibrated
value and must speak the same language:

  · the upstream narrative reconcile (``equity_research._reconcile_narrative_targets``)
    which rewrites a drifting prose $-amount back to the canonical token, and
  · the end-to-end output contract (``artifact/contract``, clause C3) which
    re-checks that the basis conclusion amount equals the headline at the persist
    boundary — and is forbidden to import ``pipelines/`` (ADR: the contract stays
    a dumb end-to-end invariant; it may import a calibrated constant from a leaf
    but never the pipeline that computed the result).

Kept tight (1%) so a rounded restatement like "$276" against $276.43 passes, but
a contradicting headline like "$280" against $276.43 is caught — the exact
table-vs-prose desync these guards exist to neutralize.
"""

from __future__ import annotations

# Relative tolerance for "these two dollar amounts are the same number".
NARRATIVE_DRIFT_TOLERANCE = 0.01

# Report-drift approximation band: an unmatched narrative amount within this
# relative distance of SOME numeric leaf is an LLM approximation ("roughly
# $400B" against a $391B leaf, 2.3%) — kept in prose, flagged for review.
# Beyond it the amount is near NOTHING the artifact computed → redacted as a
# high-confidence fabrication/material error. Calibrated 2026-07-02 on all 51
# stored artifacts (627 amounts, 99 unmatched@1%): gaps ≤10% read as roundings
# (1.4%/2.8%/4.2%…), gaps >10% were materially wrong numbers (JPM DDM
# "$1.58 trillion" 15% off, "$140.95B" 22.5% off, MU LBO "$-31892M" 102% off)
# — a visible break, not a smooth continuum.
NARRATIVE_APPROXIMATION_BAND = 0.10
