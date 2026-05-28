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
# than the soft outlier band), the methods fundamentally disagree and the
# confidence-weighted price is no longer a defensible target — it's just the
# midpoint of two estimates that don't corroborate each other. The synthesis
# is flagged ``reliable=False`` so the pipeline can refuse to publish a
# headline target/verdict. TSLA 2026-05-28: DCF $5.88 vs Comps $19.54 both
# deviated 54% from the $12.71 median, yet the artifact shipped a confident
# SELL @ $11.25. This threshold is the gate that stops that.
_RELIABILITY_SPREAD_THRESHOLD = 0.50


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

    return ValuationSynthesis(
        methods=methods,
        weighted_price=weighted_price,
        current_price=current_price,
        upside_downside=upside_downside,
        outlier_methods=outlier_methods,
        warnings=synthesis_warnings,
        reliable=reliable,
    )
