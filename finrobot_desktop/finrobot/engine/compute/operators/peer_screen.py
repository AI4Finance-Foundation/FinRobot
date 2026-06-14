"""Deterministic peer screening for comps (ADR-0014).

What this code does that raw LLM cannot: same candidate payload always yields
the same peer set, with a numeric trace an analyst can re-derive by hand. The
retired LLM selection picked different sets run-to-run, swinging the published
comps_pe target ±30% within one day (MSFT $487 → $636, 2026-06-05) — a number
that moves without the market moving is worse than no number.

Selection = tiered business affinity, then size proximity within tier
(empirically validated 2026-06-05 against MSFT/KO/NVDA/ADBE; pure size
proximity without tiers turned MSFT's comp sheet into a semiconductor basket):

  Tier 1  same FMP industry        (closest business definition)   ─┐ high
  Tier 2  FMP stock_peers list     (cross-recommendations)          ─┘ affinity
  Tier 3  same FMP sector          (cross-industry breadth fill — used ONLY when
                                    the affinity tiers can't field a viable set)

Within each tier candidates must pass the eligibility screen:
  - market cap inside the tier's band. The CEILING is 20x for every tier (never
    compare UP to a giant). The FLOOR differs by affinity: the high-affinity
    tiers (1, 2) use a wide 1/200x floor — a same-industry / cross-recommended
    name is a real comp even when much smaller, and a symmetric 1/20x floor
    excludes every actual peer of a mega-cap industry LEADER (TSLA's 1/20 floor
    is $77B, above all automakers but Toyota). The low-affinity sector tier (3)
    keeps the strict 1/20x floor so breadth fill can't drag in a $5B "peer".
  - positive trailing P/E (loss-makers carry no earnings-multiple information and
    are not trading comps; a NEGATIVE P/E is excluded here)

Tier 3 (cross-industry) is skipped entirely when tiers 1+2 yield ≥3 eligible
names: ≥3 genuine comps stand on their own, and padding an automaker's sheet with
same-sector retailers (Home Depot / McDonald's) only dilutes the median.

Note the MEMBER gate is only ``pe > 0`` — a positive-but-high trailing P/E (AMD
at 156x, ARM at 399x, both textbook NVDA competitors) stays IN the set for the
competitive landscape. The not-meaningful (NM) cap that keeps a distorting
multiple out of the comps_pe MEDIAN lives downstream in
``multiples.calculate_peer_statistics`` / ``calculate_core_pe`` (the touch-5
identity/multiple decoupling): membership and median-eligibility are separate
questions, so AMD can be a peer AND have its 156x trailing print excluded from
the median while its 62.5x FORWARD print drives ``median_forward_pe``.

then rank by |log(mcap / target_mcap)| ascending (ties: alphabetical), filling
``top_n`` slots tier by tier.
"""

from __future__ import annotations

import math
from typing import Any, Final

from finrobot.engine.primitives.industry import semiconductor_role

from pydantic import BaseModel

PEER_SCREEN_TOP_N: Final[int] = 7
"""Slots to fill. 6-8 is the standard comp-sheet size; 7 keeps medians odd."""

PEER_SCREEN_MCAP_BAND: Final[float] = 20.0
"""Eligible market-cap band for the LOW-affinity sector tier: a same-sector but
cross-industry name must be within [1/20, 20]x of the target to be a comp."""

PEER_SCREEN_HIGH_AFFINITY_FLOOR_BAND: Final[float] = 200.0
"""Wider FLOOR divisor for the high-affinity tiers (same industry + stock_peers).

A same-industry or explicitly cross-recommended company is a real trading comp
even when it is much smaller — relative multiples (P/E, EV/EBITDA) are size-
normalised. The symmetric 20x floor breaks for mega-cap industry LEADERS: for
TSLA ($1.5T) the 1/20 floor is $77B, which excludes every actual automaker but
Toyota (GM $75.5B misses by $1.3B; Ferrari/Ford/Honda/Stellantis/Rivian all
below it) — so the sheet backfilled from the Consumer-Cyclical SECTOR with
McDonald's/Home Depot/TJX. The floor is widened to 1/200x for the affinity tiers
(≈$7.7B for TSLA: keeps TM/GM/RACE/Geely, drops micro-cap EV startups) while the
CEILING stays 20x (don't compare UP to a giant). The sector tier keeps the
strict band. Empirically validated 2026-06-09 against TSLA/MSFT/KO/NVDA."""

PEER_SCREEN_MIN_AFFINITY_FOR_SECTOR: Final[int] = 3
"""High-affinity peer count at/above which the cross-industry sector tier is NOT
used. With ≥3 genuine same-industry / cross-recommended comps a sheet stands on
its own; padding it with same-sector-different-industry names (retail for an
automaker) only dilutes the median. Below 3, sector breadth fill is the lesser
evil (some comp signal beats none) — the original mega-cap-thin-industry net."""


class PeerScreenResult(BaseModel):
    """Deterministic screening outcome + the trace that makes it auditable."""

    tickers: list[str]
    """Selected peers, tier order then size-proximity order."""

    tier_of: dict[str, int]
    """Selected ticker → tier (1 = same industry, 2 = stock_peers, 3 = sector)."""

    rationale: str
    """Algorithm trace: pool size → eligibility cuts → per-pick tier/size ratio.

    Replaces the retired LLM free-text rationale so the report's peer list is
    re-derivable by hand instead of justified by prose."""

    dropped_nm: list[str]
    """Eligible-by-size candidates excluded for a non-positive (loss-maker) P/E.

    The MEMBER gate is ``pe > 0`` only — a positive-but-high P/E (AMD 156x, ARM
    399x) stays in the set; the NM cap that keeps a distorting multiple out of the
    median lives downstream in ``multiples``. So this list is loss-makers, not
    high-multiple names (touch-5 identity/multiple decoupling)."""

    dropped_role: list[str] = []
    """Candidates excluded because their value-chain role does not match the target.

    Example: for a fabless/design semiconductor target, foundries (TSM/UMC/GFS)
    and semiconductor equipment vendors (ASML/LRCX/AMAT/KLAC) are suppliers, not
    trading-comps. The rule is deterministic and based on provider profile text,
    not on LLM rationale wording.
    """

    pool_median_pe: float | None
    """Median trailing P/E of the FULL eligible pool (pre-top-N). Baseline for
    the selection tripwire: a selected-set median far from the pool median
    means the top-N slice is unrepresentative of the candidate universe."""

    selected_median_pe: float | None
    """Median trailing P/E of the selected set (selection-stage, as-reported
    caliber — the published comps multiple is recomputed downstream on the
    normalized core caliber; this one only drives the tripwire + trace)."""


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _value_chain_compatible(
    target_profile: dict[str, Any],
    candidate_profile: dict[str, Any] | None,
) -> bool:
    target_role = semiconductor_role(target_profile)
    if target_role is None:
        return True

    candidate_role = semiconductor_role(candidate_profile)
    if candidate_role is None:
        return False

    if target_role == "design":
        return candidate_role in {"design", "semiconductor_other"}
    if target_role in {"foundry", "equipment"}:
        return candidate_role == target_role
    return candidate_role not in {"foundry", "equipment"} or target_role == candidate_role


def screen_peers(
    payload: dict[str, Any],
    target_ticker: str,
    *,
    top_n: int = PEER_SCREEN_TOP_N,
    mcap_band: float = PEER_SCREEN_MCAP_BAND,
    high_affinity_floor_band: float = PEER_SCREEN_HIGH_AFFINITY_FLOOR_BAND,
    min_affinity_for_sector: int = PEER_SCREEN_MIN_AFFINITY_FOR_SECTOR,
    protected_peers: frozenset[str] = frozenset(),
) -> PeerScreenResult:
    """Screen the raw PEER_CANDIDATES payload into a deterministic peer set.

    ``payload`` is the raw dict shipped by the provider
    (``DataType.PEER_CANDIDATES``): profile / stock_peers / industry_screen /
    sector_screen / quotes. Defensive parsing here mirrors the
    forward_estimates precedent — the operator owns interpretation, the
    provider stays raw.

    ``protected_peers`` is the hand-curated commodity-cyclical cohort
    (``cyclical_peers.cyclical_peer_group``) for a memory/storage target — the
    one set the provider's industry tags AND the description-based role
    classifier BOTH fail on. Two failure modes the curated anchor must override:
    (1) a pure storage maker's description carries no semiconductor token, so
    ``semiconductor_role`` returns None and the value-chain gate rejects it
    (Seagate/STX: "global provider of advanced data storage technology", zero
    chip/wafer/semiconductor words — role-dropped while it IS MU's真同业); and
    (2) even a cohort member that survives the role gate (WDC) loses the
    intra-tier size-proximity race to the giant logic-semis also tagged
    "Semiconductors" (AMD $846B / AVGO $1.8T / NVDA $4.95T vs WDC $182B), so it
    never reaches the top-N. A protected member therefore bypasses the role gate
    AND is PINNED to the front of Tier 1 (ahead of size-proximity fill). It
    still must clear the size band + ``pe > 0`` member gate and have a provider
    quote — protection asserts "this is a genuine comp", not "ship it blind".
    Empirically validated 2026-06-14: MU keeps WDC/STX/SNDK instead of a sheet
    of 5 logic semis whose growth-stock P/E mispriced the comps median.

    Raises:
        ValueError: when the target's market cap is unavailable (eligibility
            is undefined without it) — callers degrade the comps step.
    """
    target = target_ticker.strip().upper()
    protected = frozenset(p.strip().upper() for p in protected_peers) - {target}
    profile = payload.get("profile") or {}
    target_profile = profile if isinstance(profile, dict) else {}
    try:
        target_mcap = float(target_profile.get("market_cap") or 0.0)
    except (TypeError, ValueError):
        target_mcap = 0.0
    if target_mcap <= 0:
        raise ValueError(
            f"peer screen for {target}: target market cap unavailable in candidate "
            "payload — size band undefined, comps step must degrade"
        )

    quotes_raw = payload.get("quotes") or {}
    quotes: dict[str, tuple[float, float | None]] = {}
    for sym, q in quotes_raw.items():
        if not isinstance(q, dict):
            continue
        try:
            mcap = float(q.get("market_cap") or 0.0)
        except (TypeError, ValueError):
            continue
        pe_raw = q.get("pe")
        try:
            pe = float(pe_raw) if pe_raw is not None else None
        except (TypeError, ValueError):
            pe = None
        quotes[str(sym).upper()] = (mcap, pe)

    profiles_raw = payload.get("profiles") or {}
    profiles: dict[str, dict[str, Any]] = (
        {str(sym).upper(): p for sym, p in profiles_raw.items() if isinstance(p, dict)}
        if isinstance(profiles_raw, dict)
        else {}
    )

    tiers: list[list[str]] = [
        [str(s).upper() for s in payload.get("industry_screen") or []],
        [str(s).upper() for s in payload.get("stock_peers") or []],
        [str(s).upper() for s in payload.get("sector_screen") or []],
    ]

    def in_band(mcap: float, tier_idx: int) -> bool:
        # Ceiling is the same for every tier (never compare UP to a 20x+ giant).
        # Floor is wider for the high-affinity tiers (1 = same industry, 2 =
        # stock_peers) so a real but smaller peer is not excluded; the low-
        # affinity sector tier (3) keeps the strict symmetric floor.
        if mcap <= 0:
            return False
        floor_band = mcap_band if tier_idx >= 3 else high_affinity_floor_band
        return target_mcap / floor_band <= mcap <= target_mcap * mcap_band

    def meaningful(pe: float | None) -> bool:
        # MEMBER gate only: pe > 0. A loss-maker carries no earnings-multiple
        # information and is not a trading comp. A positive-but-high P/E stays IN
        # the set — the NM cap that keeps a distorting multiple out of the comps_pe
        # MEDIAN is applied downstream in multiples (touch-5 decoupling).
        return pe is not None and pe > 0.0

    def role_ok(sym: str) -> bool:
        # A hand-curated cohort member is a human-verified true comp; the role
        # gate exists to drop value-chain partners the provider text misclassifies,
        # but the cohort is curated BECAUSE that same text fails on it (STX has no
        # semiconductor token → role None → would be rejected). Protection overrides.
        if sym in protected:
            return True
        return _value_chain_compatible(target_profile, profiles.get(sym))

    dropped_nm: list[str] = []
    dropped_role: list[str] = []
    eligible: list[tuple[str, int, float]] = []  # (sym, first-seen tier, pe)
    seen_pool: set[str] = set()
    for tier_idx, tier_syms in enumerate(tiers, start=1):
        for sym in tier_syms:
            if sym == target or sym in seen_pool or sym not in quotes:
                continue
            seen_pool.add(sym)
            mcap, pe = quotes[sym]
            if not in_band(mcap, tier_idx):
                continue
            if not role_ok(sym):
                dropped_role.append(sym)
                continue
            if not meaningful(pe):
                dropped_nm.append(sym)
                continue
            assert pe is not None  # narrowed by meaningful()
            eligible.append((sym, tier_idx, pe))

    # The cross-industry sector tier (3) is breadth fill of last resort: skip it
    # entirely when the high-affinity tiers (1+2) already field a viable set.
    high_affinity_count = sum(1 for _, t, _ in eligible if t <= 2)
    use_sector = high_affinity_count < min_affinity_for_sector
    eligible_pool_pes = [pe for _, t, pe in eligible if use_sector or t <= 2]

    chosen: list[str] = []
    tier_of: dict[str, int] = {}
    trace_picks: list[str] = []
    seen: set[str] = set()
    for tier_idx, tier_syms in enumerate(tiers, start=1):
        if len(chosen) >= top_n:
            break
        if tier_idx >= 3 and not use_sector:
            continue
        # Sort key pins the curated cohort to the FRONT of the tier (0 < 1) so a
        # human-verified true comp can't be evicted from the top-N by a giant
        # logic-semi winning the size-proximity race; within each group, size
        # proximity then ties broken alphabetically (sym) keep determinism.
        ranked = sorted(
            (0 if s in protected else 1, abs(math.log(quotes[s][0] / target_mcap)), s)
            for s in sorted(set(tier_syms))
            if s != target
            and s not in seen
            and s in quotes
            and in_band(quotes[s][0], tier_idx)
            and role_ok(s)
            and meaningful(quotes[s][1])
        )
        for _protected_rank, dist, sym in ranked:
            if len(chosen) >= top_n:
                break
            chosen.append(sym)
            seen.add(sym)
            tier_of[sym] = tier_idx
            trace_picks.append(f"{sym}(T{tier_idx}, {math.exp(dist):.2g}x size)")

    selected_pes = [quotes[s][1] for s in chosen]
    selected_median = _median([p for p in selected_pes if p is not None])
    pool_median = _median(eligible_pool_pes)

    sector_note = (
        f"高亲和层(同行业+互荐) {high_affinity_count} 家 ≥ {min_affinity_for_sector}，"
        "跳过跨行业同板块层"
        if not use_sector
        else f"高亲和层仅 {high_affinity_count} 家 < {min_affinity_for_sector}，"
        f"启用同板块层补足(严格带 [{1 / mcap_band:.2g}x, {mcap_band:.0f}x])"
    )
    rationale = (
        f"确定性筛选：候选池 {len(seen_pool)} 家 → 高亲和层市值带 "
        f"[{1 / high_affinity_floor_band:.3g}x, {mcap_band:.0f}x]（同行业/互荐的真实可比"
        f"不因更小而剔除）+ 价值链角色一致 + 正 P/E（成员门 pe>0，高倍数对手保留入集、"
        f"其失真倍数在中位数处单独 NM）过滤后 "
        f"{len(eligible_pool_pes)} 家（亏损剔除 {len(dropped_nm)} 家"
        f"{'：' + ', '.join(dropped_nm[:6]) if dropped_nm else ''}；"
        f"角色剔除 {len(dropped_role)} 家"
        f"{'：' + ', '.join(dropped_role[:6]) if dropped_role else ''}）；"
        f"{sector_note} → 按 同行业>互荐>同板块 分层、层内规模邻近取 {len(chosen)} 家："
        f"{', '.join(trace_picks)}"
    )

    return PeerScreenResult(
        tickers=chosen,
        tier_of=tier_of,
        rationale=rationale,
        dropped_nm=dropped_nm,
        dropped_role=dropped_role,
        pool_median_pe=pool_median,
        selected_median_pe=selected_median,
    )
