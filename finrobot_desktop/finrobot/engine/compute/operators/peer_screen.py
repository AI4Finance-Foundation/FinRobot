"""Deterministic peer screening for comps (ADR-0014).

What this code does that raw LLM cannot: same candidate payload always yields
the same peer set, with a numeric trace an analyst can re-derive by hand. The
retired LLM selection picked different sets run-to-run, swinging the published
comps_pe target ±30% within one day (MSFT $487 → $636, 2026-06-05) — a number
that moves without the market moving is worse than no number.

Selection = tiered business affinity, then size proximity within tier
(empirically validated 2026-06-05 against MSFT/KO/NVDA/ADBE; pure size
proximity without tiers turned MSFT's comp sheet into a semiconductor basket):

  Tier 1  same FMP industry        (closest business definition)
  Tier 2  FMP stock_peers list     (cross-recommendations, may cross industry)
  Tier 3  same FMP sector          (breadth fill for mega-caps whose industry
                                    slice is too thin at their size)

Within each tier candidates must pass the eligibility screen:
  - market cap within [1/BAND, BAND]x of the target (no $5B "peer" for $3T)
  - meaningful trailing P/E in (0, NM_CAP] — the banker convention that a
    loss-maker or a hyper-growth 159x name carries no information about what a
    mature target's earnings are worth (absolute band, NOT proximity to the
    target's own multiple, so the screen cannot curve-fit the answer)
then rank by |log(mcap / target_mcap)| ascending (ties: alphabetical), filling
``top_n`` slots tier by tier.
"""

from __future__ import annotations

import math
from typing import Any, Final

from pydantic import BaseModel

PEER_SCREEN_TOP_N: Final[int] = 7
"""Slots to fill. 6-8 is the standard comp-sheet size; 7 keeps medians odd."""

PEER_SCREEN_MCAP_BAND: Final[float] = 20.0
"""Eligible market-cap band: peer must be within [1/20, 20]x of the target."""

PEER_SCREEN_PE_NM_CAP: Final[float] = 75.0
"""Trailing P/E above this (or ≤ 0 / missing) is NM — excluded from the sheet."""


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
    """Eligible-by-size candidates excluded for a non-meaningful P/E."""

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


def _profile_text(profile: dict[str, Any]) -> str:
    parts = [
        profile.get("company_name"),
        profile.get("companyName"),
        profile.get("industry"),
        profile.get("sector"),
        profile.get("description"),
    ]
    return " ".join(str(p).lower() for p in parts if p)


def _semiconductor_role(profile: dict[str, Any] | None) -> str | None:
    """Classify semiconductor value-chain role from provider profile text.

    This is intentionally narrow. The gate only activates when the target is
    recognisably semiconductor-related; broad technology megacaps stay out of a
    semiconductor comp set unless their profile actually describes chips.
    """
    if not profile:
        return None
    text = _profile_text(profile)
    if not any(
        token in text
        for token in (
            "semiconductor",
            "integrated circuit",
            "chip",
            "gpu",
            "processor",
            "lithography",
            "wafer",
        )
    ):
        return None

    equipment_terms = (
        "semiconductor equipment",
        "equipment systems",
        "lithography",
        "metrology",
        "inspection systems",
        "wafer processing equipment",
        "deposition",
        "etch",
    )
    if any(term in text for term in equipment_terms):
        return "equipment"

    foundry_terms = (
        "foundry",
        "wafer fabrication",
        "fabrication processes",
        "contract manufacturer",
        "contract manufacturing",
        "manufactures, packages, tests",
        "manufactures, packages, and tests",
        "manufactures, tests",
    )
    if any(term in text for term in foundry_terms):
        return "foundry"

    design_terms = (
        "designs",
        "develops",
        "supplies semiconductor",
        "integrated circuits",
        "microprocessors",
        "graphics processing",
        "gpu",
        "chipsets",
        "system-on-chip",
        "data center platforms",
    )
    if any(term in text for term in design_terms):
        return "design"

    return "semiconductor_other"


def _value_chain_compatible(
    target_profile: dict[str, Any],
    candidate_profile: dict[str, Any] | None,
) -> bool:
    target_role = _semiconductor_role(target_profile)
    if target_role is None:
        return True

    candidate_role = _semiconductor_role(candidate_profile)
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
    pe_nm_cap: float = PEER_SCREEN_PE_NM_CAP,
) -> PeerScreenResult:
    """Screen the raw PEER_CANDIDATES payload into a deterministic peer set.

    ``payload`` is the raw dict shipped by the provider
    (``DataType.PEER_CANDIDATES``): profile / stock_peers / industry_screen /
    sector_screen / quotes. Defensive parsing here mirrors the
    forward_estimates precedent — the operator owns interpretation, the
    provider stays raw.

    Raises:
        ValueError: when the target's market cap is unavailable (eligibility
            is undefined without it) — callers degrade the comps step.
    """
    target = target_ticker.strip().upper()
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

    def in_band(mcap: float) -> bool:
        return mcap > 0 and 1.0 / mcap_band <= mcap / target_mcap <= mcap_band

    def meaningful(pe: float | None) -> bool:
        return pe is not None and 0.0 < pe <= pe_nm_cap

    def role_ok(sym: str) -> bool:
        return _value_chain_compatible(target_profile, profiles.get(sym))

    dropped_nm: list[str] = []
    dropped_role: list[str] = []
    eligible_pool_pes: list[float] = []
    seen_pool: set[str] = set()
    for tier_syms in tiers:
        for sym in tier_syms:
            if sym == target or sym in seen_pool or sym not in quotes:
                continue
            seen_pool.add(sym)
            mcap, pe = quotes[sym]
            if not in_band(mcap):
                continue
            if not role_ok(sym):
                dropped_role.append(sym)
                continue
            if not meaningful(pe):
                dropped_nm.append(sym)
                continue
            assert pe is not None  # narrowed by meaningful()
            eligible_pool_pes.append(pe)

    chosen: list[str] = []
    tier_of: dict[str, int] = {}
    trace_picks: list[str] = []
    seen: set[str] = set()
    for tier_idx, tier_syms in enumerate(tiers, start=1):
        if len(chosen) >= top_n:
            break
        ranked = sorted(
            (abs(math.log(quotes[s][0] / target_mcap)), s)
            for s in sorted(set(tier_syms))
            if s != target
            and s not in seen
            and s in quotes
            and in_band(quotes[s][0])
            and role_ok(s)
            and meaningful(quotes[s][1])
        )
        for dist, sym in ranked:
            if len(chosen) >= top_n:
                break
            chosen.append(sym)
            seen.add(sym)
            tier_of[sym] = tier_idx
            trace_picks.append(f"{sym}(T{tier_idx}, {math.exp(dist):.2g}x size)")

    selected_pes = [quotes[s][1] for s in chosen]
    selected_median = _median([p for p in selected_pes if p is not None])
    pool_median = _median(eligible_pool_pes)

    rationale = (
        f"确定性筛选：候选池 {len(seen_pool)} 家 → 市值带 [{1 / mcap_band:.2g}x, "
        f"{mcap_band:.0f}x] + 价值链角色一致 + P/E 有意义 (0, {pe_nm_cap:.0f}] 过滤后 "
        f"{len(eligible_pool_pes)} 家（NM 剔除 {len(dropped_nm)} 家"
        f"{'：' + ', '.join(dropped_nm[:6]) if dropped_nm else ''}；"
        f"角色剔除 {len(dropped_role)} 家"
        f"{'：' + ', '.join(dropped_role[:6]) if dropped_role else ''}）→ "
        f"按 同行业>互荐>同板块 分层、层内规模邻近取 {len(chosen)} 家："
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
