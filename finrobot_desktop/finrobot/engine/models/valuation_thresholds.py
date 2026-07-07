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

# Method-vs-method corroboration span — the max(mid)/min(mid) ratio above which
# two or more valuation methods do NOT corroborate each other (orthogonal to the
# model-vs-market bands above, which compare the headline to the live price). With
# exactly two methods the median is always their midpoint, so a 2.57x disagreement
# averages into a meaningless midpoint that the median-deviation gate is blind to
# (the MSFT $189 DCF vs $487 comps bug). max/min is invariant to method count, so
# it trips on any pair > K. K=2.0: two methods that differ by more than 2x do not
# corroborate, full stop — no honest blended point exists.
#
# Lives in the leaf because it is consumed at the persist boundary and must speak
# the same calibrated language as the rest of the divergence bands:
#   · the persist-boundary output contract (``artifact/contract`` clause C1b)
#     re-checks the method span on the FINAL artifact — and is forbidden to import
#     ``compute/``. C1 (model-vs-market) is structurally blind to a target that
#     sits in-band against the market while its methods are 7x apart (the MU
#     0.69x-market-yet-DCF-7x-comps case); C1b is that backstop.
# (At synthesis time the confidence dial in ``valuation_synthesis`` now grades the
# call from method agreement with its OWN span thresholds — ``_DIAL_CORROBORATE_SPAN``
# / ``_DIAL_MILD_SPAN`` — rather than this binary 2x gate; the deleted ``reliable``
# flag used to re-export this constant.)
METHOD_CORROBORATION_SPAN_K = 2.0

# ── Re-rating dominance gate (P0-1.2, 2026-07-07, lead-signed K/M) ───────────
# A multiples method (comps_pe / self-band ev_ebitda) prices the target on the
# premise that its own multiple CONVERGES to the anchor (peer median / own 5y
# band). When that premise requires a large multiple shift AND those methods
# drag the corroborated blend away from the cash-flow (DCF) anchor, the blend's
# "high confidence" is really a bet on an unproven re-rating — the MSFT
# 2026-07-07 external-review case: dcf $451 / comps_pe $534 (1.38x re-rate) /
# ev_ebitda $632 (1.64x) slipped BOTH existing gates by a hair (span 1.40 vs
# 1.5, DCF median-deviation 27.3% vs 30%) and blended into a high-confidence
# +38% BUY whose own disclosures contradicted it. The gate caps confidence at
# medium and shows the DCF-only anchor alongside — it changes NO number, drops
# NO method, never withholds the point and never touches the verdict directly.
#
# 红线 (do NOT re-litigate): this is deliberately ORTHOGONAL to market distance.
# Two methods that agree far BELOW market (a corroborated high-confidence SELL)
# have a near-zero blend-vs-DCF displacement and MUST NOT be capped — the
# displacement condition (M), not the market gap, is what discriminates.
# Confidence-not-a-function-of-market-distance stays the standing principle.
#
# Calibration (EMPIRICAL VALIDATION replay over the stored basket, 2026-07-07):
# only MSFT lives on the corroborated-blend branch — AAPL (bimodal), KO
# (re-anchor), GOOGL/MU (divergent), JPM/BAC (RI band), TSM (single) are
# structurally out of the gate's scope — and MSFT reads ratios 1.38x/1.64x with
# an +18.4% blend displacement. K=1.3: a ±30% multiple shift is a broken
# premise, comfortably above the 0.25 pure-disclosure threshold
# (_RERATING_DISCLOSURE_THRESHOLD) and below the archetype's 1.38. M=0.15:
# catches the +18.4% archetype with margin while the corroborated-SELL /
# corroborated-deep-value red-line cases sit at |disp| ≈ 3-4%, an ~11pp buffer.
RERATING_GAP_RATIO_K = 1.3

# Blend-vs-cash-flow-anchor displacement (|blend/dcf − 1|) above which breaching
# multiples methods count as DRAGGING the headline (condition (b) of the gate —
# see RERATING_GAP_RATIO_K above for the full rationale and red line).
RERATING_ANCHOR_DISPLACEMENT_M = 0.15

# Sponsor equity-return hurdle, shared by the two LBO consumers that must speak
# the same bar (a leaf for the same reason as the constants above — the
# aggregator is forbidden to import compute/operators/lbo):
#   · ic_memo's IRR gate (recommendation forced to PASS below the hurdle), and
#   · valuation_aggregator's LBO ability-to-pay band, which discounts the
#     t+N exit equity back to today at this rate (PV = exit_equity/(1+r)^N).
#     Undiscounted exit equity is a FUTURE value — plotting it on the football
#     field next to PV methods (DCF) and the current price overstated the LBO
#     row ~2x over a 5y hold.
# 15% is the project's long-standing IC bar. [金融待核] Textbook sponsor
# hurdles run 20–25% (Rosenbaum & Pearl Ch.8); raising this lowers the
# ability-to-pay band and tightens the IC gate together — calibrate once, both
# consumers follow.
SPONSOR_IRR_HURDLE = 0.15

# Minimum (discount rate − terminal growth) spread for a FORWARD Gordon
# perpetuity. A 0.5% spread puts a 200× multiplier on the terminal cash flow —
# an astronomically levered point estimate, not a valuation (Damodaran: tg ≤
# risk-free, implying spread ≥ the equity premium). Shared by every forward
# Gordon consumer (calculate_dcf raise / sensitivity grid cell → None /
# Monte Carlo per-path clamp / calculate_ddm raise) so no path can publish a
# blowup another path refuses. Deliberately NOT applied to the reverse-DCF
# kernel (_price_for): the reverse direction's whole job is to report the
# absurd implied parameters the market price encodes (协议 §2), so its search
# domain must reach them.
MIN_GORDON_SPREAD = 0.015
