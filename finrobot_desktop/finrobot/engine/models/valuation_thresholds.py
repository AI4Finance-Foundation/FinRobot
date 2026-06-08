"""Calibrated model-vs-market divergence bands — leaf constants (ADR-0005 leaf
layer, importable by compute / pipeline / artifact alike, same as numeric_claim).

These two are the *public* divergence thresholds: a fair-value-to-market ratio
outside the band means the valuation is out of calibration and its headline
target must not ship as a confident BUY/SELL. They live here (not in
``compute/operators/valuation_synthesis``) because two layers consume the SAME
calibrated value and must speak the same language:

  · the upstream data-health gate (``valuation_synthesis``) which produces the
    REVIEW decision at synthesis time, and
  · the end-to-end output contract (``artifact/contract``, clause C1) which
    re-checks the *result* at the persist boundary — and is forbidden to import
    ``compute/`` (ADR: contract stays a dumb end-to-end invariant; it may import
    calibrated constants from a leaf but never re-run the compute layer).

A calibrated threshold shared across layers is exactly the kind of value that
belongs in a leaf both can depend on without a cycle (the ``numeric_claim``
precedent). The private spread/reliability internals (``_RELIABILITY_*``) stay
inside ``valuation_synthesis`` — they are not consumed across the boundary.
"""

from __future__ import annotations

# Model-vs-market circuit breaker (MULTI-method, corroborated point estimate).
# Asks whether the confidence-weighted target sits within a sane multiple of the
# market price. Blind spot it covers: every method agreeing with EACH OTHER while
# ALL of them sit far from market — the Amazon-1999 / TSLA case where a
# fundamentals DCF and auto-peer comps corroborate at ~$18 while the market
# prices ~$418 of option value (FSD / robotaxi) that no cash-flow model captures.
# A point estimate 24x off the market is not a publishable target however
# internally consistent it is.
#
# Gate on the RATIO fair_value / market_price (ratio > K OR ratio < 1/K), NOT
# abs(upside%): upside% is log-asymmetric (a +75% call is 1.75x, a −75% call is
# 0.25x = a 4x gap), so gating on abs(upside) would trust over-priced models far
# more readily than under-priced ones. K=4 keeps the 0.25x downside floor (the
# original −75% choice that caught the TSLA screenshot) and makes the upside
# symmetric to it. Genuine 2–3x over/undervaluation calls still publish. (K is
# the single tunable knob; drop to 3 for a stricter gate.)
MARKET_DIVERGENCE_RATIO_K = 4.0

# Single-method market-divergence circuit breaker — TIGHTER than the multi-method
# band above. A lone surviving method (DCF dropped out, only comps left) has NO
# internal cross-check: the market price is its ONLY second opinion. So it is held
# to the same 2x corroboration limit two methods must clear against each other —
# a single method that disagrees with the market by > 2x does not corroborate,
# full stop, and its mid must not become a headline target.
#
# Why not reuse the 4x multi-method band: 4x is the budget for a *corroborated*
# point estimate (≥2 methods agree with each other, all sit far from market =
# market option value the models can't see). One uncorroborated method that lands
# 2–4x off the market is far more likely the model being wrong than the market
# being wrong — e.g. the MU 2026-06-07 artifact, where a lone comps_pe applied a
# peer GROWTH forward P/E (36.9x) to a memory cyclical's PEAK forward EPS ($58.9)
# and printed $2172 = 2.5x the $864 market, shipped as a confident +151% BUY.
SINGLE_METHOD_DIVERGENCE_RATIO_K = 2.0
