"""Industry classification + bank-caliber helpers for valuation routing.

Pure, zero-I/O. Lives in ``primitives/`` (not ``compute/operators/``) because
BOTH the data layer (``fmp_provider`` net-revenue / gross-margin caliber fixes)
and the compute layer (``cli`` DDM routing) need ``is_bank`` — putting it here
lets a provider import it WITHOUT a data->compute cycle (ADR-0005 §2.2).

Banks differ from non-financials in two ways the generic income-statement
template gets wrong:

1. **Revenue caliber.** A bank's analyst-quoted top line is *total net revenue*
   (net interest income + noninterest income), not the gross sum of total
   interest income + noninterest income. FMP's ``revenue`` field is the gross
   sum; subtracting interest expense recovers the net caliber. Live-verified on
   JPM Q1-2026: FMP ``revenue`` 73.66B − ``interestExpense`` 23.82B = 49.84B,
   which ties to SEC ``us-gaap:RevenuesNetOfInterestExpense`` (49.836B) to the
   penny (= NII 25.37B + noninterest 24.47B).

2. **No COGS.** Banks have no cost of goods sold, so gross profit / gross margin
   are undefined. FMP nonetheless forces its non-bank template and reports a
   ``grossProfit`` / 60.9% gross margin that means nothing; yfinance returns 0%.
   Both must be suppressed (see ``fmp_provider`` / ``extractor``).

Reference: GICS (Global Industry Classification Standard) — sector 40
(Financials) contains banks, insurance, diversified financials.
"""

from __future__ import annotations

import re

# Industries that should use DDM instead of FCF-DCF.
# Based on GICS sub-industry names and common yfinance/FMP labels.
_BANK_INDUSTRIES: frozenset[str] = frozenset(
    {
        "Banks",
        "Banks—Diversified",
        "Banks—Regional",
        "Banks - Diversified",
        "Banks - Regional",
        "Diversified Banks",
        "Regional Banks",
        "Money Center Banks",
        "Major Banks",
        "Savings & Loans",
        "Thrifts & Mortgage Finance",
    }
)

# Broader set: if sector is Financial Services AND industry contains "bank"
_FINANCIAL_SECTOR_NAMES: frozenset[str] = frozenset(
    {
        "Financial Services",
        "Financials",
    }
)

# Commodity / deep-cyclical industries whose earnings swing peak→trough by tens of
# margin points within one business cycle, so the trailing-3y snapshot the generic
# DCF seeds off badly misprices them (Damodaran, *Valuing Cyclical and Commodity
# Companies*). These names need a THROUGH-CYCLE normalized earnings base, not the
# current-regime median. Membership is the PRIMARY gate (a deterministic whitelist,
# the same工程权衡 as ``_BANK_INDUSTRIES``); op-margin volatility is deliberately
# NOT the gate — it假阳's AMD (a turnaround/secular-growth high-vol story, not a
# commodity cycle) while abstaining on names whose margin history the provider
# can't field (empirically: scripts/_cyclical_normalization_validation.py PILLAR 3).
#
# Only UNAMBIGUOUS industry labels live here. Memory/storage names ride the generic
# "Semiconductors" / "Computer Hardware" buckets that ALSO contain non-cyclicals
# (NVDA/AMD; DELL/ANET), so they are gated separately below via keyword收口 on the
# business description and a curated ticker anchor — the industry tag alone can't
# separate MU from NVDA (both "Semiconductors").
_COMMODITY_CYCLICAL_INDUSTRIES: frozenset[str] = frozenset(
    {
        # Marine shipping / freight (charter-rate cyclical)
        "Marine Shipping",
        "Shipbuilding & Marine",
        "Integrated Freight & Logistics",
        # Steel / industrial metals & mining
        "Steel",
        "Aluminum",
        "Other Industrial Metals & Mining",
        "Industrial Metals & Mining",
        "Copper",
        "Coking Coal",  # yfinance form
        "Coal",  # FMP-stable form
        "Gold",
        "Silver",
        "Other Precious Metals",  # FMP-stable (platinum/palladium) — no yfinance bucket equivalent
        # Bulk chemicals
        "Chemicals",
        "Specialty Chemicals",  # yfinance form
        "Chemicals - Specialty",  # FMP-stable form
        "Agricultural Inputs",
        # Oil & gas (upstream / services / refining — NOT midstream pipelines)
        "Oil & Gas E&P",  # yfinance form
        "Oil & Gas Exploration & Production",  # FMP-stable form (DVN/EOG)
        "Oil & Gas Equipment & Services",
        "Oil & Gas Drilling",
        "Oil & Gas Refining & Marketing",
        "Oil & Gas Integrated",
        # Autos (volume-cyclical OEM + parts)
        "Auto Manufacturers",
        "Auto Parts",
    }
)

# Wide industry buckets that CONTAIN commodity-cyclicals but also non-cyclicals.
# A name in one of these is cyclical ONLY when its business description carries a
# memory/storage keyword (keyword收口, §2.3-A) — mirrors ``semiconductor_role``
# below, which also gates on provider profile text.
_AMBIGUOUS_CYCLICAL_BUCKETS: frozenset[str] = frozenset(
    {
        "Semiconductors",  # MU is here, so are NVDA/AMD/AVGO — keyword separates them
        "Computer Hardware",  # WDC/STX/SNDK here, so are DELL/ANET — keyword separates
        "Consumer Electronics",
    }
)

# Memory / storage keywords. A "Semiconductors" / "Computer Hardware" name whose
# description contains one of these is a memory/storage cyclical (DRAM/NAND price
# swings drive the cycle). Lower-cased substring match against the profile text.
_MEMORY_STORAGE_KEYWORDS: tuple[str, ...] = (
    "dram",
    "nand",
    "memory",
    "flash memory",
    "hard disk",
    "hard drive",
    "hdd",
    "solid state drive",
    "solid-state drive",
    "data storage",
    "storage solutions",
)

# Curated memory/storage ticker anchor. The seed path (``seed_dcf_inputs``) only
# carries the provider industry/sector tags — NOT a business description — so the
# keyword收口 above can't fire there for MU/WDC/STX (all generic-tagged). This
# whitelist is the deterministic anchor that makes them cyclical on the seed path,
# the same curated-constant mechanism as ``cyclical_peers._CYCLICAL_PEER_MAP``
# (and kept in sync with it). It is an ANCHOR, never a denylist: a ticker absent
# here still qualifies via industry/keyword. Normalized (upper, no exchange suffix).
_MEMORY_STORAGE_TICKERS: frozenset[str] = frozenset(
    {
        "MU",  # Micron — DRAM/NAND
        "WDC",  # Western Digital — HDD + flash
        "STX",  # Seagate — HDD
        "SNDK",  # Sandisk — NAND flash (2025 spin from WDC)
    }
)


# Provider industry labels drift in punctuation across FMP API vintages: the v3→
# stable migration renamed "Auto Manufacturers" → "Auto - Manufacturers" (hyphen-
# space; live-verified 2026-06-15 across the whole auto sector), silently de-classifying
# every auto OEM because the exact-match whitelists carried only the no-hyphen form.
# (The bank whitelist hand-hedged "Banks—Diversified" + "Banks - Diversified"; the
# cyclical one did not — a sibling-position miss.) Normalize dash variants (em-dash —,
# en-dash –, hyphen -) and whitespace to one canonical form so every label whitelist is
# immune to punctuation drift; the live-label assertion in
# scripts/verify_fmp_stable_migration.py catches residual word-level renames.
_INDUSTRY_NORM_RE = re.compile(r"[—–\-\s]+")


def _norm_industry(label: str) -> str:
    """Lowercase + collapse dash/whitespace runs to a single space (canonical form)."""
    return _INDUSTRY_NORM_RE.sub(" ", label).strip().lower()


_COMMODITY_CYCLICAL_INDUSTRIES_NORM: frozenset[str] = frozenset(
    _norm_industry(s) for s in _COMMODITY_CYCLICAL_INDUSTRIES
)
_AMBIGUOUS_CYCLICAL_BUCKETS_NORM: frozenset[str] = frozenset(
    _norm_industry(s) for s in _AMBIGUOUS_CYCLICAL_BUCKETS
)
_BANK_INDUSTRIES_NORM: frozenset[str] = frozenset(_norm_industry(s) for s in _BANK_INDUSTRIES)
_FINANCIAL_SECTOR_NAMES_NORM: frozenset[str] = frozenset(
    _norm_industry(s) for s in _FINANCIAL_SECTOR_NAMES
)


def is_commodity_cyclical(
    industry: str | None = None,
    sector: str | None = None,
    description: str | None = None,
    ticker: str | None = None,
) -> bool:
    """Detect a commodity / deep-cyclical company that needs through-cycle
    earnings normalization in its DCF seed (Damodaran cyclical口径).

    A company qualifies when ANY of:
    1. Its industry is an unambiguous commodity-cyclical label
       (``_COMMODITY_CYCLICAL_INDUSTRIES``: steel, shipping, oil&gas E&P, autos…).
    2. Its industry is a wide bucket that mixes cyclicals with non-cyclicals
       (``_AMBIGUOUS_CYCLICAL_BUCKETS``: Semiconductors / Computer Hardware /
       Consumer Electronics) AND its business ``description`` carries a
       memory/storage keyword (DRAM/NAND/flash/HDD…). This separates MU from
       NVDA/AMD, and WDC/STX from DELL/ANET, without trusting the industry tag.
    3. Its ``ticker`` is in the curated memory/storage anchor
       (``_MEMORY_STORAGE_TICKERS``). This is the seed-path mechanism: the seed
       carries no description, so the keyword收口 can't fire — the anchor makes
       MU/WDC/STX cyclical there. Never a denylist (absence ≠ non-cyclical).

    Volatility is intentionally NOT a gate (it misclassifies AMD's turnaround
    high-vol as a commodity cycle — PILLAR 3 empirics). Whitelist + keyword +
    anchor are all deterministic and traceable.

    Args:
        industry: Provider industry label (e.g. "Semiconductors").
        sector: Provider sector label (reserved; the industry tag is decisive here).
        description: Business-description text (peer_screen profile / SEC business
            summary). Drives the keyword收口 for the wide buckets. None on the seed
            path → falls through to the ticker anchor.
        ticker: Stock symbol for the curated memory/storage anchor.

    Returns:
        True when the DCF earnings base should be the through-cycle normalized
        median rather than the trailing-3y median.
    """
    if industry and _norm_industry(industry) in _COMMODITY_CYCLICAL_INDUSTRIES_NORM:
        return True
    if industry and _norm_industry(industry) in _AMBIGUOUS_CYCLICAL_BUCKETS_NORM and description:
        text = description.lower()
        if any(kw in text for kw in _MEMORY_STORAGE_KEYWORDS):
            return True
    if ticker and ticker.strip().upper() in _MEMORY_STORAGE_TICKERS:
        return True
    return False


def commodity_cyclical_basis(industry: str | None) -> str:
    """Which arm of ``is_commodity_cyclical`` fired — for honest provenance.

    Only meaningful when ``is_commodity_cyclical`` already returned True for the
    name. ``"industry"`` when the industry label sits in the UNCONDITIONAL
    commodity whitelist (steel / shipping / chemicals / oil&gas / autos…);
    ``"memory_storage"`` otherwise — a True verdict that didn't come from the
    industry list can only have come from the memory/storage keyword收口 or the
    curated ticker anchor (both memory/storage mechanisms).

    Downstream consumers use this to keep the memory-supercycle narrative
    (审校修正 1: "peak priced as perpetual") scoped to memory/storage names —
    a volume-cyclical auto OEM (TSLA/F/GM) must not inherit that framing, its
    price gap is a different story (e.g. option value, not margin permanence).
    """
    if industry and _norm_industry(industry) in _COMMODITY_CYCLICAL_INDUSTRIES_NORM:
        return "industry"
    return "memory_storage"


def profile_text(profile: dict[str, object]) -> str:
    """Lower-cased concatenation of the descriptive profile fields.

    Tolerates both snake_case (``company_name``, our normalized dicts) and
    camelCase (``companyName``, raw FMP rows) so callers don't need to
    pre-normalize.
    """
    parts = [
        profile.get("company_name"),
        profile.get("companyName"),
        profile.get("industry"),
        profile.get("sector"),
        profile.get("description"),
    ]
    return " ".join(str(p).lower() for p in parts if p)


def semiconductor_role(profile: dict[str, object] | None) -> str | None:
    """Classify semiconductor value-chain role from provider profile text.

    Lives in ``primitives/`` because BOTH layers need the SAME predicate:
    ``compute.operators.peer_screen`` uses it to reject value-chain partners
    (foundry/equipment are suppliers, not trading comps), and ``fmp_provider``
    uses it to decide whether per-candidate profile descriptions must be
    fetched at all (FMP stable has no batch profile endpoint, so descriptions
    cost one request per candidate — only semiconductor targets consult them).
    Sharing one function makes "provider fetches profiles" ⇔ "operator reads
    profiles" mechanically equivalent.

    Intentionally narrow: the gate only activates when the target is
    recognisably semiconductor-related; broad technology megacaps stay out of
    a semiconductor comp set unless their profile actually describes chips.

    The role split relies on DESCRIPTION text (e.g. TSM's industry tag is the
    generic "Semiconductors"; only the description carries "foundry"), so a
    candidate profile without a description cannot be classified — callers
    treat that as role-unknown and exclude it rather than guess.
    """
    if not profile:
        return None
    text = profile_text(profile)
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
        # Fab-TOOL / materials-engineering vendors (Applied Materials-class). They
        # sell the TOOLS customers use to fabricate chips — NOT a foundry. Their
        # descriptions carry "wafer fabrication TOOLS" / "materials engineering"
        # (live-verified AMAT 2026-07-03: "provision of materials engineering
        # solutions used to produce semiconductors … critical wafer fabrication
        # tools used for customers to manufacture semiconductors"), which miss the
        # narrow terms above yet greedily match the foundry substring "wafer
        # fabrication" below → AMAT was mis-tagged foundry and slipped into TSM's
        # foundry comp set. These identity terms fire equipment FIRST. No real
        # pure-play foundry (TSM/UMC/GFS/TSEM) uses them (they fabricate chips, they
        # do not sell tools/equipment), so foundry classification is unaffected.
        "fabrication tools",
        "fabrication equipment",
        "manufacturing equipment",
        "materials engineering",
        "process control",
    )
    if any(term in text for term in equipment_terms):
        return "equipment"

    # A pure-play foundry's IDENTITY is being a foundry: it manufactures OTHERS'
    # designs. Live-verified 2026-06-14 against the 4 real pure-plays (TSM/UMC/
    # GFS/TSEM) — each describes itself with one of these and carries NO
    # own-product-design identity. The earlier broad terms ("contract
    # manufacturer", "manufactures, tests/packages") were too loose: they fired on
    # IDMs (designers who fab THEIR OWN products) and dragged NXPI/MCHP/ON into a
    # foundry comp set, diluting the foundry median. NXPI's "contract manufacturer"
    # is only a CUSTOMER type it serves; MCHP's "wafer foundry" is a subcontracting
    # SERVICE line; ON's "foundry" is a govt-only niche — none make them a foundry.
    foundry_terms = (
        "foundry",
        "wafer fabrication",
        "fabrication processes",
    )
    # IDM / design-house own-product identity that disqualifies a foundry verdict
    # even when a foundry word appears incidentally. A pure-play foundry never says
    # it designs+sells its OWN product portfolio nor brings products "to market"
    # (it builds customers' designs). Live-verified 2026-06-14 to catch every
    # foundry-mention IDM in the semiconductor universe — NXPI ("design and
    # production"), MCHP ("creates, produces, and sells"), ON ("designs and
    # develops"), QRVO ("developing and bringing to market"; its "compound
    # semiconductor foundry services" is a defense-prime niche, not its identity) —
    # while matching NONE of TSM/UMC/GFS/TSEM.
    idm_identity_terms = (
        "design and production",
        "designs and produces",
        "designs and develops",
        "designs, develops",
        "designs and sells",
        "designs, manufactures",
        "creates, produces, and sells",
        "design, production",
        "bringing to market",
    )
    if any(term in text for term in foundry_terms) and not any(
        term in text for term in idm_identity_terms
    ):
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


def is_bank(
    industry: str | None = None,
    sector: str | None = None,
) -> bool:
    """Detect whether a company is a bank that should use DDM valuation.

    A company is classified as a bank if:
    1. Its industry exactly matches a known bank industry label, OR
    2. Its sector is Financial Services AND its industry contains "bank"
       (case-insensitive).

    Args:
        industry: Industry string from provider (e.g., "Banks—Diversified").
        sector: Sector string from provider (e.g., "Financial Services").

    Returns:
        True if the company should use DDM instead of FCF-DCF.
    """
    if industry and _norm_industry(industry) in _BANK_INDUSTRIES_NORM:
        return True
    if (
        sector
        and _norm_industry(sector) in _FINANCIAL_SECTOR_NAMES_NORM
        and industry
        and "bank" in industry.lower()
    ):
        return True
    return False


def is_balance_sheet_financial(
    industry: str | None = None,
    sector: str | None = None,  # noqa: ARG001 — accepted for caller symmetry with is_bank; the call is industry-driven (FMP tags every financial sector="Financial Services", so sector has no discriminating power — probe 2026-06-06)
) -> bool:
    """True for issuers whose ENTIRE industry bucket is balance-sheet-funded —
    deposit-taking banks AND risk-carrying (non-broker) insurers — where deposits /
    float / reserves are operating raw material, not capital structure, and there is
    no clean above-the-line EBITDA. These must be valued on P/B · P/TBV · ROTCE · DDM,
    NOT FCF-DCF / EV-EBITDA / P-FCF (those are category errors here).

    This is the SINGLE authority for "suppress the cash-flow valuation methods",
    shared by the numeric-audit verifier (``audit/sector_sign``) and the football-field
    aggregator (``valuation_aggregator`` via ``_helpers`` and the API route). ``is_bank``
    is a STRICTER predicate (banks only) used for DDM routing + bank-specific data
    corrections (net-revenue, bank-beta floor) that insurers must NOT inherit; THIS one
    is the WIDER cash-flow-suppression boundary. Keeping the two distinct is deliberate:
    insurers suppress DCF/EV but do not route to DDM (P/B is their lead).

    Boundary (probe 2026-06-06, FMP industry strings):
    - ``"bank"`` → all "Banks - Diversified/Regional" (incl. foreign ADRs HSBC/MUFG/
      ITUB), deposit-takers. Clean token.
    - ``"insurance"`` BUT NOT ``"broker"`` → "Insurance - Life/Diversified/P&C" carry
      float/reserves; "Insurance - Brokers" (AON/MMC/AJG/BRO/WTW) are asset-light fee
      businesses with a MEANINGFUL EV/EBITDA — must not suppress.
    - "Financial - Capital Markets" is DELIBERATELY NOT suppressed: FMP lumps
      balance-sheet investment banks (GS/MS) with asset-light advisory boutiques
      (EVR/LAZ/PJT) into one indistinguishable string, so suppressing it would
      false-positive the boutiques. A finer split needs a balance-sheet-leverage signal.
    Excluded by construction (EV meaningful, asset-light): "Financial - Credit
    Services" (V/MA), "Asset Management" (BLK), "Financial - Data & Stock Exchanges"
    (ICE/CME/NDAQ), all "REIT - *".
    """
    if not industry:
        return False
    low = industry.lower()
    if "bank" in low:
        return True
    if "insurance" in low and "broker" not in low:
        return True
    return False


def is_non_life_insurer(
    industry: str | None = None,
    sector: str | None = None,  # noqa: ARG001 — caller symmetry; industry-driven like is_balance_sheet_financial
) -> bool:
    """True for a property-casualty / diversified / reinsurance / specialty insurer —
    a risk-carrying insurer that is NOT a life insurer — whose standalone DDM is
    structurally unreliable and must degrade to relative valuation.

    Why the cohort: a non-life insurer's earnings are driven by the underwriting
    cycle, so its trailing ROE swings to a hard-market peak (ALL 42.7% / TRV 24% live
    2026-07-06) that ``g = ROE × (1 − payout)`` extrapolates as perpetual growth; and
    it returns capital mostly via BUYBACK, so its low dividend payout drives a large
    ``terminal_payout / trailing_payout`` step-up. Together these blow the DDM to
    multiples of price even AFTER through-cycle ROE normalization (empirically: ALL
    DDM +530% / TRV +177% / HIG +229% / CB +115% at through-cycle ROE — the residual
    is the low-payout step-up). A LIFE insurer earns a stable spread on reserves and
    pays a high, steady dividend (MET/PRU payout 46-56%, DDM within band at through-
    cycle ROE), so its DDM is legitimate and kept. This is STRICTER than
    ``is_balance_sheet_financial`` (which also suppresses cash-flow methods for banks
    AND life insurers) — it targets ONLY the DDM-unreliable non-life cohort.

    Insurers only reach a DDM via the standalone ``run_ddm_valuation`` tool; the
    research pipeline routes DDM to banks only (``is_bank``), so this predicate is not
    a football-field suppression — it degrades the standalone DDM artifact at source.
    """
    if not industry:
        return False
    low = industry.lower()
    if "insurance" not in low or "broker" in low:
        return False
    return "life" not in low


def bank_net_revenue(
    gross_revenue: float | None,
    interest_expense: float | None,
) -> float | None:
    """Total net revenue for a bank = gross revenue − interest expense.

    FMP's ``revenue`` for a bank is the GROSS sum (total interest income +
    noninterest income). Subtracting interest expense yields *total net revenue*
    (net interest income + noninterest income), the analyst-quoted top line that
    ties to SEC ``RevenuesNetOfInterestExpense`` (JPM Q1-2026: 73.66B − 23.82B =
    49.84B = SEC 49.836B).

    Returns ``None`` when either input is missing (caliber undefined — never
    fabricate by treating a missing interest expense as 0, which would re-serve
    the misleading gross figure).
    """
    if gross_revenue is None or interest_expense is None:
        return None
    return gross_revenue - interest_expense


def bank_operating_income_net_caliber(
    gross_revenue: float | None,
    cost_and_expenses: float | None,
    operating_income: float | None,
) -> float | None:
    """Operating income on the SAME net-revenue caliber as ``bank_net_revenue``.

    A bank's operating_margin divides operating_income by the net-revenue top
    line (gross − interest expense). For that ratio to be single-caliber, the
    numerator must be the operating income measured AGAINST net revenue, i.e.
    interest expense must be netted on the revenue side AND already absorbed as
    an expense in operating income — not double-counted, not omitted.

    FMP builds ``operatingIncome = gross_revenue − costAndExpenses`` and embeds
    interestExpense INSIDE costAndExpenses (live-verified JPM/BAC/WFC/C/GS
    FY2025). When that identity holds, the net-revenue-caliber operating income
    is algebraically IDENTICAL to FMP's ``operatingIncome``::

        net_caliber_OI = net_rev − (costAndExpenses − interest_expense)
                       = (gross − int_exp) − costAndExpenses + int_exp
                       = gross − costAndExpenses
                       = operatingIncome

    so OI / net_revenue is already self-consistent (interest expense nets once on
    each side). The margin is NOT inflated, and re-deriving the numerator would
    DOUBLE-net interest expense (JPM: net_rev − C&E = −25.3B garbage).

    The whole argument rests on ``interestExpense ⊆ costAndExpenses``. The only
    payload-observable proxy for that containment is the identity itself:
    ``gross_revenue − costAndExpenses == operatingIncome``. When it does NOT hold
    (an FMP template that places interest expense outside costAndExpenses, so OI
    never subtracted it), FMP's operatingIncome is a GROSS-caliber figure and
    dividing it by net revenue WOULD be the mixed caliber the naive read fears —
    but we cannot reconstruct the correct numerator without knowing where the
    interest sits, so we ABSTAIN to None rather than emit a misleading margin
    (project信条: never fabricate a number).

    Returns:
        FMP's ``operating_income`` when the identity holds (it already IS the
        net-revenue-caliber figure); ``None`` when any input is missing or the
        identity fails (template anomaly → caliber unverifiable → abstain).
    """
    if gross_revenue is None or cost_and_expenses is None or operating_income is None:
        return None
    # Tolerance: $1M floor or 1bp of gross revenue, whichever is larger —
    # absorbs FMP rounding without admitting a real structural mismatch.
    tol = max(1_000_000.0, abs(gross_revenue) * 1e-4)
    if abs(gross_revenue - cost_and_expenses - operating_income) > tol:
        return None
    return operating_income
