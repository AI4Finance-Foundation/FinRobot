"""Multi-method valuation synthesis.

What this code does that raw LLM cannot: deterministic confidence-weighted
average across valuation methods. Same inputs always produce same result.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from typing import Literal

from finrobot.engine.models.financial import ValuationMethod, ValuationSynthesis
from finrobot.engine.models.valuation_thresholds import (
    MARKET_DIVERGENCE_RATIO_K,
    METHOD_CORROBORATION_SPAN_K,
    SINGLE_METHOD_DIVERGENCE_RATIO_K,
)

logger = logging.getLogger(__name__)

# Any method whose mid deviates from the cross-method median by more than this
# fraction is flagged in outlier_methods and a soft cross-method spread warning
# is appended (disclosure only — it never withholds the call; the confidence
# dial below grades the call from method agreement).
_OUTLIER_THRESHOLD = 0.30

# MARKET_DIVERGENCE_RATIO_K (4.0, multi-method), SINGLE_METHOD_DIVERGENCE_RATIO_K
# (2.0, lone surviving method) and METHOD_CORROBORATION_SPAN_K (2.0, method-vs-method
# span) are the divergence bands — imported above from engine/models/valuation_thresholds
# (leaf). They live in the leaf because the persist-boundary output contract
# (artifact/contract clauses C1/C1b) re-checks the same bands on the final artifact
# and is forbidden to import compute/. The full calibration rationale (why 4x for a
# corroborated estimate, why 2x for an uncorroborated lone method — the TSLA
# option-value and MU $2172 cases) lives with the constants there. The gate that
# fires on these bands is the confidence dial below (_confidence_dial): out-of-band
# → cap the tier and, when extreme, withhold the POINT (valuation_withheld) while the
# directional verdict still ships.


# ── Confidence dial (REVIEW → graded-call redesign, ADR 估值优雅降级) ─────────
# The dial NEVER withholds the directional verdict — uncertainty only (a) lowers
# the confidence tier, (b) widens the target band, and (c) for a point that could
# only be fabricated, withholds the POINT (valuation_withheld) while the verdict
# still ships from the market-implied read. Spread → tier is by method AGREEMENT,
# not market distance (KO's two-methods-agree-but-rich stays high); market distance
# only caps the tier when the model/market ratio leaves the [0.25x, 4x] calibration
# band (the option-value regime). Thresholds calibrated against the full basket
# (MU/AAPL/KO/NVDA/TSLA/RIVN/F) — see scripts/probe_review_map + dial validation.
_DIAL_CORROBORATE_SPAN = 1.5  # max/min ≤ → methods agree → blend + high tier
_DIAL_MILD_SPAN = 3.0  # max/min ≤ → mild divergence → medium; above → low
_DIAL_SINGLE_BAND_FRAC = 0.25  # single-method (no cross-check) range half-width
ConfidenceTier = Literal["very_low", "low", "medium", "high"]
_TIER_ORDER: tuple[ConfidenceTier, ...] = ("very_low", "low", "medium", "high")


def _floor_tier(a: ConfidenceTier, b: ConfidenceTier) -> ConfidenceTier:
    """The lower (more conservative) of two confidence tiers."""
    return a if _TIER_ORDER.index(a) <= _TIER_ORDER.index(b) else b


def _select_anchor(methods: list[ValuationMethod], cyclical: bool) -> ValuationMethod | None:
    """Comparability anchor for a divergent method set (sell-side convention).

    Cyclical / unique business → DCF (book/cash-flow is cycle-stable, unlike a
    trough/peak-EPS multiple). Rich peer set (comps present) on a non-cyclical →
    comps. Never a blended midpoint of divergent methods (that prints a number no
    method produced). None only when neither DCF nor comps is present.
    """
    dcf = next((m for m in methods if m.name == "dcf"), None)
    comps = [m for m in methods if m.name.startswith("comps")]
    if cyclical and dcf is not None:
        return dcf
    if comps:
        by_name = {m.name: m for m in comps}
        return by_name.get("comps_pe") or by_name.get("comps_pb") or comps[0]
    return dcf


def _confidence_dial(
    methods: list[ValuationMethod], current_price: float, cyclical: bool
) -> tuple[ConfidenceTier, str | None, float | None, float | None, bool, str | None]:
    """Return (confidence, anchor_method, target_low, target_high, withheld, note).

    Pure. Encodes the graded-call rules; the verdict/target themselves are resolved
    downstream from these fields (resolve_canonical_thesis). ``methods`` is non-empty.
    """
    mids = [m.mid for m in methods]
    lo, hi = min(mids), max(mids)

    # Single method: no cross-check. In-band → medium with a wide band; wildly
    # off-market → the only point we could give is the market price in costume, so
    # withhold the POINT (verdict still ships from the market-implied read).
    if len(methods) == 1:
        only = methods[0]
        ratio = only.mid / current_price if current_price > 0 else float("inf")
        band = abs(only.mid) * _DIAL_SINGLE_BAND_FRAC
        if 1.0 / SINGLE_METHOD_DIVERGENCE_RATIO_K <= ratio <= SINGLE_METHOD_DIVERGENCE_RATIO_K:
            return (
                "medium",
                None,
                only.mid - band,
                only.mid + band,
                False,
                f"single method {only.name} with no cross-validation — band widened, confidence medium.",
            )
        # Off the single-method calibration band: withhold the POINT (no false-precise
        # headline stamped on a lone, far-from-market method) — but STILL ship the band.
        # Contract ②: 单方法/估值远离市价 → 给区间、标低置信、不撤回(给基本面底 + 市价 gap),
        # never blank a field. This mirrors the multi-method extreme-withhold path below,
        # which likewise returns lo/hi while withholding the point — the two withhold paths
        # must be symmetric (a lone method is not LESS deserving of a visible range).
        return (
            "very_low",
            None,
            only.mid - band,
            only.mid + band,
            True,
            f"single method {only.name} ${only.mid:.0f} is {ratio:.2g}x the market price, outside the "
            f"[{1.0 / SINGLE_METHOD_DIVERGENCE_RATIO_K:.2g}x,"
            f"{SINGLE_METHOD_DIVERGENCE_RATIO_K:.0f}x] single-method calibration band — point target withheld (avoid stamping "
            f"false precision on a lone far-from-market method); the band still provides a fundamental floor, with direction taken from the market implied.",
        )

    # ≥2 methods: tier from inter-method agreement (NOT market distance).
    span = hi / lo if lo > 0 else float("inf")
    tier: ConfidenceTier
    point_withheld = False
    if span <= _DIAL_CORROBORATE_SPAN:
        point = sum(m.mid * m.confidence for m in methods) / sum(m.confidence for m in methods)
        tier = "high"
        anchor_name = None
        note = None
    else:
        anchor = _select_anchor(methods, cyclical)
        anchor_name = anchor.name if anchor else None
        point = anchor.mid if anchor else statistics.median(mids)
        tier = "medium" if span <= _DIAL_MILD_SPAN else "low"
        note = (
            f"method divergence {span:.2g}x — anchored to {anchor_name} ${point:.0f} "
            f"(comparability: {'cyclical cash flow / book value' if cyclical else 'peer multiples'}); the remaining methods set the range bounds."
            if anchor_name
            else f"method divergence {span:.2g}x; taking the median."
        )
        if span > METHOD_CORROBORATION_SPAN_K:
            point_withheld = True
            note += (
                f" Method span exceeds the {METHOD_CORROBORATION_SPAN_K:.0f}x "
                "corroboration limit — no single method is publishable as a headline "
                "point; publish the range instead."
            )

    # Out-of-calibration cap: model/market outside [0.25x, 4x]. Even when methods
    # agree (TSLA: both ~14x below market), a confident point is unsafe — the market
    # prices growth/discount the normalized model doesn't. Cap the tier; if extreme,
    # withhold the point (keep the directional verdict). This band only GRADES the
    # gap's SIZE — it does NOT classify its NATURE (reachable aggressive growth vs
    # genuine optionality); that is the reverse-DCF's job (classify_market_implied_
    # nature), so the note must NOT assert "option value" here. The [0.25x,4x] band
    # fires for MU at 0.17x, yet MU's price IS reachable at ~37% growth — asserting
    # "option value" here contradicted the reverse-DCF's "implied 37% growth" read in
    # shipped MU output (price_target_basis vs valuation_overview, fixed 2026-06-16).
    ratio = point / current_price if current_price > 0 else float("inf")
    if ratio > MARKET_DIVERGENCE_RATIO_K or ratio < 1.0 / MARKET_DIVERGENCE_RATIO_K:
        extreme = ratio > 2 * MARKET_DIVERGENCE_RATIO_K or ratio < 1.0 / (
            2 * MARKET_DIVERGENCE_RATIO_K
        )
        tier = _floor_tier(tier, "very_low" if extreme else "low")
        note = (note or "") + (
            f" model ${point:.0f} is {ratio:.2g}x the market price, outside the [0.25x, 4x] calibration band — "
            "the market is pricing materially different growth/discount than the model's "
            "normalized assumptions; confidence reduced"
            + (", point target withheld" if extreme else "")
            + "."
        )
        if extreme:
            return tier, anchor_name, lo, hi, True, note.strip()

    return tier, anchor_name, lo, hi, point_withheld, (note or None)


def synthesize_valuations(
    methods: list[ValuationMethod], current_price: float, *, cyclical: bool = False
) -> ValuationSynthesis:
    """Synthesize multiple valuation methods into a single confidence-weighted estimate.

    Formula: weighted_price = Σ(mid_i × confidence_i) / Σ(confidence_i)
             upside_downside = (weighted_price - current_price) / current_price

    When fewer than 2 methods are present, ``weighted_price`` and
    ``upside_downside`` are set to ``None`` — a single-method result has no
    cross-check and MUST NOT be surfaced as a meaningful weighted average.

    Cross-method spread check (≥2 methods): any method whose mid deviates from
    the median of all mids by > 30% is added to ``outlier_methods`` and a
    human-readable spread warning is appended to ``warnings`` (soft disclosure
    only — it never withholds the call). The graded call (confidence tier +
    target band + the POINT-withhold decision) is produced by the confidence
    dial (``_confidence_dial``): uncertainty lowers the tier and widens the band,
    and only when the sole available number would be fabricated does it withhold
    the POINT (``valuation_withheld``) — the directional verdict always ships.

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
        conf, anchor, t_lo, t_hi, withheld, note = _confidence_dial(
            methods, current_price, cyclical
        )
        return ValuationSynthesis(
            methods=methods,
            weighted_price=None,
            current_price=current_price,
            upside_downside=None,
            confidence=conf,
            anchor_method=anchor,
            target_low=t_lo,
            target_high=t_hi,
            valuation_withheld=withheld,
            degradation_note=note,
        )

    weighted_price = sum(m.mid * m.confidence for m in methods) / total_confidence
    upside_downside = (weighted_price - current_price) / current_price

    # --- Cross-method spread check (soft disclosure only) ---
    # Flags any method whose mid sits > 30% from the cross-method median so the
    # analyst sees real method disagreement. This NEVER withholds the call — the
    # graded call (tier / band / POINT-withhold) is the confidence dial's job.
    mids = [m.mid for m in methods]
    median_mid = statistics.median(mids)

    outlier_methods: list[str] = []
    synthesis_warnings: list[str] = []

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

    conf, anchor, t_lo, t_hi, withheld, note = _confidence_dial(methods, current_price, cyclical)
    return ValuationSynthesis(
        methods=methods,
        weighted_price=weighted_price,
        current_price=current_price,
        upside_downside=upside_downside,
        outlier_methods=outlier_methods,
        warnings=synthesis_warnings,
        confidence=conf,
        anchor_method=anchor,
        target_low=t_lo,
        target_high=t_hi,
        valuation_withheld=withheld,
        degradation_note=note,
    )


# ── Recommendation thresholds (confidence-tiered, asymmetric) ───────────────
# Applied to ValuationSynthesis.upside_downside. Each tier is (buy_discount,
# sell_premium): BUY when upside ≥ buy, SELL when upside ≤ −sell, else HOLD.
# Three sell-side principles, calibrated against the live basket (MU/AAPL/KO/
# NVDA/TSLA/RIVN/F):
#   · The bands WIDEN as confidence drops — Morningstar's margin-of-safety logic:
#     the less trustworthy the anchor, the further price must sit from fair value
#     before a directional call is warranted (the alternative — a fixed ±15% on a
#     very-low-confidence anchor — fires the most aggressive call on the least
#     reliable number, which is backwards).
#   · The sell premium EXCEEDS the buy discount within every tier (asymmetric):
#     overvaluation must be more pronounced than undervaluation to trigger a call,
#     the empirical bias of long-horizon fair-value frameworks.
#   · The verdict is ALWAYS directional (BUY/HOLD/SELL) — the dial expresses
#     uncertainty by widening these bands + the target range, NEVER by withholding
#     the call (the deleted REVIEW state).
# They travel into both the LLM prompt (so the narrative is consistent) and the
# post-run override (so the contract holds even if the LLM drifts).
_VERDICT_BANDS: dict[str, tuple[float, float]] = {
    "high": (0.20, 0.25),
    "medium": (0.30, 0.35),
    "low": (0.40, 0.55),
    "very_low": (0.50, 0.75),
}


def verdict_from_upside(upside: float, confidence: str = "high") -> str:
    """Deterministic Buy/Hold/Sell from synthesis upside vs current price.

    The buy/sell bands are confidence-tiered and asymmetric (see _VERDICT_BANDS):
    a lower-confidence anchor needs price to sit further from fair value before a
    directional call fires, and the sell side requires a larger premium than the
    buy side a discount. NEVER returns a non-directional verdict.
    """
    buy, sell = _VERDICT_BANDS.get(confidence, _VERDICT_BANDS["high"])
    if upside >= buy:
        return "BUY"
    if upside <= -sell:
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
        target:              headline price target, or None when the POINT is
                             honestly withheld (valuation_withheld) — the verdict
                             still ships.
        verdict:             ALWAYS directional "BUY"/"HOLD"/"SELL" (the REVIEW
                             state is deleted); only None for the truly-empty
                             no-synthesis case.
        basis:               human-readable derivation string (cited in
                             price_target_basis).
        upside:              implied upside of the directional reference point vs
                             current price, or None.
        valuation_withheld:  True when the POINT target is withheld (the only
                             number available would be fabricated). The directional
                             verdict still ships — this is NOT a refusal to rate.
        confidence:          the synthesis confidence tier (high/medium/low/
                             very_low) that drove the asymmetric verdict bands.
    """

    target: float | None
    verdict: str | None
    basis: str | None
    upside: float | None
    valuation_withheld: bool
    confidence: str | None = None


def _anchor_point(vs: ValuationSynthesis) -> float | None:
    """The directional reference point — always computed, even when the POINT is
    withheld (it is what the verdict's direction reads off, not what publishes).

    Priority: the dial's chosen anchor method (comparability rule) → the
    confidence-weighted blend → the lone surviving method. None only when there
    is no method at all.
    """
    if vs.anchor_method:
        anchor = next((m for m in vs.methods if m.name == vs.anchor_method), None)
        if anchor is not None:
            return anchor.mid
    if vs.weighted_price is not None:
        return vs.weighted_price
    if vs.methods:
        return vs.methods[0].mid
    return None


def _range_spans_market(vs: ValuationSynthesis) -> bool:
    """True when the disclosed valuation band includes the current market price."""
    if vs.target_low is None or vs.target_high is None or vs.current_price <= 0:
        return False
    low, high = sorted((vs.target_low, vs.target_high))
    return low <= vs.current_price <= high


def resolve_canonical_thesis(vs: object, ticker: str) -> CanonicalThesis:
    """Resolve the deterministic headline verdict (+ maybe target) from a synthesis.

    Pure: depends only on ``vs`` (the "valuation_synthesis" structured-context
    value — any non-ValuationSynthesis input yields an empty CanonicalThesis).
    ``ticker`` is used only for log attribution. No I/O, no LLM — this is the
    code the LLM's headline numbers are force-reconciled against.

    The verdict is ALWAYS directional (BUY/HOLD/SELL — the REVIEW state is
    deleted). Uncertainty is expressed by the confidence tier (which widens the
    asymmetric verdict bands), the target range [target_low, target_high], and —
    when the only point we could give would be fabricated — by withholding the
    POINT (``valuation_withheld``) while the directional verdict still ships from
    the market-implied read. The dial (synthesize_valuations) already encoded the
    withhold decision; this function reads it, never re-derives it.
    """
    if not isinstance(vs, ValuationSynthesis):
        return CanonicalThesis(
            target=None, verdict=None, basis=None, upside=None, valuation_withheld=False
        )

    # Directional reference point — always, even when the point is withheld.
    point = _anchor_point(vs)

    if point is None or vs.current_price <= 0:
        # No usable point (no method at all, or no market price to compare): the
        # call is a neutral HOLD; there is nothing to anchor a direction on.
        logger.warning(
            "ValuationSynthesis for %s has %d method(s), current_price=%s — no "
            "directional reference point; verdict defaults to HOLD, target withheld",
            ticker,
            len(vs.methods),
            vs.current_price,
        )
        return CanonicalThesis(
            target=None,
            verdict="HOLD",
            basis=(
                "No usable valuation point — verdict held neutral. " + (vs.degradation_note or "")
            ).strip(),
            upside=None,
            valuation_withheld=vs.valuation_withheld,
            confidence=vs.confidence,
        )

    range_spans_market = vs.valuation_withheld and _range_spans_market(vs)
    verdict_point = vs.current_price if range_spans_market else point
    upside = (verdict_point - vs.current_price) / vs.current_price
    verdict = verdict_from_upside(upside, vs.confidence)
    target = None if vs.valuation_withheld else round(point, 2)

    # Build the basis from the method breakdown + the dial's anchor/range/note.
    method_breakdown = ", ".join(
        f"{m.name}=${m.mid:.2f}(wt={m.confidence:.2f})" for m in vs.methods
    )
    range_txt = (
        f" Range [${vs.target_low:.2f}, ${vs.target_high:.2f}]."
        if vs.target_low is not None and vs.target_high is not None
        else ""
    )
    if vs.valuation_withheld:
        anchor_txt = f"anchor {vs.anchor_method}" if vs.anchor_method else "the surviving method"
        verdict_basis = (
            "The HOLD verdict stands because the published valuation range spans the "
            "current market price, so the methods do not support a one-sided call."
            if range_spans_market
            else f"The {verdict} verdict stands on the directional read of the "
            "market-implied valuation, not a point estimate."
        )
        basis = (
            f"POINT TARGET WITHHELD (confidence={vs.confidence}): the only number "
            f"available ({anchor_txt} ${point:.2f}) would be fabricated, so it is not "
            f"published (never fabricate a number). {verdict_basis} "
            f"Methods: {method_breakdown}.{range_txt} {vs.degradation_note or ''}"
        ).strip()
    else:
        anchor_txt = (
            f"anchored on {vs.anchor_method} (comparability rule — not a blended "
            f"midpoint of divergent methods)"
            if vs.anchor_method
            else f"method-weighted blend of {len(vs.methods)} corroborating method(s) "
            "(wt = data-quality weight, NOT prediction accuracy)"
        )
        basis = (
            f"Confidence={vs.confidence}; {anchor_txt}: {method_breakdown} → "
            f"${target:.2f}.{range_txt} {vs.degradation_note or ''}"
        ).strip()

    # Substantive method suppressions — a runnable method a guard sent off (cyclical
    # forward-P/E, thin peer sample, >10x premise mismatch, …) — are forwarded onto
    # vs.warnings with the "方法退出" marker (build_valuation_synthesis). But basis above
    # is built only from the dial's degradation_note and NEVER reads vs.warnings, so the
    # headline said "only one method resolved" without the other half of the sentence
    # (run_413ad4913cc1). The narrative prompt reads canonical.basis, so folding the exit
    # reasons in here is the single point that surfaces the WHY in both the headline and
    # the narrative — not just the artifact's machine-readable warnings[] list.
    suppression_reasons = [w for w in vs.warnings if "method withheld" in w]
    if suppression_reasons:
        basis = f"{basis} {' '.join(suppression_reasons)}".strip()

    return CanonicalThesis(
        target=target,
        verdict=verdict,
        basis=basis,
        upside=upside,
        valuation_withheld=vs.valuation_withheld,
        confidence=vs.confidence,
    )
