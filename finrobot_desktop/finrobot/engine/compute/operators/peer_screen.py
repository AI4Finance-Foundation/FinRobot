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
``top_n`` slots tier by tier — with one re-ordering rule for the high-affinity
tiers (the mega-cap tier fix, 2026-07-07): a Tier-1/Tier-2 candidate whose size
gap vs the target exceeds ``PEER_SCREEN_SIZE_GAP_DEMOTE`` is DEMOTED behind both
near tiers into a single "far" pool ranked globally by size proximity. Tier
priority is a proxy for business affinity, but for a $2.9T target a same-industry
label 30x away carries less comp information than a cross-recommended mega-cap
1.5x away: MSFT's Software-Infrastructure Tier 1 fields 20 mid-caps that ate all
7 slots by same-tier size proximity while FMP's own stock_peers cross-
recommendations (AAPL/GOOGL/NVDA, ~1.6x) never got a slot — pricing MSFT off a
PLTR/PANW-median forward P/E (a +61% re-rating premise, 2026-07-07 external
review). Candidates within the gap keep exact tier order, so a small/mid-cap
target whose Tier 1 is size-adjacent is untouched; a curated/protected cohort
member is NEVER demoted (curation must beat every downstream gate — the
2026-06-14 MU lesson: WDC/STX sit >5x from MU and are precisely the members the
demotion would otherwise evict).
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
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

PEER_SCREEN_SIZE_GAP_DEMOTE: Final[float] = 5.0
"""Size-gap ratio (max/min vs the target) beyond which a HIGH-affinity candidate
(Tier 1 same-industry or Tier 2 stock_peers) loses its tier priority and is
demoted into the shared "far" pool drained AFTER both near tiers, ranked
globally by size proximity. Within the gap, tier order is untouched.

Calibration (2026-07-07, lead-signed, probed at G ∈ {3, 5, 7} on the
MSFT/AAPL/GOOGL/NVDA/AMZN/KO/JPM/MU/TSLA basket): 7/9 tickers keep an
identical set across the whole G range (their high-affinity candidates are
size-adjacent, or the far pool refills in the same proximity order), so the
value is structurally insensitive; G=5 is the robust midpoint. What it fixes:
a mega-cap whose same-industry tier holds only names 7–90x smaller (MSFT,
GOOGL) now leads with its cross-recommended true peers (~1.5x) instead of
letting Tier-1 label priority anchor the comps median on mid-caps. Ordinary
leader premia over genuine same-size peers (2–3x gaps) are untouched. NOT a
financial calibration of any multiple — it re-orders selection priority only;
eligibility (band / role / P/E member gates) and the sector-tier rule are
unchanged, and a protected/curated member is never demoted."""

PEER_ISSUER_MCAP_RATIO_TOL: Final[float] = 3.0
"""Same-issuer dedup guard: two candidates are only collapsed as ONE issuer when
their market caps agree within this ratio (max/min ≤ 3). Two listings of one
company (RY.TO / RY — Royal Bank of Canada on Toronto vs NYSE) carry a near-equal
market cap once FX-normalised (≈1x); dual-class shares (GOOGL / GOOG) differ only
by the class float split (≈1.05x). The identity signal is the normalized company
NAME; this size band is only a sanity guard that stops a name-normalization
collision (two DIFFERENT firms whose names collapse to the same token) from
merging a $10B name-twin into a $300B issuer. 3x leaves margin for quote-timing /
share-count drift while still blocking any real size mismatch."""

# Legal-form + share-class tokens stripped from a company name before comparing
# issuer identity. Deliberately conservative — legal suffixes and class markers
# ONLY, never semantic words like HOLDINGS / GROUP / AMERICAN — so distinct
# issuers that merely share a common word are NOT collapsed (the Coca-Cola family
# KO / KOF / COKE / CCEP each normalize to a DIFFERENT token, so they never merge).
_ISSUER_NAME_NOISE_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "THE",
        "INC",
        "INCORPORATED",
        "CORP",
        "CORPORATION",
        "CO",
        "COMPANY",
        "LTD",
        "LIMITED",
        "LLC",
        "LLP",
        "LP",
        "PLC",
        "SA",
        "SAB",
        "AG",
        "NV",
        "SE",
        "AB",
        "ASA",
        "OYJ",
        "SPA",
        "KGAA",
        "GMBH",
        "CLASS",
        "CL",
        "SERIES",
        "SER",
        "ADR",
    }
)


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

    dropped_non_common: list[str] = []
    """Candidates excluded as a NON-common-stock listing (preferred / warrant / unit /
    right), which are not trading comps for a common-equity valuation.

    A preferred listing (FMP ``MER-PK`` = Merrill Lynch preferred series K, ``RY-PZ``,
    ``BAC-PB``) trades on its coupon near par (~$25), not on the issuer's common
    equity, and FMP attributes the PARENT's market cap + income statement to it — so
    it double-weights the parent AND its bank net-revenue caliber collapses to
    non-positive, which then failed the WHOLE peer set's sanity check (Citigroup
    comps 2026-07-02: MER-PK → statistical_bench degraded → median_pb=None, a single
    bad listing crashing the report). Dropped here so it never enters the set; the
    same-issuer dedup only caught the ones whose common was ALSO present (RY-PZ.TO
    beside RY), which is why MER-PK slipped through.
    """

    dropped_duplicate: list[str] = []
    """Candidates excluded as the redundant listing of an issuer already in the set.

    A company cross-listed on two exchanges (RY.TO Toronto + RY NYSE = Royal Bank
    of Canada) or carrying dual share classes (GOOGL + GOOG = Alphabet) arrives as
    two candidate tickers with near-identical market cap. Counting both double-
    weights that one issuer in the peer MEDIAN (JPM's median P/B was inflated +26%
    by RY.TO and RY both landing in the set, 2026-07-02). The redundant listing —
    the exchange-suffixed / non-target-market one — is dropped here so each issuer
    contributes to the median exactly once; the surviving primary listing keeps its
    slot and the freed slot is refilled from the pool.
    """

    dropped_delisted: list[str] = []
    """Candidates excluded as a delisted / renamed listing the provider flags
    ``isActivelyTrading=False``.

    A dead ticker freezes at its last trade with a stale market cap (VMware ``VMW``,
    absorbed into Broadcom 2023, prints a ~$61B cap at a frozen $142.48; old Block
    ``SQ``, renamed ``XYZ`` in 2025, prints a stale cap) — it is not a live trading
    comp and pollutes the peer median / competitive landscape. Only an EXPLICIT
    ``False`` lands here; a candidate whose liveness is UNKNOWN (absent from the
    payload's ``active`` map — a stale pre-``active`` cache row, or a stock-peers-only
    name whose profile fetch failed) is NOT dropped, so a missing signal never
    mis-kills a live peer. A protected/curated cohort member flagged inactive is kept
    (curation override) and disclosed in the rationale, not listed here.
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


def _normalize_issuer_name(name: str) -> str:
    """Collapse a company name to a stable issuer key for cross-listing dedup.

    Uppercases, drops punctuation, removes legal-form / share-class noise tokens
    (``_ISSUER_NAME_NOISE_TOKENS``) and any trailing single-letter class marker,
    then joins the rest with no separators. "Royal Bank of Canada" (RY and RY.TO
    both) → ``ROYALBANKOFCANADA``; "Alphabet Inc. Class A" / "Alphabet Inc." →
    ``ALPHABET``. Returns ``""`` for an empty/absent name (no identity → the caller
    falls back to the base symbol and never merges on an empty key)."""
    cleaned = "".join(ch if ch.isalnum() else " " for ch in name.upper())
    tokens = [t for t in cleaned.split() if t and t not in _ISSUER_NAME_NOISE_TOKENS]
    while tokens and len(tokens[-1]) == 1 and tokens[-1].isalpha():
        tokens.pop()  # trailing class letter ("ALPHABET A")
    return "".join(tokens)


# Preferred-share listings are not common-equity trading comps. FMP encodes them
# with a ``-P<series>`` class segment after a HYPHEN: ``MER-PK`` (Merrill Lynch pref
# series K), ``RY-PZ``, ``BAC-PB``, ``WFC-PL``, ``TD-PFK`` (P + multi-letter series),
# and bare ``-P``. Common-stock DUAL-CLASS listings ALSO use a hyphen (BRK-B, HEI-A,
# GEF-B) — those are real comps, so we match ONLY a ``P``-prefixed class code (which
# only preferred uses), never a bare ``-A``/``-B`` class letter. Checked against the
# base symbol (exchange suffix ``.TO`` stripped first).
_PREFERRED_TICKER_RE: Final[re.Pattern[str]] = re.compile(r"-P[A-Z]{0,3}$")
# Name-based backstop for a non-common listing whose ticker carries NO ``-P`` marker
# (a bare 3-letter symbol) — the case the ticker regex above misses entirely. FMP
# lists a preferred / baby-bond under a plain symbol named after its PARENT plus an
# instrument descriptor (AEB "Aegon N.V. PERP CAP FLTG RT", AED "PERP CAP SECS",
# AEH "PRP CP SEC 6.375", ATHS "Athene Holding Ltd. 7.250% Fixe"): these fetch the
# PARENT's balance sheet against a ~$25-par price → a garbage ~6x P/B that dragged
# HIG's / AIG's insurer P/B median to 2-4x the true value (2026-07-06). The tokens
# are the perpetual-capital / capital-securities / subordinated-note phrases specific
# to preferreds — deliberately multi-word ("CAP SEC", not bare "CAP") so a real name
# like "Arch Capital" / "Ares Capital" / "Aegon Ltd." (the actual common) is untouched.
_NON_COMMON_NAME_TOKENS: Final[tuple[str, ...]] = (
    "PFD",
    "PREF",
    "PREFERRED",
    "WARRANT",
    "PERP CAP",
    "PRP CP",
    "CAP SEC",
    "CAP FLTG",
    "CP SEC",
    "SUBORDINAT",
    "DEBENTURE",
)
# A coupon rate spelled into the name ("7.250%", "6.375%", "5.5%") is a preferred /
# note / baby-bond signature — a common-equity name never carries a rate. The primary
# general catch for the bare-symbol preferreds the token list can't enumerate.
_COUPON_RATE_RE: Final[re.Pattern[str]] = re.compile(r"\d\.\d{1,3}\s*%")


def _is_non_common_listing(ticker: str, raw_name: str) -> bool:
    """Whether a candidate is a non-common-stock listing (preferred / warrant / …),
    which must not enter a common-equity comp set."""
    base = ticker.upper().split(".", 1)[0]
    if _PREFERRED_TICKER_RE.search(base):
        return True
    up = raw_name.upper()
    if any(tok in up for tok in _NON_COMMON_NAME_TOKENS):
        return True
    return _COUPON_RATE_RE.search(up) is not None


def _base_symbol(ticker: str) -> str:
    """Ticker with any exchange suffix stripped (``RY.TO`` → ``RY``, ``RY`` → ``RY``).

    Used only as the FALLBACK issuer key when a company name is unavailable — a
    shared base symbol across a suffixed / unsuffixed pair is a strong cross-listing
    signal (also covers dual-class dotted US tickers ``BRK.A`` / ``BRK.B``)."""
    return ticker.upper().split(".", 1)[0]


def _has_exchange_suffix(ticker: str) -> bool:
    """Whether the ticker carries an exchange suffix (a ``.`` segment, e.g. ``.TO``).

    Drives the "keep the primary listing" rule: within a same-issuer group the
    unsuffixed listing (the US / target-market ticker ``RY``) is preferred over the
    exchange-suffixed one (``RY.TO``)."""
    return "." in ticker


def _same_issuer(
    mcap_a: float,
    name_a: str,
    base_a: str,
    mcap_b: float,
    name_b: str,
    base_b: str,
) -> bool:
    """Whether two candidates are the SAME issuer (a cross-listing / dual-class pair).

    Requires the market caps to agree within ``PEER_ISSUER_MCAP_RATIO_TOL`` (the
    sanity guard), then: when BOTH normalized names are present, the names are
    authoritative — equal ⇒ same issuer, different ⇒ different issuer even if the
    base symbols coincide (this is the veto that stops the same ticker string
    meaning different companies on two exchanges from merging). When a name is
    missing (a stale payload without the ``names`` map) it falls back to base-symbol
    equality. Either market cap ≤ 0 → never merge (fail-safe: keep both)."""
    if mcap_a <= 0 or mcap_b <= 0:
        return False
    if max(mcap_a, mcap_b) / min(mcap_a, mcap_b) > PEER_ISSUER_MCAP_RATIO_TOL:
        return False
    if name_a and name_b:
        return name_a == name_b
    return base_a == base_b


def screen_peers(
    payload: dict[str, Any],
    target_ticker: str,
    *,
    top_n: int = PEER_SCREEN_TOP_N,
    mcap_band: float = PEER_SCREEN_MCAP_BAND,
    high_affinity_floor_band: float = PEER_SCREEN_HIGH_AFFINITY_FLOOR_BAND,
    min_affinity_for_sector: int = PEER_SCREEN_MIN_AFFINITY_FOR_SECTOR,
    protected_peers: frozenset[str] = frozenset(),
    size_gap_demote: float = PEER_SCREEN_SIZE_GAP_DEMOTE,
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

    # Liveness (isActivelyTrading) per candidate. Only genuine booleans are kept:
    # an absent sym is UNKNOWN, not dead, so an old pre-``active`` cache payload (no
    # key at all) or a candidate the provider couldn't classify is never dropped for
    # liveness. The gate below acts ONLY on an explicit ``active[sym] is False``.
    active_raw = payload.get("active") or {}
    active: dict[str, bool] = {}
    if isinstance(active_raw, dict):
        for sym, val in active_raw.items():
            if isinstance(val, bool):
                active[str(sym).upper()] = val

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

    # ── Same-issuer dedup (cross-listing / dual-class) ────────────────────────
    # A company reachable under two tickers (RY.TO Toronto + RY NYSE = Royal Bank
    # of Canada; GOOGL + GOOG = Alphabet) must count ONCE, or its multiple double-
    # weights the peer median (JPM median P/B +26%, 2026-07-02). Issuer identity =
    # normalized company name (authoritative) with a market-cap sanity band; the
    # base symbol is the fallback key when a name is unavailable. Names come from
    # the provider's top-level ``names`` map, falling back to the semiconductor
    # ``profiles`` company_name (the only target class that ships profiles).
    names_raw = payload.get("names") or {}
    cand_names: dict[str, str] = {}
    if isinstance(names_raw, dict):
        for sym, nm in names_raw.items():
            cand_names[str(sym).upper()] = _normalize_issuer_name(str(nm or ""))
    for sym, prof in profiles.items():
        if sym not in cand_names or not cand_names[sym]:
            cand_names[sym] = _normalize_issuer_name(str(prof.get("company_name") or ""))
    target_name = _normalize_issuer_name(str(target_profile.get("company_name") or ""))
    target_base = _base_symbol(target)

    def _name_of(sym: str) -> str:
        return cand_names.get(sym, "")

    # Raw (un-normalized) candidate names for the non-common-listing name backstop —
    # ``cand_names`` above is normalized (legal-form/class tokens stripped), which
    # would swallow a "preferred" token before it can be matched.
    raw_names: dict[str, str] = {}
    if isinstance(names_raw, dict):
        for sym, nm in names_raw.items():
            raw_names[str(sym).upper()] = str(nm or "")
    for sym, prof in profiles.items():
        raw_names.setdefault(sym, str(prof.get("company_name") or ""))

    # Preferred / warrant / other non-common listings are not common-equity trading
    # comps; drop them before selection. A preferred (MER-PK) trades near par, carries
    # the PARENT's market cap + income statement, and its bank net-revenue caliber goes
    # non-positive — which failed the WHOLE peer set's sanity check (C comps 2026-07-02).
    # The same-issuer dedup only caught preferred whose common was ALSO in the set
    # (RY-PZ.TO beside RY); this is the general catch.
    non_common_drop: set[str] = {
        sym
        for tier_syms in tiers
        for sym in tier_syms
        if sym != target and _is_non_common_listing(sym, raw_names.get(sym, ""))
    }
    dropped_non_common = sorted(s for s in non_common_drop if s in quotes)

    # Candidates that could actually be selected (a quote + inside their tier's
    # band). Grouping over these keeps the primary listing selectable and shares
    # band-membership across the cross-listing pair.
    first_tier: dict[str, int] = {}
    for tier_idx, tier_syms in enumerate(tiers, start=1):
        for sym in tier_syms:
            if sym == target or sym not in quotes:
                continue
            first_tier.setdefault(sym, tier_idx)
    band_ok = [s for s, t in first_tier.items() if in_band(quotes[s][0], t)]

    def _keep_rank(sym: str) -> tuple[int, int, int, float, str]:
        # Lower = kept. Prefer a curated/protected member, then a LIVE listing over a
        # delisted / renamed one, then the primary listing (no exchange suffix = US /
        # target-market ticker), then the larger cap (more-liquid listing), ties broken
        # alphabetically for determinism. The liveness key demotes ONLY an explicit
        # isActivelyTrading=False — UNKNOWN ranks WITH live (``is not False``) so a pair
        # whose liveness is unknown (RY / RY.TO) still resolves on the no-suffix key
        # exactly as before. This is what keeps the live listing of a same-issuer pair:
        # old Block SQ (False) loses to XYZ (True) even though SQ's stale frozen cap is
        # the larger of the two (which would otherwise win the -cap tiebreak).
        return (
            0 if sym in protected else 1,
            0 if active.get(sym) is not False else 1,
            1 if _has_exchange_suffix(sym) else 0,
            -quotes[sym][0],
            sym,
        )

    dup_drop: set[str] = set()
    # A candidate that IS the target under another listing is a self-comp — drop it.
    remaining: list[str] = []
    for sym in band_ok:
        if _same_issuer(
            quotes[sym][0], _name_of(sym), _base_symbol(sym), target_mcap, target_name, target_base
        ):
            dup_drop.add(sym)
        else:
            remaining.append(sym)
    # Group the rest by issuer identity; keep one primary listing per group.
    issuer_groups: list[list[str]] = []
    for sym in remaining:
        for group in issuer_groups:
            rep = group[0]
            if _same_issuer(
                quotes[sym][0],
                _name_of(sym),
                _base_symbol(sym),
                quotes[rep][0],
                _name_of(rep),
                _base_symbol(rep),
            ):
                group.append(sym)
                break
        else:
            issuer_groups.append([sym])
    for group in issuer_groups:
        if len(group) > 1:
            primary = min(group, key=_keep_rank)
            dup_drop.update(s for s in group if s != primary)
    dropped_duplicate = sorted(dup_drop)

    dropped_nm: list[str] = []
    dropped_role: list[str] = []
    dropped_delisted: list[str] = []
    protected_inactive: list[str] = []  # curated members the provider flags inactive
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
            if sym in dup_drop:
                # Redundant listing of an issuer kept elsewhere in the set (or the
                # target itself under another ticker) — already in dropped_duplicate.
                # (A dead listing of an issuer whose live listing is kept lands HERE,
                # not in dropped_delisted: the same-issuer dedup already resolved the
                # pair to the live one via _keep_rank's liveness key.)
                continue
            if sym in non_common_drop:
                # Preferred / warrant / non-common listing — already in
                # dropped_non_common; not a common-equity trading comp.
                continue
            if active.get(sym) is False:
                # Delisted (VMware VMW) or renamed-ticker (old Block SQ) — the provider
                # flags it isActivelyTrading=False; it is frozen at a stale price / cap,
                # not a live trading comp. A curated/protected cohort member is KEPT
                # regardless (the curation override must beat every downstream gate — the
                # 2026-06-14 MU lesson) and the override is disclosed in the rationale.
                # UNKNOWN (absent) is not False, so it passes untouched.
                if sym in protected:
                    protected_inactive.append(sym)
                else:
                    dropped_delisted.append(sym)
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

    def _eligible(s: str, tier_idx: int) -> bool:
        return (
            s != target
            and s not in seen
            and s not in dup_drop
            and s not in non_common_drop
            # Delisted / renamed listing (isActivelyTrading=False) is not a live comp —
            # mirror the eligibility gate. Protected/curated members override (kept).
            and not (active.get(s) is False and s not in protected)
            and s in quotes
            and in_band(quotes[s][0], tier_idx)
            and role_ok(s)
            and meaningful(quotes[s][1])
        )

    def _near(s: str) -> bool:
        # Within the size-gap band → keeps its tier priority. A protected/curated
        # member is NEVER demoted: WDC/STX sit >5x from MU and are exactly the
        # members the curation exists to keep (2026-06-14 lesson — curation must
        # beat every downstream gate, and demotion is a downstream gate).
        if s in protected:
            return True
        mcap = quotes[s][0]
        return max(mcap, target_mcap) / min(mcap, target_mcap) <= size_gap_demote

    def _fill(
        ranked: list[tuple[int, float, str]], origin: dict[str, int] | int, far: bool
    ) -> None:
        for _protected_rank, dist, sym in ranked:
            if len(chosen) >= top_n:
                return
            t = origin[sym] if isinstance(origin, dict) else origin
            chosen.append(sym)
            seen.add(sym)
            tier_of[sym] = t
            trace_picks.append(f"{sym}(T{t}{'→far' if far else ''}, {math.exp(dist):.2g}x size)")

    # Sort key pins the curated cohort to the FRONT of its group (0 < 1) so a
    # human-verified true comp can't be evicted from the top-N by a giant
    # logic-semi winning the size-proximity race; within each group, size
    # proximity then ties broken alphabetically (sym) keep determinism.
    def _ranked(
        syms: Iterable[str], tier_idx: int, *, near: bool | None
    ) -> list[tuple[int, float, str]]:
        # ``near=True`` keeps only candidates inside the size-gap band (the near
        # high-affinity stages); ``near=None`` applies no gap filter at all (the
        # sector tier — its own strict band already caps at 20x and the demotion
        # rule deliberately does not touch it).
        return sorted(
            (0 if s in protected else 1, abs(math.log(quotes[s][0] / target_mcap)), s)
            for s in syms
            if _eligible(s, tier_idx) and (near is None or _near(s) == near)
        )

    # Demoted far pool: high-affinity (Tier 1 + Tier 2) candidates beyond the size
    # gap, keyed by first-seen tier (a sym listed in both keeps the T1 label).
    # Drained AFTER both near tiers, ranked GLOBALLY by size proximity — past the
    # gap, tier labels are weak affinity proxies and a cross-recommended 7x name
    # should beat a same-industry 30x one (and vice versa).
    far_origin: dict[str, int] = {}
    for tier_idx, tier_syms in enumerate(tiers[:2], start=1):
        for s in sorted(set(tier_syms)):
            if s not in far_origin and _eligible(s, tier_idx) and not _near(s):
                far_origin[s] = tier_idx

    # Near high-affinity tiers first, exact tier order — unchanged behaviour for a
    # size-adjacent tier (the small/mid-cap common case, and every protected member).
    for tier_idx, tier_syms in enumerate(tiers[:2], start=1):
        if len(chosen) >= top_n:
            break
        _fill(_ranked(sorted(set(tier_syms)), tier_idx, near=True), tier_idx, far=False)
    if len(chosen) < top_n and far_origin:
        far_ranked = sorted(
            (0 if s in protected else 1, abs(math.log(quotes[s][0] / target_mcap)), s)
            for s, t in far_origin.items()
            if _eligible(s, t)
        )
        _fill(far_ranked, far_origin, far=True)
    # Sector breadth fill of last resort — untouched by the demotion rule (its own
    # strict band already excludes anything beyond 20x).
    if len(chosen) < top_n and use_sector:
        _fill(_ranked(sorted(set(tiers[2])), 3, near=None), 3, far=False)

    selected_pes = [quotes[s][1] for s in chosen]
    selected_median = _median([p for p in selected_pes if p is not None])
    pool_median = _median(eligible_pool_pes)

    sector_note = (
        f"high-affinity tier (same industry + mutual-rec) {high_affinity_count} firms "
        f">= {min_affinity_for_sector}, skipping the cross-industry same-sector tier"
        if not use_sector
        else f"high-affinity tier only {high_affinity_count} firms < {min_affinity_for_sector}, "
        f"enabling the same-sector tier to top up (strict band [{1 / mcap_band:.2g}x, {mcap_band:.0f}x])"
    )
    if far_origin:
        # Demotion is a re-ordering, not a drop — but the trace must still say who
        # was demoted and why, or the tier labels in the picks read as contradictory
        # (a T2 pick ahead of T1 names). Mirrors the cap-trim naming lesson
        # (2026-07-03): every silently re-ranked candidate is a broken audit trail.
        sector_note += (
            f"; {len(far_origin)} high-affinity candidate(s) beyond the {size_gap_demote:.0f}x "
            f"size gap demoted behind the near tiers into a global size-proximity pool "
            f"(mega-cap tier fix: tier priority is an affinity proxy and stops outranking "
            f"size past that gap)"
        )
    rationale = (
        f"Deterministic screen: candidate pool {len(seen_pool)} firms -> high-affinity market-cap band "
        f"[{1 / high_affinity_floor_band:.3g}x, {mcap_band:.0f}x] (genuine same-industry / mutual-rec "
        f"comparables are not dropped for being smaller) + consistent value-chain role + positive P/E "
        f"(membership gate pe>0; high-multiple peers are kept in the set, their distorted multiple marked "
        f"NM only at the median) -> after filtering, "
        f"{len(eligible_pool_pes)} firms (loss-making dropped {len(dropped_nm)}"
        f"{': ' + ', '.join(dropped_nm[:6]) if dropped_nm else ''}; "
        f"role-dropped {len(dropped_role)}"
        f"{': ' + ', '.join(dropped_role[:6]) if dropped_role else ''}; "
        f"non-common (preferred/warrant) dropped {len(dropped_non_common)}"
        f"{': ' + ', '.join(dropped_non_common[:6]) if dropped_non_common else ''}; "
        f"same-issuer duplicate listing dropped {len(dropped_duplicate)}"
        f"{': ' + ', '.join(dropped_duplicate[:6]) if dropped_duplicate else ''}; "
        f"delisted/renamed (inactive) dropped {len(dropped_delisted)}"
        f"{': ' + ', '.join(dropped_delisted[:6]) if dropped_delisted else ''}); "
        f"{sector_note} -> tiered by same-industry > mutual-rec > same-sector, "
        f"picking {len(chosen)} firms by within-tier size proximity: "
        f"{', '.join(trace_picks)}"
    )
    if protected_inactive:
        # Rare: a curated cohort member (e.g. a storage peer for MU) the provider flags
        # inactive. It is kept by the curation override (it beat the liveness gate), so
        # the analyst-facing trace must disclose the override rather than hide it.
        rationale += (
            f" [curation override: {', '.join(sorted(set(protected_inactive)))} flagged "
            f"inactive by provider (isActivelyTrading=false) but kept as curated peer(s)]"
        )

    return PeerScreenResult(
        tickers=chosen,
        tier_of=tier_of,
        rationale=rationale,
        dropped_nm=dropped_nm,
        dropped_role=dropped_role,
        dropped_non_common=dropped_non_common,
        dropped_duplicate=dropped_duplicate,
        dropped_delisted=dropped_delisted,
        pool_median_pe=pool_median,
        selected_median_pe=selected_median,
    )
