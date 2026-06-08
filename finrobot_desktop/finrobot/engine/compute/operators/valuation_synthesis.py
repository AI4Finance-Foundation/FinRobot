"""Multi-method valuation synthesis.

What this code does that raw LLM cannot: deterministic confidence-weighted
average across valuation methods. Same inputs always produce same result.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass

from finrobot.engine.models.financial import ValuationMethod, ValuationSynthesis

logger = logging.getLogger(__name__)

# Any method whose mid deviates from the cross-method median by more than this
# fraction is flagged in outlier_methods and a warning is appended.
_OUTLIER_THRESHOLD = 0.30

# When a method's mid deviates from the median by more than this (much wider
# than the soft outlier band), the methods fundamentally disagree: the
# confidence-weighted price is then just the midpoint of two estimates that
# don't corroborate each other, not a defensible target. The synthesis is
# flagged ``reliable=False`` so the pipeline refuses to publish a headline
# target/verdict — e.g. DCF and Comps each ~54% from their median must not
# ship a confident BUY/SELL.
_RELIABILITY_SPREAD_THRESHOLD = 0.50

# Pairwise-spread gate (catches what the median gate above is structurally blind
# to). With EXACTLY two methods the median is always their midpoint, so each
# method's deviation-from-median is (b−a)/(a+b) — which only crosses 50% once
# b > 3a. A 2.57x disagreement therefore sails through the median gate: DCF
# $189.65 vs comps_pe $487.31 averaged into a meaningless $306.59 midpoint and
# shipped a confident MSFT SELL (the 2026-06-05 bug). max(mid)/min(mid) is
# invariant to method count, so it trips on any pair that disagrees by > K
# regardless of how many methods there are. K=2.0: two valuation methods that
# differ by more than 2x do not corroborate, full stop — no honest midpoint
# exists, so the headline target/verdict is withheld. (Genuine ≤2x dispersion
# still publishes, flagged by the soft 30% outlier band.)
_RELIABILITY_RATIO_K = 2.0

# Model-vs-market circuit breaker. The spread threshold above only asks whether
# the methods agree with EACH OTHER — it is blind to the case where every method
# agrees while ALL of them sit far from the market price. That is the Amazon-1999
# / TSLA failure: a fundamentals DCF and auto-peer comps corroborate each other
# at ~$18 while the market prices ~$418 of option value (FSD / robotaxi / energy)
# that no cash-flow model captures. A point estimate 24x off the market is NOT a
# publishable target however internally consistent it is. When the model is this
# far outside its calibration range, flag ``reliable=False`` so the same
# data-health gate withholds the headline target/verdict.
#
# Gate on the RATIO fair_value / market_price, NOT abs(upside%). Upside% is
# log-asymmetric: a +75% upside is a 1.75x ratio, but a -75% "downside" is a
# 0.25x ratio (= 4x gap) — gating on abs(upside)>0.75 would trip the upside at
# 1.75x while only tripping the downside at 4x, i.e. trust an over-priced model
# far more readily than an under-priced one. The symmetric breaker is
# ratio > K  OR  ratio < 1/K. K=4 keeps the 0.25x downside floor (the original
# -75% choice, which caught the TSLA screenshot) and makes the upside symmetric
# to it: a model worth >4x the market and one worth <1/4x are equally "out of
# calibration" and equally deserve REVIEW — divergence MAGNITUDE matters, not
# direction. Genuine 2-3x over/undervaluation calls still publish. (K is the
# single tunable knob; drop to 3 for a stricter gate.)
MARKET_DIVERGENCE_RATIO_K = 4.0

# Single-method market-divergence circuit breaker — TIGHTER than the multi-method
# band above. A lone surviving method (DCF dropped out, only comps left) has NO
# internal cross-check: the market price is its ONLY second opinion. So it is held
# to the same 2x corroboration limit two methods must clear against each other
# (_RELIABILITY_RATIO_K) — a single method that disagrees with the market by > 2x
# does not corroborate, full stop, and its mid must not become a headline target.
#
# Why not reuse the 4x multi-method band: 4x is the budget for a *corroborated*
# point estimate (≥2 methods agree with each other, all sit far from market =
# market option value the models can't see). One uncorroborated method that lands
# 2-4x off the market is far more likely the model being wrong than the market
# being wrong — e.g. the MU 2026-06-07 artifact, where a lone comps_pe applied a
# peer GROWTH forward P/E (36.9x) to a memory cyclical's PEAK forward EPS ($58.9)
# and printed $2172 = 2.5x the $864 market, shipped as a confident +151% BUY.
SINGLE_METHOD_DIVERGENCE_RATIO_K = 2.0


def synthesize_valuations(
    methods: list[ValuationMethod], current_price: float
) -> ValuationSynthesis:
    """Synthesize multiple valuation methods into a single confidence-weighted estimate.

    Formula: weighted_price = Σ(mid_i × confidence_i) / Σ(confidence_i)
             upside_downside = (weighted_price - current_price) / current_price

    When fewer than 2 methods are present, ``weighted_price`` and
    ``upside_downside`` are set to ``None`` — a single-method result has no
    cross-check and MUST NOT be surfaced as a meaningful weighted average.

    Cross-method spread check (≥2 methods): any method whose mid deviates from
    the median of all mids by > 30% is added to ``outlier_methods`` and a
    human-readable entry is appended to ``warnings``.

    Reliability gate (≥2 methods): ``reliable`` is set False when the methods'
    mids span more than ``_RELIABILITY_RATIO_K``x (max/min — invariant to method
    count, so a 2-method disagreement can't hide behind its own midpoint median),
    or any single method deviates > 50% from the median, or the weighted target
    sits outside the [0.25x, 4x] market-price band. Any trip withholds the
    headline target/verdict downstream.

    Args:
        methods: List of valuation method results, each with a confidence weight.
        current_price: Current market price to compare against.

    Returns:
        ValuationSynthesis. ``weighted_price`` is None when len(methods) < 2.

    Raises:
        ValueError: If methods is empty or total confidence is not positive.
    """
    if not methods:
        raise ValueError("At least one valuation method is required")
    total_confidence = sum(m.confidence for m in methods)
    if total_confidence <= 0:
        raise ValueError("Total confidence must be positive")

    if len(methods) < 2:
        logger.warning(
            "synthesize_valuations: single-method valuation, no cross-check — "
            "weighted_price set to None (method: %s)",
            methods[0].name,
        )
        return ValuationSynthesis(
            methods=methods,
            weighted_price=None,
            current_price=current_price,
            upside_downside=None,
        )

    weighted_price = sum(m.mid * m.confidence for m in methods) / total_confidence
    upside_downside = (weighted_price - current_price) / current_price

    # --- Cross-method spread check ---
    mids = [m.mid for m in methods]
    median_mid = statistics.median(mids)

    outlier_methods: list[str] = []
    synthesis_warnings: list[str] = []
    reliable = True

    if median_mid != 0:
        for m in methods:
            deviation = abs(m.mid - median_mid) / abs(median_mid)
            if deviation > _OUTLIER_THRESHOLD:
                outlier_methods.append(m.name)
                synthesis_warnings.append(
                    f"Method spread warning: {m.name} mid ${m.mid:.2f} deviates "
                    f"{deviation:.0%} from median ${median_mid:.2f}"
                )
                logger.warning(
                    "synthesize_valuations: %s mid $%.2f deviates %.0f%% from "
                    "cross-method median $%.2f — flagged as outlier",
                    m.name,
                    m.mid,
                    deviation * 100,
                    median_mid,
                )
            if deviation > _RELIABILITY_SPREAD_THRESHOLD:
                reliable = False
    else:
        # All-zero/negative median: the methods can't be cross-checked at all.
        reliable = False

    # Pairwise-spread gate — invariant to method count, so it catches the
    # 2-method blind spot the median gate above cannot (see _RELIABILITY_RATIO_K).
    lo = min(mids)
    hi = max(mids)
    ratio_tripped = lo > 0 and hi / lo > _RELIABILITY_RATIO_K
    if ratio_tripped:
        reliable = False
        synthesis_warnings.append(
            f"Weighted target ${weighted_price:.2f} is UNRELIABLE: the methods span "
            f"${lo:.2f}–${hi:.2f} ({hi / lo:.2g}x, over the {_RELIABILITY_RATIO_K:.2g}x "
            "corroboration limit) — they do not agree, so the confidence-weighted "
            "midpoint is not a defensible target. Headline target/verdict withheld."
        )
    elif not reliable:
        synthesis_warnings.append(
            f"Weighted target ${weighted_price:.2f} is UNRELIABLE: at least one "
            f"method deviates >{_RELIABILITY_SPREAD_THRESHOLD:.0%} from the "
            f"${median_mid:.2f} median — methods do not corroborate. Headline "
            "target/verdict must be withheld pending review."
        )

    # --- Model-vs-market divergence check (orthogonal to the spread check) ---
    # Trips even when the methods agree with each other but all sit far from the
    # market — the blind spot the spread check above cannot see. Gated on the
    # ratio (symmetric in log-space), not abs(upside%). current_price > 0 is
    # guaranteed by upside_downside being computed above.
    valuation_ratio = weighted_price / current_price
    if (
        valuation_ratio > MARKET_DIVERGENCE_RATIO_K
        or valuation_ratio < 1.0 / MARKET_DIVERGENCE_RATIO_K
    ):
        reliable = False
        synthesis_warnings.append(
            f"Weighted target ${weighted_price:.2f} is UNRELIABLE: it is "
            f"{valuation_ratio:.2g}x the ${current_price:.2f} market price (outside the "
            f"[{1.0 / MARKET_DIVERGENCE_RATIO_K:.2g}x, {MARKET_DIVERGENCE_RATIO_K:.2g}x] "
            "calibration band). The valuation methods corroborate each other but sit far "
            "outside the market — the market is pricing option value (e.g. new business "
            "lines / growth optionality) that cash-flow and relative models do not "
            "capture. The model is outside its calibration range; a fundamentals point "
            "target must be withheld pending review."
        )

    return ValuationSynthesis(
        methods=methods,
        weighted_price=weighted_price,
        current_price=current_price,
        upside_downside=upside_downside,
        outlier_methods=outlier_methods,
        warnings=synthesis_warnings,
        reliable=reliable,
    )


# ── Recommendation thresholds ──────────────────────────────────────────────
# Applied to ValuationSynthesis.upside_downside. Source: sell-side equity-
# research convention (±15% bands around fair value are the standard Buy / Hold /
# Sell separators on the Street). They travel into both the LLM prompt (so the
# narrative is consistent) and the post-run override (so the contract holds even
# if the LLM drifts).
VERDICT_BUY_THRESHOLD = 0.15
VERDICT_SELL_THRESHOLD = -0.15


def verdict_from_upside(upside: float) -> str:
    """Deterministic Buy/Hold/Sell from synthesis upside vs current price."""
    if upside >= VERDICT_BUY_THRESHOLD:
        return "BUY"
    if upside <= VERDICT_SELL_THRESHOLD:
        return "SELL"
    return "HOLD"


@dataclass(frozen=True)
class CanonicalThesis:
    """The deterministic headline a thesis MUST narrate, never negotiate.

    Resolved purely from a ValuationSynthesis — no I/O, no LLM. This is the
    enforcement point of the CLAUDE.md contract "LLM 永远不产出无法追溯到函数
    调用的数字": the equity-research pipeline injects these values into the
    synthesis prompt AND force-overrides the LLM's fields with them post-run, so
    even an uncooperative model cannot desync the published target/verdict.

    Fields:
        target:      headline price target, or None when withheld (gate tripped
                     / no usable synthesis).
        verdict:     "BUY"/"HOLD"/"SELL" from the upside bands, "REVIEW" when a
                     data-health gate withholds a directional call, or None when
                     no synthesis resolved.
        basis:       human-readable derivation string (cited in price_target_basis).
        upside:      implied upside vs current price, or None.
        gate_failed: True when a data-health gate tripped (target withheld,
                     verdict forced to REVIEW).
    """

    target: float | None
    verdict: str | None
    basis: str | None
    upside: float | None
    gate_failed: bool


def resolve_canonical_thesis(vs: object, ticker: str) -> CanonicalThesis:
    """Resolve the deterministic headline target/verdict from a synthesis.

    Pure: depends only on ``vs`` (the "valuation_synthesis" structured-context
    value — any non-ValuationSynthesis input yields an empty CanonicalThesis).
    ``ticker`` is used only for log attribution. No I/O, no LLM — this is the
    code the LLM's headline numbers are force-reconciled against.

    Branches (in contract order):
      - reliability gate tripped (``vs.reliable`` False) → REVIEW, target withheld
      - ≥2 methods converge (``weighted_price`` set)     → weighted target + verdict
      - single method, mid in calibration band           → that mid as target
      - single method, mid out of band                   → REVIEW, target withheld
      - otherwise                                        → empty (nothing usable)
    """
    canonical_target: float | None = None
    canonical_basis: str | None = None
    canonical_verdict: str | None = None
    canonical_upside: float | None = None
    # Data-health gate: when the synthesis flags itself unreliable, we publish
    # NO headline target/verdict. Two orthogonal triggers (see
    # ValuationSynthesis.reliable): (a) methods deviate > 50% from each other
    # (the 2026-05-28 TSLA artifact: "DCF deviates 54% from median"), or (b) the
    # methods agree with each other but the weighted target sits > 75% off the
    # market price (the 2026-06-05 TSLA screenshot: DCF $11.80 + Comps $25.54
    # corroborate at $17.20 yet land 96% below the $418 market — the market
    # prices option value the cash-flow models can't see). REVIEW is the honest
    # verdict; the narrative LLM is told to explain the data-health gap instead
    # of inventing conviction.
    gate_failed = isinstance(vs, ValuationSynthesis) and not vs.reliable
    if gate_failed:
        canonical_verdict = "REVIEW"
        canonical_target = None
        assert isinstance(vs, ValuationSynthesis)
        spread_detail = "; ".join(vs.warnings) if vs.warnings else "method spread exceeded gate"
        canonical_basis = f"DATA-HEALTH GATE: target withheld. {spread_detail}"
        logger.warning(
            "Equity-research data-health gate TRIPPED — verdict forced to REVIEW, "
            "target withheld. Detail: %s",
            spread_detail,
        )
    elif isinstance(vs, ValuationSynthesis) and vs.weighted_price is not None:
        # Only inject an authoritative target when ≥2 methods converge.
        # Single-method synthesis has weighted_price=None (no cross-check).
        canonical_target = round(vs.weighted_price, 2)
        canonical_upside = vs.upside_downside
        canonical_verdict = (
            verdict_from_upside(canonical_upside) if canonical_upside is not None else None
        )
        method_breakdown = ", ".join(
            f"{m.name}=${m.mid:.2f}(wt={m.confidence:.2f})" for m in vs.methods
        )
        canonical_basis = (
            f"Method-weighted average of {len(vs.methods)} valuation methods "
            f"(wt = data-quality weight, NOT prediction accuracy): "
            f"{method_breakdown} → ${canonical_target:.2f}"
        )
    elif isinstance(vs, ValuationSynthesis) and vs.methods and vs.current_price > 0:
        # Single-method synthesis (weighted_price=None — no cross-check). The LLM
        # must NOT be left free to invent a headline number here: the 2026-06-05
        # TSLA live artifact fell through this branch when comps died (all-EV
        # peer set, P/E n=0 of 6) and the LLM stamped "SELL $20.38" on a 0.05x
        # model/market ratio — bypassing every data-health gate. Gate the lone
        # method's mid against the market — its ONLY available cross-check — using
        # the TIGHTER single-method band (2x corroboration limit, not the 4x
        # multi-method band; see SINGLE_METHOD_DIVERGENCE_RATIO_K):
        #   · in-band  → publish it as the canonical target with an explicit
        #     single-method / no-cross-check caveat (banks legitimately run
        #     comps-only; forcing REVIEW would end coverage of every financial)
        #   · out-of-band → trip the data-health gate: REVIEW, target withheld,
        #     narrative explains via the market-implied check. This is the gate
        #     the MU 2026-06-07 comps_pe ($2172 = 2.5x market) must trip.
        only = vs.methods[0]
        ratio = only.mid / vs.current_price
        if (
            ratio > SINGLE_METHOD_DIVERGENCE_RATIO_K
            or ratio < 1.0 / SINGLE_METHOD_DIVERGENCE_RATIO_K
        ):
            gate_failed = True
            canonical_verdict = "REVIEW"
            canonical_target = None
            canonical_basis = (
                f"DATA-HEALTH GATE: target withheld. Only one valuation method "
                f"({only.name}) resolved — no cross-check — and its mid "
                f"${only.mid:.2f} is {ratio:.2g}x the ${vs.current_price:.2f} market "
                f"price, outside the [{1.0 / SINGLE_METHOD_DIVERGENCE_RATIO_K:.2g}x, "
                f"{SINGLE_METHOD_DIVERGENCE_RATIO_K:.2g}x] single-method corroboration "
                f"band (the market is its only cross-check). A single uncorroborated "
                f"method this far from the market must not set a headline target/verdict."
            )
            logger.warning(
                "Equity-research single-method gate TRIPPED for %s — %s mid $%.2f "
                "is %.2gx market $%.2f. Verdict forced to REVIEW, target withheld.",
                ticker,
                only.name,
                only.mid,
                ratio,
                vs.current_price,
            )
        else:
            canonical_target = round(only.mid, 2)
            canonical_upside = (only.mid - vs.current_price) / vs.current_price
            canonical_verdict = verdict_from_upside(canonical_upside)
            canonical_basis = (
                f"Single valuation method ({only.name}=${only.mid:.2f}, "
                f"wt={only.confidence:.2f}) — no cross-check available; treat with "
                f"wider uncertainty than a multi-method synthesis."
            )
    elif isinstance(vs, ValuationSynthesis):
        logger.warning(
            "ValuationSynthesis has %d method(s), current_price=%s — no authoritative "
            "price target injected",
            len(vs.methods),
            vs.current_price,
        )
    return CanonicalThesis(
        target=canonical_target,
        verdict=canonical_verdict,
        basis=canonical_basis,
        upside=canonical_upside,
        gate_failed=gate_failed,
    )
