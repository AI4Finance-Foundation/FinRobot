"""Tests for industry_defaults — DCF input fallback when ticker-level data is missing.

What these tests verify beyond "code runs":
- Damodaran CSV loads, every row produces a valid IndustryDefault.
- yfinance-style industry strings ("Consumer Electronics") map to the right
  Damodaran row via the alias table.
- Substring matching catches near-matches before the Total Market fallback.
- Unknown industries (or None) always return Total Market — never crash.
- Numerical clamping in build_industry_medians.py held: every ratio is in
  a sane range for DCF math.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from finrobot.engine.data import industry_defaults
from finrobot.engine.data.industry_defaults import (
    IndustryDefault,
    get_industry_default,
    list_known_industries,
)


class TestLookup:
    def test_total_market_is_always_available(self):
        d = get_industry_default(None)
        assert d.industry == "Total Market"

    def test_empty_string_falls_back_to_total_market(self):
        d = get_industry_default("")
        assert d.industry == "Total Market"

    def test_exact_match_on_damodaran_name(self):
        d = get_industry_default("Aerospace/Defense")
        assert d.industry == "Aerospace/Defense"
        assert 0.0 < d.capex_pct_revenue < 0.20

    def test_yfinance_consumer_electronics_maps_to_computers(self):
        """AAPL's yfinance industry is 'Consumer Electronics' — alias should land."""
        d = get_industry_default("Consumer Electronics")
        assert d.industry == "Computers/Peripherals"

    def test_yfinance_aerospace_defense_alias(self):
        d = get_industry_default("Aerospace & Defense")
        assert d.industry == "Aerospace/Defense"

    def test_yfinance_semiconductors_maps_to_semiconductor(self):
        d = get_industry_default("Semiconductors")
        assert d.industry == "Semiconductor"

    @pytest.mark.parametrize(
        ("provider_label", "expected"),
        [
            ("Software - Application", "Software (System & Application)"),
            ("Software - Infrastructure", "Software (System & Application)"),
            ("Utilities - Renewable", "Green & Renewable Energy"),
            ("Medical Care Facilities", "Hospitals/Healthcare Facilities"),
            ("Health Information Services", "Heathcare Information and Technology"),
            ("Healthcare Information Services", "Heathcare Information and Technology"),
            ("Beverages - Non-Alcoholic", "Beverage (Soft)"),
            ("Restaurants", "Restaurant/Dining"),
            ("Home Improvement", "Retail (Building Supply)"),
            ("Apparel - Retail", "Retail (Special Lines)"),
            ("Auto - Manufacturers", "Auto & Truck"),
            ("Community Banking", "Banks (Regional)"),
            ("Financial - Capital Markets", "Brokerage & Investment Banking"),
            ("Financial - Credit Services", "Financial Svcs. (Non-bank & Insurance)"),
            ("Insurance - Brokers", "Insurance (General)"),
            ("Travel Services", "Business & Consumer Services"),
        ],
    )
    def test_common_provider_labels_do_not_fall_back_to_total_market(
        self, provider_label: str, expected: str
    ):
        d = get_industry_default(provider_label)
        assert d.industry == expected

    def test_substring_match_for_close_names(self):
        """'Software' should hit some Software (* ) row, not fall back to Total Market."""
        d = get_industry_default("Software")
        assert "Software" in d.industry

    def test_internet_retail_alias_hits_existing_retail_bucket(self):
        d = get_industry_default("Internet Retail")
        assert d.industry == "Retail (General)"

    def test_unknown_industry_falls_back_to_total_market(self):
        d = get_industry_default("NonexistentIndustry-12345")
        assert d.industry == "Total Market"


class TestRanges:
    """Verify every loaded row has DCF-sane numeric ranges (clamping in build script held)."""

    @pytest.fixture(autouse=True)
    def all_rows(self):
        self.industries = [get_industry_default(name) for name in list_known_industries()]

    def test_capex_in_range(self):
        for d in self.industries:
            assert 0.0 < d.capex_pct_revenue <= 0.6, f"{d.industry}: {d.capex_pct_revenue}"

    def test_da_in_range(self):
        for d in self.industries:
            assert 0.0 < d.da_pct_revenue <= 0.5, f"{d.industry}: {d.da_pct_revenue}"

    def test_tax_in_range(self):
        for d in self.industries:
            assert 0.0 < d.effective_tax_rate <= 0.5, f"{d.industry}: {d.effective_tax_rate}"

    def test_beta_in_range(self):
        for d in self.industries:
            assert 0.2 <= d.levered_beta <= 3.0, f"{d.industry}: {d.levered_beta}"

    def test_debt_equity_in_range(self):
        for d in self.industries:
            assert 0.0 <= d.debt_equity <= 5.0, f"{d.industry}: {d.debt_equity}"


class TestDatasetArtifact:
    def test_every_alias_target_exists_in_runtime_table(self):
        known = set(list_known_industries())
        missing = {
            target for target in industry_defaults._ALIAS_MAP.values() if target not in known
        }
        assert missing == set()

    def test_runtime_csv_has_no_blank_numeric_cells(self):
        csv_path = Path(industry_defaults.__file__).with_name("datasets") / "industry_medians.csv"
        with csv_path.open(newline="", encoding="utf-8") as fh:
            for line_no, row in enumerate(csv.DictReader(fh), start=2):
                for key, value in row.items():
                    if key == "industry":
                        continue
                    assert value and value.strip(), f"{csv_path}:{line_no} blank {key}"


class TestDebtRatioConversion:
    def test_debt_ratio_derived_from_debt_equity(self):
        """D/E = 1.0 → D/(D+E) = 0.5."""
        d = IndustryDefault(
            industry="X",
            capex_pct_revenue=0.05,
            da_pct_revenue=0.03,
            ebitda_pct_revenue=0.20,
            effective_tax_rate=0.21,
            levered_beta=1.0,
            debt_equity=1.0,
        )
        assert d.debt_ratio == pytest.approx(0.5)

    def test_debt_ratio_zero_when_no_debt(self):
        d = IndustryDefault(
            industry="X",
            capex_pct_revenue=0.05,
            da_pct_revenue=0.03,
            ebitda_pct_revenue=0.20,
            effective_tax_rate=0.21,
            levered_beta=1.0,
            debt_equity=0.0,
        )
        assert d.debt_ratio == 0.0


class TestCount:
    def test_loaded_around_96_industries(self):
        """Damodaran 2026-01 dataset has ~96 industries — guards against a CSV
        truncation regression."""
        names = list_known_industries()
        assert len(names) >= 90, f"only {len(names)} industries loaded — CSV truncated?"
        assert "Total Market" in names
