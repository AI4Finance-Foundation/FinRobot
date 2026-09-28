"""One-shot: merge four Damodaran .xls files into a single clean CSV.

Run this once whenever Damodaran refreshes his datasets (twice a year, Jan/Jul).
Inputs (committed alongside, as of 2026-01-05):
  - damodaran_capex_2026-01.xls
  - damodaran_margin_2026-01.xls
  - damodaran_taxrate_2026-01.xls
  - damodaran_betas_2026-01.xls

Output:
  - industry_medians.csv   ← consumed by industry_defaults.py at runtime

Derived fields:
  - da_pct_revenue       = EBITDA/Sales - Pre-tax Unadjusted Operating Margin
                           (Operating Income excludes D&A; EBITDA includes it.)
  - capex_pct_revenue    = Net Cap Ex/Sales + da_pct_revenue
                           (CapEx = NetCapEx + Depreciation, by construction.)
  - effective_tax_rate   = Aggregate tax rate across money-making firms (col J).
                           More stable than per-firm average for downstream use.
  - levered_beta         = Equity beta (raw, levered) from the 5y average column.
  - debt_equity          = Industry-average D/E ratio.

Source: pages.stern.nyu.edu/~adamodar/New_Home_Page/datacurrent.html
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

BASE = Path(__file__).parent
TAG = "2026-01"


def _load_capex() -> pd.DataFrame:
    df = pd.read_excel(
        BASE / f"damodaran_capex_{TAG}.xls", sheet_name="Industry Averages", skiprows=7
    )
    df = df[["Industry Name", "Cap Ex/Deprecn", "Net Cap Ex/Sales"]]
    df = df.rename(
        columns={
            "Industry Name": "industry",
            "Cap Ex/Deprecn": "capex_to_dep_ratio",
            "Net Cap Ex/Sales": "net_capex_pct_revenue",
        }
    )
    return df


def _load_margin() -> pd.DataFrame:
    # skiprows=8 lands the real header (skiprows=7 from capex.xls; margin has one extra row)
    df = pd.read_excel(
        BASE / f"damodaran_margin_{TAG}.xls", sheet_name="Industry Averages", skiprows=8
    )
    df = df[["Industry Name", "EBITDA/Sales", "Pre-tax Unadjusted Operating Margin"]]
    df = df.rename(
        columns={
            "Industry Name": "industry",
            "EBITDA/Sales": "ebitda_pct_revenue",
            "Pre-tax Unadjusted Operating Margin": "operating_margin",
        }
    )
    return df


def _load_taxrate() -> pd.DataFrame:
    df = pd.read_excel(
        BASE / f"damodaran_taxrate_{TAG}.xls", sheet_name="Industry Averages", skiprows=8
    )
    # "Aggregate tax rate" column (effective, accrual basis, money-making firms only)
    df = df[["Industry name", "Aggregate tax rate"]]
    df = df.rename(
        columns={"Industry name": "industry", "Aggregate tax rate": "effective_tax_rate"}
    )
    return df


def _load_betas() -> pd.DataFrame:
    df = pd.read_excel(
        BASE / f"damodaran_betas_{TAG}.xls", sheet_name="Industry Averages", skiprows=9
    )
    df = df[["Industry Name", "Beta ", "D/E Ratio"]]
    df = df.rename(
        columns={"Industry Name": "industry", "Beta ": "levered_beta", "D/E Ratio": "debt_equity"}
    )
    return df


def main() -> None:
    capex = _load_capex()
    margin = _load_margin()
    tax = _load_taxrate()
    betas = _load_betas()
    total_market_tax = tax.loc[tax["industry"].eq("Total Market"), "effective_tax_rate"].dropna()
    fallback_tax_rate = float(total_market_tax.iloc[0]) if not total_market_tax.empty else 0.21
    tax["effective_tax_rate"] = tax["effective_tax_rate"].fillna(fallback_tax_rate)

    merged = (
        capex.merge(margin, on="industry", how="inner")
        .merge(tax, on="industry", how="inner")
        .merge(betas, on="industry", how="inner")
    )

    # D&A/Revenue = EBITDA/Sales - Operating Margin (since Operating Income = EBITDA - D&A)
    merged["da_pct_revenue"] = merged["ebitda_pct_revenue"] - merged["operating_margin"]
    # CapEx/Revenue = NetCapEx/Sales + D&A/Revenue
    merged["capex_pct_revenue"] = merged["net_capex_pct_revenue"] + merged["da_pct_revenue"]

    # Clamp to reasonable ranges — Damodaran sometimes reports negative D&A or
    # extreme capex for tiny / loss-making sectors. DCF needs non-negative ratios.
    merged["da_pct_revenue"] = merged["da_pct_revenue"].clip(lower=0.005, upper=0.40)
    merged["capex_pct_revenue"] = merged["capex_pct_revenue"].clip(lower=0.005, upper=0.50)
    merged["effective_tax_rate"] = merged["effective_tax_rate"].clip(lower=0.05, upper=0.40)
    merged["levered_beta"] = merged["levered_beta"].clip(lower=0.3, upper=2.5)
    merged["debt_equity"] = merged["debt_equity"].clip(lower=0.0, upper=3.0)

    out = merged[
        [
            "industry",
            "capex_pct_revenue",
            "da_pct_revenue",
            "ebitda_pct_revenue",
            "effective_tax_rate",
            "levered_beta",
            "debt_equity",
        ]
    ].copy()
    out = out.sort_values("industry").reset_index(drop=True)

    out_path = BASE / "industry_medians.csv"
    out.to_csv(out_path, index=False, float_format="%.4f")
    logger.info("Wrote %d industries → %s", len(out), out_path)
    logger.info("%s", out.head(10).to_string())


if __name__ == "__main__":
    # CLI invocation — surface logger output to stdout. When imported as a
    # module (the architecture audit doesn't allow print), the caller decides
    # how to handle the logger.
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
