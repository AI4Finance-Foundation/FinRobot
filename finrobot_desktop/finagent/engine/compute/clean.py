"""Financial data cleaning utilities.

What this code does that raw LLM cannot: deterministic, reproducible parsing
of financial number formats (commas, parentheses for negatives, currency
symbols, percentages, N/A). Same input always produces the same float output.
"""

from __future__ import annotations

import re

_NA_VALUES = {"n/a", "na", "none", "null", "-", "--", "\u2014", ""}


def clean_financial_number(value: str | float | int | None) -> float | None:
    """Parse a financial string into a float.

    Handles: commas, parentheses-as-negative, currency symbols ($, etc.),
    percentages, N/A variants.  Returns None for unparseable input.
    """
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    s = str(value).strip()
    if s.lower() in _NA_VALUES:
        return None

    # Percentage flag — strip before numeric parsing
    is_pct = s.endswith("%")
    if is_pct:
        s = s[:-1]

    # Strip currency symbols *before* parentheses check so "$(...)" works
    s = re.sub(r"[$\u20ac\u00a3\u00a5\u20b9]", "", s).strip()

    # Parentheses denote negative in accounting format
    is_negative = s.startswith("(") and s.endswith(")")
    if is_negative:
        s = s[1:-1]

    # Remove thousands separators
    s = s.replace(",", "")

    if not s:
        return None

    try:
        result = float(s)
    except ValueError:
        return None

    if is_negative:
        result = -result
    if is_pct:
        result = result / 100

    return result


FIELD_ALIASES: dict[str, list[str]] = {
    "cost_of_revenue": [
        "costOfRevenue",
        "costOfGoodsSold",
        "totalCostOfSales",
        "cost_of_goods_sold",
        "CostOfGoodsAndServicesSold",
    ],
    "sga": [
        "sellingGeneralAndAdministrative",
        "sgaExpense",
        "selling_general_administrative",
        "SellingGeneralAndAdministrativeExpense",
    ],
    "depreciation_amortization": [
        "depreciationAndAmortization",
        "depreciation",
        "da",
        "DepreciationAndAmortization",
    ],
    "rd_expense": [
        "researchAndDevelopmentExpenses",
        "rdExpense",
        "research_and_development",
        "ResearchAndDevelopmentExpense",
    ],
    "interest_expense": [
        "interestExpense",
        "InterestExpense",
        "interest_expense_non_operating",
    ],
    "operating_income": [
        "operatingIncome",
        "OperatingIncomeLoss",
        "operating_income_loss",
    ],
    "gross_profit": [
        "grossProfit",
        "GrossProfit",
        "gross_profit_loss",
    ],
}


def normalize_field_names(
    data: dict, aliases: dict[str, list[str]] = FIELD_ALIASES
) -> dict:
    """Map provider-specific field names to canonical names.

    For each canonical name in *aliases*, the first matching variant found
    in *data* wins.  Keys that don't match any alias pass through unchanged.
    """
    result: dict = {}
    used_keys: set[str] = set()

    for canonical, variants in aliases.items():
        for variant in variants:
            if variant in data and variant not in used_keys:
                result[canonical] = data[variant]
                used_keys.add(variant)
                break

    # Pass through keys not consumed by any alias
    for key, value in data.items():
        if key not in used_keys:
            result[key] = value

    return result
