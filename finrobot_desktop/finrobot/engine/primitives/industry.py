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
        "Coking Coal",
        "Gold",
        "Silver",
        # Bulk chemicals
        "Chemicals",
        "Specialty Chemicals",
        "Agricultural Inputs",
        # Oil & gas (upstream / services / refining — NOT midstream pipelines)
        "Oil & Gas E&P",
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
# memory/storage keyword (keyword收口, §2.3-A) — mirrors ``peer_screen.
# _semiconductor_role`` which also gates on provider profile text.
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
    if industry and industry in _COMMODITY_CYCLICAL_INDUSTRIES:
        return True
    if industry and industry in _AMBIGUOUS_CYCLICAL_BUCKETS and description:
        text = description.lower()
        if any(kw in text for kw in _MEMORY_STORAGE_KEYWORDS):
            return True
    if ticker and ticker.strip().upper() in _MEMORY_STORAGE_TICKERS:
        return True
    return False


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
    if industry and industry in _BANK_INDUSTRIES:
        return True
    if sector and sector in _FINANCIAL_SECTOR_NAMES and industry and "bank" in industry.lower():
        return True
    return False


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
