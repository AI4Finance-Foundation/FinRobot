"""Multi-method valuation synthesis.

What this code does that raw LLM cannot: deterministic confidence-weighted
average across valuation methods. Same inputs always produce same result.
"""

from __future__ import annotations

import logging
import statistics

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
_MARKET_DIVERGENCE_RATIO_K = 4.0


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

    if not reliable:
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
        valuation_ratio > _MARKET_DIVERGENCE_RATIO_K
        or valuation_ratio < 1.0 / _MARKET_DIVERGENCE_RATIO_K
    ):
        reliable = False
        synthesis_warnings.append(
            f"Weighted target ${weighted_price:.2f} is UNRELIABLE: it is "
            f"{valuation_ratio:.2g}x the ${current_price:.2f} market price (outside the "
            f"[{1.0 / _MARKET_DIVERGENCE_RATIO_K:.2g}x, {_MARKET_DIVERGENCE_RATIO_K:.2g}x] "
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
