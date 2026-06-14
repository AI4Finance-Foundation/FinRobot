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
    SINGLE_METHOD_DIVERGENCE_RATIO_K,
)

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

# MARKET_DIVERGENCE_RATIO_K (4.0, multi-method) and SINGLE_METHOD_DIVERGENCE_RATIO_K
# (2.0, lone surviving method) are the two PUBLIC divergence bands — imported above
# from engine/models/valuation_thresholds (leaf). They live in the leaf because the
# persist-boundary output contract (artifact/contract clause C1) re-checks the same
# bands on the final artifact and is forbidden to import compute/. The full
# calibration rationale (why 4x for a corroborated estimate, why 2x for an
# uncorroborated lone method — the TSLA option-value and MU $2172 cases) lives with
# the constants there. The gate that fires on these bands is the confidence dial
# below (_confidence_dial): out-of-band → cap the tier and, when extreme, withhold
# the POINT (valuation_withheld) while the directional verdict still ships.


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
        if 1.0 / SINGLE_METHOD_DIVERGENCE_RATIO_K <= ratio <= SINGLE_METHOD_DIVERGENCE_RATIO_K:
            band = abs(only.mid) * _DIAL_SINGLE_BAND_FRAC
            return (
                "medium",
                None,
                only.mid - band,
                only.mid + band,
                False,
                f"单一方法 {only.name} 无交叉校验 — 区间放宽,置信中等。",
            )
        return (
            "very_low",
            None,
            None,
            None,
            True,
            f"单一方法 {only.name} ${only.mid:.0f} 为市价的 {ratio:.2g}x,出 "
            f"[{1.0 / SINGLE_METHOD_DIVERGENCE_RATIO_K:.2g}x,"
            f"{SINGLE_METHOD_DIVERGENCE_RATIO_K:.0f}x] 单法校准带 — 点目标暂缺,方向取市场隐含。",
        )

    # ≥2 methods: tier from inter-method agreement (NOT market distance).
    span = hi / lo if lo > 0 else float("inf")
    tier: ConfidenceTier
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
            f"方法分歧 {span:.2g}x — 锚定 {anchor_name} ${point:.0f}"
            f"(可比性:{'周期股现金流/账面' if cyclical else 'peer 倍数'}),其余方法作区间界。"
            if anchor_name
            else f"方法分歧 {span:.2g}x,取中位。"
        )

    # Out-of-calibration cap (option-value regime): model/market outside [0.25x, 4x].
    # Even when methods agree (TSLA: both ~14x below market), a confident point is
    # unsafe — the market prices something the models structurally miss. Cap the
    # tier; if extreme, withhold the point (keep the directional verdict).
    ratio = point / current_price if current_price > 0 else float("inf")
    if ratio > MARKET_DIVERGENCE_RATIO_K or ratio < 1.0 / MARKET_DIVERGENCE_RATIO_K:
        extreme = ratio > 2 * MARKET_DIVERGENCE_RATIO_K or ratio < 1.0 / (
            2 * MARKET_DIVERGENCE_RATIO_K
        )
        tier = _floor_tier(tier, "very_low" if extreme else "low")
        note = (note or "") + (
            f" 模型 ${point:.0f} 为市价的 {ratio:.2g}x,出 [0.25x,4x] 校准带 — "
            "市场或在定价模型未捕捉的期权价值,置信下调" + ("、点目标暂缺" if extreme else "") + "。"
        )
        if extreme:
            return tier, anchor_name, lo, hi, True, note.strip()

    return tier, anchor_name, lo, hi, False, (note or None)


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
        # Whether the methods agree with EACH OTHER is a separate question from
        # whether they agree with the MARKET. State the real cross-method spread
        # instead of asserting "they corroborate" — for the 2026-06-09 TSLA
        # artifact the DCF ($27.83) and comps ($46.78) ranges did not even
        # overlap, yet this branch claimed they "corroborate each other".
        methods_corroborate = lo > 0 and hi / lo <= _RELIABILITY_RATIO_K
        if methods_corroborate:
            agreement = (
                f"The {len(methods)} methods agree with each other (span "
                f"${lo:.2f}–${hi:.2f}, {hi / lo:.2g}x, within the "
                f"{_RELIABILITY_RATIO_K:.2g}x corroboration limit) but all sit far "
                "outside the market — the market is pricing option value (e.g. new "
                "business lines / growth optionality) that cash-flow and relative "
                "models do not capture."
            )
        else:
            spread_txt = f"{hi / lo:.2g}x apart" if lo > 0 else "a non-positive low estimate"
            agreement = (
                f"The {len(methods)} methods do not even agree with each other (span "
                f"${lo:.2f}–${hi:.2f}, {spread_txt}) and all sit far from the market."
            )
        synthesis_warnings.append(
            f"Weighted target ${weighted_price:.2f} is UNRELIABLE: it is "
            f"{valuation_ratio:.2g}x the ${current_price:.2f} market price (outside the "
            f"[{1.0 / MARKET_DIVERGENCE_RATIO_K:.2g}x, {MARKET_DIVERGENCE_RATIO_K:.2g}x] "
            f"calibration band). {agreement} The model is outside its calibration "
            "range; a fundamentals point target must be withheld pending review."
        )

    conf, anchor, t_lo, t_hi, withheld, note = _confidence_dial(methods, current_price, cyclical)
    return ValuationSynthesis(
        methods=methods,
        weighted_price=weighted_price,
        current_price=current_price,
        upside_downside=upside_downside,
        outlier_methods=outlier_methods,
        warnings=synthesis_warnings,
        reliable=reliable,
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

    upside = (point - vs.current_price) / vs.current_price
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
        basis = (
            f"POINT TARGET WITHHELD (confidence={vs.confidence}): the only number "
            f"available ({anchor_txt} ${point:.2f}) would be fabricated, so it is not "
            f"published (绝不编数字). The {verdict} verdict stands on the directional "
            f"read of the market-implied valuation, not a point estimate. "
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

    return CanonicalThesis(
        target=target,
        verdict=verdict,
        basis=basis,
        upside=upside,
        valuation_withheld=vs.valuation_withheld,
        confidence=vs.confidence,
    )
