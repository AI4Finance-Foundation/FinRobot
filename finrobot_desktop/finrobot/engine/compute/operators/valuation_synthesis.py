"""Multi-method valuation synthesis.

What this code does that raw LLM cannot: deterministic confidence-weighted
average across valuation methods. Same inputs always produce same result.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from typing import Final, Literal

from finrobot.engine.models.financial import ValuationMethod, ValuationSynthesis
from finrobot.engine.models.valuation_thresholds import (
    MARKET_DIVERGENCE_RATIO_K,
    METHOD_CORROBORATION_SPAN_K,
    RERATING_ANCHOR_DISPLACEMENT_M,
    RERATING_GAP_RATIO_K,
    SINGLE_METHOD_DIVERGENCE_RATIO_K,
)

logger = logging.getLogger(__name__)


# Human-readable labels for the canonical method ids — the price_target_basis is
# shown verbatim on the report cover AND fed into the LLM narrative prompt, so a
# raw snake_case key ("comps_pe=$182.97") reads as developer-ese to an analyst.
# Mirrors desktop/src/components/charts/FootballField.tsx `METHOD_LABEL` (the
# football field already renders these labels; the basis line must match, not show
# two names for the same method on one page). Unknown id → upper-cased fallback,
# same as the frontend's `?? method.toUpperCase()`.
_METHOD_LABEL: Final[dict[str, str]] = {
    "dcf": "DCF",
    "comps_pe": "Comps (P/E)",
    "comps_pb": "Comps (P/B)",
    "comps_ev_ebitda": "Comps (EV/EBITDA)",
    "ev_ebitda": "EV/EBITDA",
    "p_fcf": "P/FCF",
    "ddm": "DDM",
    "residual_income": "Residual Income",
    "lbo": "LBO",
}


def _method_label(name: str) -> str:
    return _METHOD_LABEL.get(name, name.upper())


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
# band (the option-value regime). A corroborated blend is additionally capped at
# medium when it is RE-RATING-LED — breaching multiples premises dragging it off
# the DCF anchor (RERATING_GAP_RATIO_K / RERATING_ANCHOR_DISPLACEMENT_M; orthogonal
# to market distance by construction — see the gate in the blend branch).
# Thresholds calibrated against the full basket (MU/AAPL/KO/NVDA/TSLA/RIVN/F) —
# see scripts/probe_review_map + dial validation.
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
    methods: list[ValuationMethod],
    current_price: float,
    cyclical: bool,
    financial_sector: bool,
) -> tuple[ConfidenceTier, str | None, float | None, float | None, bool, str | None]:
    """Return (confidence, anchor_method, target_low, target_high, withheld, note).

    Pure. Encodes the graded-call rules; the verdict/target themselves are resolved
    downstream from these fields (resolve_canonical_thesis). ``methods`` is non-empty.

    ``financial_sector`` (``is_bank``) makes a CORROBORATED bank/insurer anchor on its
    DDM row (the income-based intrinsic value) rather than blend — see the corroborated
    branch for the rationale and the corroboration-gate safety.
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

    # Lone median-outlier inside an otherwise-corroborated set. ``span`` (max/min) is a
    # two-POINT measure — blind to a bimodal "2 cluster + 1 outlier" set whose extremes
    # happen to land ≤ _DIAL_CORROBORATE_SPAN. AAPL: comps_pe $183 + dcf $189 cluster at
    # ~$185 while ev_ebitda $266 sits +41% off the $189 median, yet 266/183 = 1.45 ≤ 1.5,
    # so the span read it as corroborated and blended all three into a false-precise
    # high-confidence $210. GOOGL (span 1.56, comps_pe the high outlier) is the SAME shape
    # one tick over the 1.5x cliff and already routes divergent — so this is the
    # consistency fix, not new behaviour. A bimodal set is NOT corroborated: route it to
    # the divergent branch (anchor the cluster's cash-flow value, never a blend that
    # absorbs the outlier). The downstream median-deviation gate flags ``outlier_methods``
    # with the SAME _OUTLIER_THRESHOLD, so the headline and the flagged outlier can no
    # longer disagree (the old blend named ev_ebitda an outlier while pricing it in).
    # NON-cyclical only: a cyclical's DCF/PB anchor is intentional even as the lone
    # outlier (peak-EPS comps are the unreliable side there), so the cyclical exemption
    # in the divergent branch must keep owning it — never anchor a cyclical to its comps
    # cluster here.
    median_mid = statistics.median(mids)
    cluster = [
        m
        for m in methods
        if median_mid == 0 or abs(m.mid - median_mid) / abs(median_mid) <= _OUTLIER_THRESHOLD
    ]
    cluster_mids = [m.mid for m in cluster]
    bimodal = (
        not cyclical
        and len(methods) >= 3
        and 2 <= len(cluster) < len(methods)  # a tight cluster + ≥1 median-outlier
        and (max(cluster_mids) / min(cluster_mids) if min(cluster_mids) > 0 else float("inf"))
        <= _DIAL_CORROBORATE_SPAN
    )

    # Bank intrinsic anchor = residual income (justified P/B): ROE-coherent and
    # buyback-invariant, so it anchors whether the comps corroborate OR diverge. A
    # bank's comps_pb and comps_pe disagree precisely because they price book and
    # earnings separately and the peer median grants no quality premium — RI
    # integrates book, earnings and ROE into one value (PNC 2026-06-23: comps_pb
    # $303 vs comps_pe $193 anchored the low $193 → RI $275, in the sell-side range).
    # When ROE < CoE the value sits below book — the correct bearish read for a
    # chronic underperformer (Citi), not papered over to consensus. A mid-merger bank
    # whose ROE is poisoned is caught upstream by the mna_transition gate and never
    # reaches here, and the out-of-calibration cap below still withholds if RI is
    # wildly off market. Supersedes the dividend-only DDM anchor — buyback-invariant
    # where the DDM was not (BAC). The RI beta is the SAME Blume-adjusted cost of
    # equity the DCF/DDM use.
    ri_method = next((m for m in methods if m.name == "residual_income"), None)
    if financial_sector and ri_method is not None:
        anchor_name = "residual_income"
        # The target band IS the RI value band [RI at trailing ROE → RI at forward
        # consensus ROE] (set in _ri_method, ±15%-floored), NOT the comps mid-spread. A
        # cyclical bank's metric at one point in the cycle is not its perpetuity value, so
        # we refuse to extrapolate a single ROE — the band brackets trough→normalized and
        # resolve_canonical_thesis rates price-vs-band. In-band → HOLD, point withheld (the
        # band IS that refusal); outside → directional from the nearest edge. ``point`` =
        # the trailing RI is kept only for the out-of-calibration cap below. tier still
        # grades from the comps agreement (span).
        lo, hi = min(ri_method.low, ri_method.high), max(ri_method.low, ri_method.high)
        point = ri_method.mid
        point_withheld = lo <= current_price <= hi
        tier = (
            "high"
            if span <= _DIAL_CORROBORATE_SPAN
            else "medium"
            if span <= _DIAL_MILD_SPAN
            else "low"
        )
        loc = "within" if point_withheld else ("above" if current_price > hi else "below")
        note = (
            f"financial-sector issuer — residual-income value band ${lo:.0f}–${hi:.0f} "
            f"(RI at trailing ROE → at FY1 consensus ROE), the bank's ROE-coherent, "
            f"buyback-invariant intrinsic. Price ${current_price:.0f} is {loc} the band → "
            + (
                "verdict HOLD, point withheld (we do not claim a single cycle-point value)."
                if point_withheld
                else "directional verdict from the nearest edge."
            )
        )
    elif span <= _DIAL_CORROBORATE_SPAN and not bimodal:
        # Corroborated method set → blend (confidence-weighted central tendency; the
        # agreement IS the signal).
        tier = "high"
        point = sum(m.mid * m.confidence for m in methods) / sum(m.confidence for m in methods)
        anchor_name = None
        note = None
        # ── Re-rating dominance gate (P0-1.2, 2026-07-07) ─────────────────────
        # comps_pe / self-band ev_ebitda price the target on the premise that its
        # multiple CONVERGES to their anchor. When (a) ≥1 such premise requires a
        # multiple shift beyond RERATING_GAP_RATIO_K, AND (b) those methods drag
        # the blend more than RERATING_ANCHOR_DISPLACEMENT_M away from the
        # cash-flow (DCF) anchor, "high confidence" would really be a bet on an
        # unproven re-rating (MSFT 2026-07-07: 1.38×/1.64× premises, blend +18.4%
        # off the $451 DCF, shipped as high-conf +38% BUY that slipped the span
        # and bimodal gates by a hair). Cap the tier at medium and put the
        # DCF-only anchor beside the blend — change no number, drop no method,
        # never touch the verdict directly. Deliberately ORTHOGONAL to market
        # distance (红线): a corroborated SELL/BUY where the methods AGREE has a
        # near-zero blend-vs-DCF displacement and never trips condition (b), so
        # "two methods both say rich = high-confidence SELL" stays intact. This
        # GRADES the premise's size — it never classifies the gap's nature (the
        # reverse-DCF owns that). No DCF in the set → no cash-flow reference to
        # displace from → gate inert (the per-method re-rating warnings still
        # disclose the premise). A bank without RI lands here with DCF
        # suppressed, so it is inert there too.
        rerating_breach = [
            m
            for m in methods
            if m.rerating_ratio is not None
            and (
                m.rerating_ratio > RERATING_GAP_RATIO_K
                or m.rerating_ratio < 1.0 / RERATING_GAP_RATIO_K
            )
        ]
        dcf_anchor = next((m for m in methods if m.name == "dcf"), None)
        if rerating_breach and dcf_anchor is not None and dcf_anchor.mid > 0:
            displacement = point / dcf_anchor.mid - 1.0
            if abs(displacement) > RERATING_ANCHOR_DISPLACEMENT_M:
                tier = _floor_tier(tier, "medium")
                premise_txt = "; ".join(
                    f"{_method_label(m.name)} prices the target at {m.rerating_ratio:.2f}× "
                    f"its current same-caliber multiple"
                    for m in rerating_breach
                )
                note = (
                    f"multiples-led blend: {premise_txt} — an unproven re-rating premise, "
                    f"not a modelled convergence — and it pulls the blended point "
                    f"${point:.0f} to {displacement:+.0%} from the cash-flow (DCF-only) "
                    f"anchor ${dcf_anchor.mid:.0f}. Confidence capped at medium; read the "
                    f"blend and the DCF anchor side by side."
                )
    else:
        reanchored_from: ValuationMethod | None = None
        anchor: ValuationMethod | None
        if bimodal:
            # Bimodal set (tight cluster + lone median-outlier the max/min span missed).
            # Anchor the cluster's cash-flow value — DCF if it clustered, else the cluster
            # method nearest the cluster median — NOT a blend that absorbs the outlier into
            # the headline (AAPL: dcf $189, the cluster centre, not the $210 three-way blend
            # inflated by ev_ebitda $266). The outlier still bounds the band. The note names
            # the REAL outlier (the median-deviation one), unlike the re-anchor branch below
            # which assumes the comps EXTREME is the suspect.
            cluster_median = statistics.median(cluster_mids)
            anchor = next((m for m in cluster if m.name == "dcf"), None) or min(
                cluster, key=lambda m: abs(m.mid - cluster_median)
            )
            anchor_name = anchor.name
            point = anchor.mid
            outliers = [m for m in methods if m not in cluster]
            outlier_txt = ", ".join(f"{_method_label(m.name)} ${m.mid:.0f}" for m in outliers)
            note = (
                f"method spread {span:.2g}x reads corroborated on the extremes, but {outlier_txt} "
                f"sits >{_OUTLIER_THRESHOLD:.0%} off the cross-method median while the remaining methods "
                f"cluster (≤{_DIAL_CORROBORATE_SPAN:g}x) — a bimodal set. Anchored to the corroborated "
                f"{_method_label(anchor_name)} ${point:.0f} rather than a blend that would absorb the "
                f"outlier; the full method range still bounds the band."
            )
        else:
            anchor = _select_anchor(methods, cyclical)
            # Lone-outlier re-anchor (non-cyclical, ≥3 methods): _select_anchor anchors a
            # peer-rich name to comps, but when that comps anchor is a cross-method EXTREME
            # and the OTHER methods corroborate (≤ _DIAL_CORROBORATE_SPAN) WITHOUT it, ≥2
            # independent methods agree AWAY from comps → comps is the suspect one and must
            # not stamp the headline. KO 2026-06-22: comps_pe $53 (peer-median P/E ignores
            # KO's quality premium — verified vs external analyst target $85 / KO fwd P/E
            # 24.7 / our DCF $76) while DCF $76 + EV/EBITDA $90 agree and match truth. Re-
            # anchor to the corroborated DCF cash-flow value so the headline isn't a −33%
            # outlier. Cyclicals are EXEMPT — their DCF/PB anchor is intentional even as an
            # outlier (peak-EPS comps are the unreliable side there).
            if (
                not cyclical
                and anchor is not None
                and anchor.name.startswith("comps")
                and len(methods) >= 3
            ):
                dcf = next((m for m in methods if m.name == "dcf"), None)
                rest = [m.mid for m in methods if m is not anchor]
                rest_span = (max(rest) / min(rest)) if rest and min(rest) > 0 else float("inf")
                if (
                    dcf is not None
                    and anchor.mid in (lo, hi)
                    and rest_span <= _DIAL_CORROBORATE_SPAN
                ):
                    reanchored_from = anchor
                    anchor = dcf
            anchor_name = anchor.name if anchor else None
            point = anchor.mid if anchor else statistics.median(mids)
            if reanchored_from is not None:
                note = (
                    f"method divergence {span:.2g}x — {reanchored_from.name} ${reanchored_from.mid:.0f} is a "
                    f"lone outlier (the other methods corroborate ≤{_DIAL_CORROBORATE_SPAN:g}x without it), so the "
                    f"target anchors to the corroborated DCF cash-flow value ${point:.0f}; the full method range "
                    "still bounds the band."
                )
            elif anchor_name:
                note = (
                    f"method divergence {span:.2g}x — anchored to {anchor_name} ${point:.0f} "
                    f"(comparability: {'cyclical cash flow / book value' if cyclical else 'peer multiples'}); the remaining methods set the range bounds."
                )
            else:
                note = f"method divergence {span:.2g}x; taking the median."
        tier = "medium" if span <= _DIAL_MILD_SPAN else "low"
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


def _apply_mna_transition(
    withheld: bool, note: str | None, mna_transition: bool
) -> tuple[bool, str | None]:
    """When the name just closed a stock-funded acquisition / large secondary, its
    TTM per-share metrics are not yet representative of the combined entity (post-
    deal share count over mostly-pre-deal earnings), so every method reads
    spuriously bearish. Force the POINT withheld and disclose why; the neutral HOLD
    verdict is applied in resolve_canonical_thesis off the mna_transition flag. A
    data-lineage degradation, not a calibration call."""
    if not mna_transition:
        return withheld, note
    mna_note = (
        "recent acquisition / large secondary — current share count exceeds the "
        "pre-deal weighted-average baseline, so the TTM per-share metrics (DDM "
        "growth, comps EPS, ROE) are not yet representative of the combined entity; "
        "the point target is withheld and the verdict held neutral pending the "
        "combined entity's normalized results"
    )
    return True, (f"{note} {mna_note}".strip() if note else mna_note)


# A small HOLD buffer just past the band edge — knife-edge protection so a name sitting
# AT the band boundary doesn't flip BUY/SELL on a price micro-move. NOT a calibration of
# the call's magnitude: the band itself ([realized ROE → forward consensus ROE]) carries
# the margin of safety, already widening for low-agreement names, so re-applying the wide
# confidence-tier thresholds here would double-count that uncertainty and suppress a real
# out-of-band signal to HOLD. Past this buffer the call is directional; the upside MAGNITUDE
# (shown to the analyst) conveys mild vs strong.
_RI_BAND_EDGE_BUFFER: Final[float] = 0.03


def _ri_band_verdict(
    band_low: float, band_high: float, current_price: float
) -> tuple[float | None, str, float | None, bool]:
    """Rate a bank's residual-income value band against price → (target, verdict, upside,
    withheld).

    The band is [RI at trailing ROE → RI at forward consensus ROE] — the trough→normalized
    range. A cyclical metric at one point in the cycle is not the perpetuity value, so we
    refuse to extrapolate a single ROE to a point:
      • price WITHIN the band (or within the ±edge-buffer of it) → HOLD, point withheld
        (the band IS that refusal; the range still discloses the realized-low /
        consensus-high bounds — 撤点 ≠ 撤区间);
      • price OUTSIDE → directional from the NEAREST edge. Price above the forward
        (consensus-recovery) end means the market pays more than even the bank's own best
        case justifies — an independent SELL a consensus-parroting engine structurally
        cannot produce (the forward end is our ceiling, never our anchor). Price below the
        realized-ROE floor → BUY.
    """
    lo, hi = sorted((band_low, band_high))
    if current_price <= 0 or lo <= current_price <= hi:
        return None, "HOLD", None, True
    edge = hi if current_price > hi else lo
    upside = (edge - current_price) / current_price
    if abs(upside) <= _RI_BAND_EDGE_BUFFER:
        return None, "HOLD", None, True  # at the band boundary → HOLD (no knife-edge)
    return round(edge, 2), ("SELL" if current_price > hi else "BUY"), upside, False


def synthesize_valuations(
    methods: list[ValuationMethod],
    current_price: float,
    *,
    cyclical: bool = False,
    financial_sector: bool = False,
    mna_transition: bool = False,
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
            methods, current_price, cyclical, financial_sector
        )
        withheld, note = _apply_mna_transition(withheld, note, mna_transition)
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
            mna_transition=mna_transition,
            financial_sector=financial_sector,
        )

    weighted_price = sum(m.mid * m.confidence for m in methods) / total_confidence

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
                    f"{_method_label(m.name)} valuation (${m.mid:,.2f}) diverges "
                    f"{deviation:.0%} from the cross-method median (${median_mid:,.2f})"
                    f" — wide method spread; treat the point estimate with caution."
                )
                logger.warning(
                    "synthesize_valuations: %s mid $%.2f deviates %.0f%% from "
                    "cross-method median $%.2f — flagged as outlier",
                    m.name,
                    m.mid,
                    deviation * 100,
                    median_mid,
                )

    conf, anchor, t_lo, t_hi, withheld, note = _confidence_dial(
        methods, current_price, cyclical, financial_sector
    )
    withheld, note = _apply_mna_transition(withheld, note, mna_transition)

    # upside_downside must equal the canonical upside the verdict/target read off,
    # NOT the raw blend. When methods diverge the dial anchors the headline to ONE
    # method (`anchor`) — resolve_canonical_thesis then reads its mid as the
    # directional point, not the blend. A blend-based upside contradicts the
    # report's own headline (KO: weighted blend $72.68 → −8.5% vs the published
    # comps_pe anchor $53.51 → −32.6%). This mirrors _anchor_point + the
    # range-spans-market neutralisation in resolve_canonical_thesis exactly (pinned
    # by test_upside_downside_matches_canonical_*), so the two never drift.
    reference_price = (
        next((m.mid for m in methods if m.name == anchor), weighted_price)
        if anchor
        else weighted_price
    )
    # Mirror resolve_canonical_thesis: a withheld point whose disclosed range spans
    # the market reads as a neutral 0% gap (the band brackets price → no one-sided
    # directional distance), else the gap to the reference point.
    range_spans_market = (
        withheld
        and t_lo is not None
        and t_hi is not None
        and min(t_lo, t_hi) <= current_price <= max(t_lo, t_hi)
    )
    # Withheld + range entirely on one side: read direction from the NEAREST published
    # EDGE, never the withheld interior anchor — an out-of-cal anchor (e.g. a 5.6x-price
    # DCF) otherwise prints a de-anchored upside (ALL +460% pre-slice-1). Mirrors the
    # RI-band edge logic + resolve_canonical_thesis (Bug-1c, 2026-06-24).
    if range_spans_market:
        verdict_point = current_price
    elif withheld and t_lo is not None and t_hi is not None:
        lo, hi = sorted((t_lo, t_hi))
        verdict_point = lo if current_price < lo else hi
    else:
        verdict_point = reference_price
    # upside_downside must mirror the canonical verdict exactly (pinned invariant), so it
    # follows the SAME branch resolve_canonical_thesis takes: an M&A-transition name has no
    # usable direction (None); a bank with an RI value band reads price-vs-band; everything
    # else takes the anchor/range read.
    if mna_transition:
        upside_downside = None
    elif anchor == "residual_income" and t_lo is not None and t_hi is not None:
        _, _, upside_downside, _ = _ri_band_verdict(t_lo, t_hi, current_price)
    else:
        upside_downside = (verdict_point - current_price) / current_price
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
        mna_transition=mna_transition,
        financial_sector=financial_sector,
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


STREET_CONTEXT_MARKER: Final[str] = "Street context:"
"""Stable leading label every street-context line begins with. The report's
compute-warnings layering (frontend ``reportData.layerComputeWarnings``) matches on
THIS token to route the line OUT of the ⚠ caveat pile and into the valuation box
beside the cover target — a re-location, not a suppression. Single source: reword
the disclosure prose only through this constant, or the frontend routing silently
breaks. Mirrors the ``RERATING_WARNING_MARKER`` pattern in ``valuation_aggregator.py``.
The frontend copy lives in ``reportData.ts`` (STREET_CONTEXT_MARKER) — keep in sync."""


def street_range_disclosure(
    target: float | None,
    street_low: float | None,
    street_high: float | None,
    analyst_count: int | None = None,
    consensus: float | None = None,
) -> str | None:
    """Standing street-context fact line beside the cover target, whenever the
    sell-side distribution is available (boss-approved 2026-07-08 disclosure,
    widened 2026-07-09 to an always-on fact line — BACKLOG A9/B1). Eliminates the
    "when does the street get shown" edge: the reader used to see nothing at all
    UNLESS our target fell entirely outside the sell-side band, so an in-band call
    that was nonetheless deep inside a lopsided street distribution (MSFT: our
    target sat within the sell-side band but far below its mean) rendered with the
    same silence as "no coverage exists" — a blind audit read that silence as "the
    system doesn't know the consensus". Now the low/high/consensus/analyst-count
    facts render every time they are available; verdict/confidence/target numbers
    are never touched by this function — pure disclosure, never a gate.

    Out-of-band (our target sits entirely outside [street_low, street_high]): the
    SAME fact line, with the pre-existing out-of-consensus sentence appended on the
    one marker line (single frontend route) — an out-of-consensus call is legitimate
    (the contract says confidence never looks at market distance), but a reader
    handed a target below the most bearish street number deserves to be told so.

    Caliber note: both sides are 12-month FORWARD targets (ours = the report's
    12-month target; FMP /price-target-consensus = sell-side 12-month targets),
    so the comparison shares one axis — this is street RANGE POSITIONING, never
    a success probability (the LBO FV/PV mixed-axis family does not apply).

    Returns None when the target is missing/non-positive, when either bound is
    missing/non-positive, or when the band is degenerate (low > high) — a fetch
    miss or a malformed distribution must never degrade the thesis step (never
    raises). ``consensus`` and ``analyst_count`` are each independently optional:
    a missing consensus (or a non-positive one) drops only that segment of the
    fact line rather than withholding the whole line — the low/high band alone is
    still useful context.
    """
    if target is None or target <= 0:
        return None
    if street_low is None or street_high is None or street_low <= 0 or street_high <= 0:
        return None
    if street_low > street_high:
        return None

    consensus_part = (
        f" · consensus ${consensus:.2f}" if consensus is not None and consensus > 0 else ""
    )
    analysts_part = f" · {analyst_count} analysts" if analyst_count else ""
    fact = (
        f"{STREET_CONTEXT_MARKER} sell-side ${street_low:.2f}–${street_high:.2f}"
        f"{consensus_part}{analysts_part}"
    )
    if street_low <= target <= street_high:
        return fact

    direction = "below" if target < street_low else "above"
    # The fact segment already stated the band + count; the appended clause carries
    # only the out-of-consensus interpretation, not a second copy of the numbers.
    return (
        f"{fact} — the 12-month target ${target:.2f} sits {direction} the entire "
        f"sell-side range, an out-of-consensus call disclosed for context; it does "
        f"not alter the verdict or confidence."
    )


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

    if vs.mna_transition:
        # Just-closed stock-funded acquisition / large secondary: every method is
        # built on a TTM snapshot that mixes a post-deal share count with mostly
        # pre-deal earnings, so they read spuriously bearish while the market prices
        # the pro-forma entity. Withhold the poisoned point and hold the verdict
        # neutral — a data-lineage degradation, NOT a directional call. The methods
        # stay visible (range/football field) for transparency.
        method_breakdown = ", ".join(f"{_method_label(m.name)} ${m.mid:.2f}" for m in vs.methods)
        return CanonicalThesis(
            target=None,
            verdict="HOLD",
            basis=(
                "POINT TARGET WITHHELD — post-acquisition transition: "
                + (vs.degradation_note or "the share count jumped on a recent deal")
                + ". Verdict held neutral. Methods (shown for transparency): "
                + f"{method_breakdown}."
            ).strip(),
            upside=None,
            valuation_withheld=True,
            confidence=vs.confidence,
        )

    # Bank residual-income value band → rate price-vs-band, never a single perpetuity-ROE
    # point. The band [RI at trailing ROE → RI at forward consensus ROE] brackets the
    # trough→normalized uncertainty; the band IS our refusal to claim one cycle-point value.
    if (
        vs.anchor_method == "residual_income"
        and vs.target_low is not None
        and vs.target_high is not None
    ):
        lo, hi = sorted((vs.target_low, vs.target_high))
        target, verdict, upside, in_band = _ri_band_verdict(lo, hi, vs.current_price)
        # Respect the dial's out-of-calibration cap: when it already withheld the point (RI
        # band extreme vs market) keep the target withheld but still ship the directional
        # verdict from the market-implied read.
        cap_withheld = vs.valuation_withheld and not in_band
        withheld = in_band or vs.valuation_withheld
        if withheld:
            target = None
        method_breakdown = ", ".join(f"{_method_label(m.name)} ${m.mid:.2f}" for m in vs.methods)
        if in_band:
            # Price inside the fair-value band → FAIRLY VALUED. Lead with the conclusion
            # (the analyst's read), not the mechanic (point withheld): there is no margin
            # of safety either way, hence HOLD. We still don't fabricate a single
            # perpetuity-ROE point inside the band — the band IS that refusal.
            basis = (
                f"FAIRLY VALUED: price ${vs.current_price:.2f} sits within the residual-income "
                f"fair-value band [${lo:.2f}, ${hi:.2f}] (RI at trailing ROE → at FY1 consensus "
                f"ROE), so there is no margin of safety either way — verdict HOLD. A cyclical "
                f"bank's value is a trough→normalized range, not a single perpetuity ROE, so we "
                f"publish the band rather than fabricate a point inside it. Methods: "
                f"{method_breakdown}."
            )
        elif cap_withheld:
            basis = (
                f"POINT TARGET WITHHELD: the residual-income band [${lo:.2f}, ${hi:.2f}] is "
                f"out of calibration vs price ${vs.current_price:.2f} — the {verdict} verdict "
                f"ships from the market-implied read, not a fabricated point. "
                f"Methods: {method_breakdown}."
            )
        else:
            side = "above" if vs.current_price > hi else "below"
            extra = (
                " — the market pays more than even the bank's own forward-consensus recovery "
                "justifies (the consensus end is our ceiling, not our anchor)"
                if side == "above"
                else " — the market is below even our realized-ROE floor"
            )
            basis = (
                f"Price ${vs.current_price:.2f} is {side} the residual-income value band "
                f"[${lo:.2f}, ${hi:.2f}]{extra}; target = nearest edge ${target:.2f} "
                f"({verdict}). Methods: {method_breakdown}."
            )
        return CanonicalThesis(
            target=target,
            verdict=verdict,
            basis=basis,
            upside=upside,
            valuation_withheld=withheld,
            confidence=vs.confidence,
        )

    # Withheld + range entirely on one side: read direction from the NEAREST published
    # EDGE, never the withheld interior point — an out-of-cal anchor (e.g. a 5.6x-price
    # DCF) otherwise prints a de-anchored upside (ALL +460% pre-slice-1). The edge gives
    # an honest direction without republishing a fabricated magnitude; generalizes to any
    # future extreme-withhold, financial or not. Mirrors the RI-band path + the
    # upside_downside calc in synthesize_valuations (Bug-1c, 2026-06-24).
    range_spans_market = vs.valuation_withheld and _range_spans_market(vs)
    if range_spans_market:
        verdict_point = vs.current_price
    elif vs.valuation_withheld and vs.target_low is not None and vs.target_high is not None:
        lo, hi = sorted((vs.target_low, vs.target_high))
        verdict_point = lo if vs.current_price < lo else hi
    else:
        verdict_point = point
    upside = (verdict_point - vs.current_price) / vs.current_price
    verdict = verdict_from_upside(upside, vs.confidence)
    target = None if vs.valuation_withheld else round(point, 2)

    # Build the basis from the method breakdown + the dial's anchor/range/note.
    method_breakdown = ", ".join(
        f"{_method_label(m.name)} ${m.mid:.2f} (wt {m.confidence:.2f})" for m in vs.methods
    )
    range_txt = (
        f" Range [${vs.target_low:.2f}, ${vs.target_high:.2f}]."
        if vs.target_low is not None and vs.target_high is not None
        else ""
    )
    if vs.valuation_withheld and range_spans_market:
        # Fairly valued: the published range brackets the market on BOTH sides, so the
        # methods give no one-sided call → HOLD. Lead with the conclusion (fairly valued),
        # not the mechanic (point withheld); we still don't fabricate a single interior
        # point — the range is the honest answer. (Keep the "range spans the current
        # market price" clause: contract test_run_5ae06f55 pins it.)
        basis = (
            f"FAIRLY VALUED (confidence={vs.confidence}): the published valuation range "
            f"spans the current market price, so the methods do not support a one-sided "
            f"call — verdict HOLD. We publish the range rather than fabricate a single "
            f"point inside it. Methods: {method_breakdown}.{range_txt} "
            f"{vs.degradation_note or ''}"
        ).strip()
    elif vs.valuation_withheld:
        # Withheld + range entirely on one side of the market: a genuine "we can't pin a
        # defensible number" — keep the honest WITHHELD framing, direction off the nearest edge.
        anchor_txt = f"anchor {vs.anchor_method}" if vs.anchor_method else "the surviving method"
        verdict_basis = (
            f"The {verdict} verdict reads off the nearest published range bound "
            f"(${verdict_point:.2f}), not the withheld interior point — the market sits "
            f"{'below' if vs.current_price < verdict_point else 'above'} the whole range."
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
