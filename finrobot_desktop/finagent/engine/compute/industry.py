"""Industry classification utilities for valuation model routing.

Banks should use DDM (not FCF-DCF) because they don't have traditional
free cash flow. This module detects bank/financial companies from
sector and industry strings returned by data providers (FMP, yfinance).

Reference: GICS (Global Industry Classification Standard) — sector 40
(Financials) contains banks, insurance, diversified financials.
"""
from __future__ import annotations

# Industries that should use DDM instead of FCF-DCF.
# Based on GICS sub-industry names and common yfinance/FMP labels.
_BANK_INDUSTRIES: frozenset[str] = frozenset({
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
})

# Broader set: if sector is Financial Services AND industry contains "bank"
_FINANCIAL_SECTOR_NAMES: frozenset[str] = frozenset({
    "Financial Services",
    "Financials",
})


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
    if (
        sector
        and sector in _FINANCIAL_SECTOR_NAMES
        and industry
        and "bank" in industry.lower()
    ):
        return True
    return False
