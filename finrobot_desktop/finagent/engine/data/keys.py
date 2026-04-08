"""Canonical financial data keys that all providers must normalize to.

Documents the contract between providers and the extractor. Runtime enforcement
is deferred — providers still return untyped dicts, but this module documents
the expected structure and serves as single source of truth for key names.

All providers are responsible for normalizing their raw outputs to these keys.
The extractor consumes from this contract and raises ValueError if critical
keys are missing.
"""
from typing import TypedDict


class NormalizedFinancialKeys(TypedDict, total=False):
    """TypedDict specifying canonical financial data structure.

    Required keys (must be present):
    - revenue: TTM revenue in USD
    - ebitda: TTM EBITDA in USD
    - net_income: TTM net income in USD
    - market_cap: Current market cap in USD
    - shares_outstanding: Diluted shares in millions
    - current_price: Current stock price in USD
    - gross_margin: Gross margin as decimal (0-1)
    - operating_margin: Operating margin as decimal (can be negative)

    Optional keys (may be None or absent):
    - total_debt: Total debt in USD (can be None; defaults to 0 in extractor)
    - total_cash: Total cash in USD (can be None; defaults to 0 in extractor)
    - pe_ratio: Current P/E ratio
    - depreciation_amortization: TTM D&A in USD (used for FCF tax shield)
    - rd_expense: TTM R&D expense in USD
    - sga_expense: TTM SG&A expense in USD
    - interest_expense: TTM interest expense in USD
    """

    # Required
    revenue: float
    ebitda: float
    net_income: float
    market_cap: float
    shares_outstanding: float
    current_price: float
    gross_margin: float
    operating_margin: float

    # Optional
    total_debt: float | None
    total_cash: float | None
    pe_ratio: float | None
    depreciation_amortization: float | None
    rd_expense: float | None
    sga_expense: float | None
    interest_expense: float | None


REQUIRED_KEYS: frozenset[str] = frozenset({
    "revenue",
    "ebitda",
    "net_income",
    "market_cap",
    "shares_outstanding",
    "current_price",
    "gross_margin",
    "operating_margin",
})

OPTIONAL_KEYS: frozenset[str] = frozenset({
    "total_debt",
    "total_cash",
    "pe_ratio",
    "depreciation_amortization",
    "rd_expense",
    "sga_expense",
    "interest_expense",
})

ALL_KEYS: frozenset[str] = REQUIRED_KEYS | OPTIONAL_KEYS
