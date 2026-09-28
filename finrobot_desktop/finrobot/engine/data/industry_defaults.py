"""Industry-median financial ratios — DCF input fallback when ticker-level data is missing.

Source: Damodaran industry datasets, ``finrobot/engine/data/datasets/`` (refreshed
twice yearly by build_industry_medians.py). Currently 96 US industries plus a
"Total Market" catch-all.

What this code does that raw LLM cannot:
- Deterministic lookup keyed on yfinance ``industry`` / ``sector`` strings.
- Substring matching with a curated alias table so yfinance's industry names
  (e.g. "Consumer Electronics") map to Damodaran's nearest equivalent
  ("Computers/Peripherals").
- Always returns a complete IndustryDefault — falls back to "Total Market"
  when no Damodaran industry matches, so downstream DCF code never sees None.

Numbers here are intentionally *fallbacks*. ``dcf_seed`` prefers the ticker's
own 3-year historical medians; industry defaults only fire when D&A / CapEx
/ ΔWC / tax / beta are absent from the company's filings.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_DATASET_DIR = Path(__file__).parent / "datasets"
_CSV_PATH = _DATASET_DIR / "industry_medians.csv"
_TOTAL_MARKET = "Total Market"


@dataclass(frozen=True)
class IndustryDefault:
    """Industry-median DCF ratios. All values are decimals (0.05 = 5%)."""

    industry: str
    capex_pct_revenue: float
    da_pct_revenue: float
    ebitda_pct_revenue: float
    effective_tax_rate: float
    levered_beta: float
    debt_equity: float

    @property
    def debt_ratio(self) -> float:
        """Convert D/E → D/(D+E), the form WACC formula expects."""
        return self.debt_equity / (1.0 + self.debt_equity) if self.debt_equity > 0 else 0.0


# yfinance industry → Damodaran industry alias table.
# Keys are normalized (lower-case, single spaces). yfinance is inconsistent
# ("Consumer Electronics" vs "Computer Hardware"); Damodaran is curated. When
# adding a new alias, prefer the most-specific Damodaran row that fits.
_ALIAS_MAP: dict[str, str] = {
    "consumer electronics": "Computers/Peripherals",
    "computer hardware": "Computers/Peripherals",
    "software—application": "Software (System & Application)",
    "software—infrastructure": "Software (System & Application)",
    "internet content & information": "Software (Internet)",
    # Damodaran 2026-01 has no Retail (Online) row; use the nearest retail
    # operating bucket instead of silently falling through to Total Market.
    "internet retail": "Retail (General)",
    "beverages—non—alcoholic": "Beverage (Soft)",
    "auto manufacturers": "Auto & Truck",
    "auto—manufacturers": "Auto & Truck",
    "auto & truck dealerships": "Auto & Truck",
    "specialty retail": "Retail (Special Lines)",
    "discount stores": "Retail (General)",
    "home improvement retail": "Retail (Building Supply)",
    "home improvement": "Retail (Building Supply)",
    "apparel retail": "Retail (Special Lines)",
    "apparel—retail": "Retail (Special Lines)",
    "restaurants": "Restaurant/Dining",
    "drug manufacturers—general": "Drugs (Pharmaceutical)",
    "drug manufacturers—specialty & generic": "Drugs (Pharmaceutical)",
    "biotechnology": "Drugs (Biotechnology)",
    "medical devices": "Healthcare Products",
    "medical instruments & supplies": "Healthcare Products",
    "diagnostics & research": "Healthcare Products",
    "medical care facilities": "Hospitals/Healthcare Facilities",
    "healthcare plans": "Healthcare Support Services",
    # Damodaran's source row is misspelled "Heathcare"; keep the exact runtime
    # row name but map common provider spellings to it.
    "health information services": "Heathcare Information and Technology",
    "healthcare information services": "Heathcare Information and Technology",
    "banks—diversified": "Bank (Money Center)",
    "banks—regional": "Banks (Regional)",
    "community banking": "Banks (Regional)",
    "financial—capital markets": "Brokerage & Investment Banking",
    "credit services": "Financial Svcs. (Non-bank & Insurance)",
    "financial—credit services": "Financial Svcs. (Non-bank & Insurance)",
    "asset management": "Investments & Asset Management",
    "insurance—brokers": "Insurance (General)",
    "insurance—life": "Insurance (Life)",
    "insurance—property & casualty": "Insurance (Prop/Cas.)",
    "oil & gas integrated": "Oil/Gas (Integrated)",
    "oil & gas e&p": "Oil/Gas (Production and Exploration)",
    "oil & gas midstream": "Oil/Gas Distribution",
    "oil & gas refining & marketing": "Oil/Gas (Production and Exploration)",
    "utilities—regulated electric": "Power",
    "utilities—regulated water": "Utility (Water)",
    "utilities—regulated gas": "Utility (General)",
    "utilities—renewable": "Green & Renewable Energy",
    "reit—residential": "R.E.I.T.",
    "reit—retail": "R.E.I.T.",
    "reit—office": "R.E.I.T.",
    "reit—industrial": "R.E.I.T.",
    "reit—healthcare facilities": "R.E.I.T.",
    "reit—mortgage": "R.E.I.T.",
    "reit—specialty": "R.E.I.T.",
    "reit—diversified": "R.E.I.T.",
    "telecom services": "Telecom. Services",
    "entertainment": "Entertainment",
    "broadcasting": "Broadcasting",
    "advertising agencies": "Advertising",
    "airlines": "Air Transport",
    "trucking": "Trucking",
    "railroads": "Transportation (Railroads)",
    "marine shipping": "Shipbuilding & Marine",
    "aerospace & defense": "Aerospace/Defense",
    "semiconductors": "Semiconductor",
    "semiconductor equipment & materials": "Semiconductor Equip",
    "travel services": "Business & Consumer Services",
}


@lru_cache(maxsize=1)
def _load_all() -> dict[str, IndustryDefault]:
    """Load the full Damodaran CSV. Cached for the process lifetime."""
    if not _CSV_PATH.exists():
        raise FileNotFoundError(
            f"Industry-medians CSV missing at {_CSV_PATH}. "
            "Run finrobot/engine/data/datasets/build_industry_medians.py."
        )
    out: dict[str, IndustryDefault] = {}
    with _CSV_PATH.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                out[row["industry"]] = IndustryDefault(
                    industry=row["industry"],
                    capex_pct_revenue=float(row["capex_pct_revenue"]),
                    da_pct_revenue=float(row["da_pct_revenue"]),
                    ebitda_pct_revenue=float(row["ebitda_pct_revenue"] or "0.15"),
                    effective_tax_rate=float(row["effective_tax_rate"] or "0.21"),
                    levered_beta=float(row["levered_beta"] or "1.0"),
                    debt_equity=float(row["debt_equity"] or "0.3"),
                )
            except (ValueError, KeyError):
                # Skip malformed rows; the loader prefers Total Market fallback
                # over crashing.
                continue
    if _TOTAL_MARKET not in out:
        raise ValueError(
            f"industry_medians.csv missing '{_TOTAL_MARKET}' fallback row — "
            "rerun build_industry_medians.py."
        )
    return out


_DASH_RE = re.compile(r"\s*[—–-]\s*")


def _normalize(name: str) -> str:
    """Lower-case, normalize dash variants, collapse whitespace — for alias matching."""
    dashed = _DASH_RE.sub("—", name.lower())
    return " ".join(dashed.split())


def get_industry_default(industry: str | None) -> IndustryDefault:
    """Look up Damodaran industry median for a yfinance industry string.

    Match strategy:
      1. Exact match on Damodaran industry name.
      2. Curated alias table (_ALIAS_MAP).
      3. Substring match (case-insensitive) on Damodaran name.
      4. Fall back to "Total Market" — covers everything Damodaran lists.

    Args:
        industry: yfinance ``info["industry"]`` string. None or empty ⇒
                  Total Market fallback.

    Returns:
        IndustryDefault (never None). The ``industry`` field of the returned
        object reflects *which* Damodaran row matched, not the input string —
        useful for provenance logging in dcf_seed.
    """
    table = _load_all()
    if not industry:
        return table[_TOTAL_MARKET]

    # 1. Exact match
    if industry in table:
        return table[industry]

    norm = _normalize(industry)

    # 2. Alias
    if norm in _ALIAS_MAP:
        target = _ALIAS_MAP[norm]
        if target in table:
            return table[target]

    # 3. Substring match (industry name ⊆ Damodaran name, or vice versa)
    for damodaran_name in table:
        if damodaran_name == _TOTAL_MARKET:
            continue
        if norm in _normalize(damodaran_name) or _normalize(damodaran_name) in norm:
            return table[damodaran_name]

    # 4. Final fallback
    return table[_TOTAL_MARKET]


def list_known_industries() -> list[str]:
    """Return the full list of Damodaran industries — useful for tests / debugging."""
    return sorted(_load_all().keys())
