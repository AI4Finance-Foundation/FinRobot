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
