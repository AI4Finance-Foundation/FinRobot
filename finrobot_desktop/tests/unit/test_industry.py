"""Tests for primitives/industry.py — bank classification + net-revenue caliber.

``bank_net_revenue`` expected values are anchored to external truth (SEC XBRL,
JPM FY-Q1 2026 ending 2026-03-31, verified 2026-06-08):
  net interest income (us-gaap:InterestIncomeExpenseNet)    = 25.366B
  noninterest income  (us-gaap:NoninterestIncome)           = 24.470B
  total net revenue   (us-gaap:RevenuesNetOfInterestExpense)= 49.836B  (= NII + noninterest)
FMP serves gross revenue 73.661B and interestExpense 23.825B for that quarter;
73.661B − 23.825B = 49.836B ties to SEC to the penny.
"""

from finrobot.engine.primitives.industry import (
    bank_net_revenue,
    bank_operating_income_net_caliber,
    commodity_cyclical_basis,
    is_bank,
    is_commodity_cyclical,
)


class TestIsBank:
    def test_bank_by_industry(self) -> None:
        assert is_bank(industry="Banks—Diversified") is True
        assert is_bank(industry="Banks—Regional") is True
        assert is_bank(industry="Banks") is True
        assert is_bank(industry="Banks - Diversified") is True

    def test_bank_by_sector_and_industry(self) -> None:
        assert is_bank(industry="Investment Banking", sector="Financial Services") is True
        assert is_bank(industry="Community Banking", sector="Financials") is True

    def test_not_bank(self) -> None:
        assert is_bank(industry="Software") is False
        assert is_bank(industry="Insurance", sector="Financial Services") is False
        assert is_bank(industry=None, sector=None) is False
        assert is_bank(industry="Technology", sector="Technology") is False

    def test_financial_sector_without_bank_keyword(self) -> None:
        """Financial Services sector but industry without 'bank' -> not a bank."""
        assert is_bank(industry="Insurance", sector="Financial Services") is False
        assert is_bank(industry="Asset Management", sector="Financial Services") is False


class TestIsCommodityCyclical:
    """Full-basket regression钉死 for the cyclical gate (mechanical闸门).

    The provider industry tags below are the REAL ones (yfinance, probed
    2026-06-10 in scripts/_cyclical_*): MU/NVDA/AMD all carry "Semiconductors";
    WDC/STX carry "Computer Hardware" (so do DELL/ANET). The gate must therefore
    separate cyclicals from non-cyclicals WITHIN those shared buckets, never by
    the tag alone. AMD=False is the load-bearing assertion: a pure-volatility gate
    misclassifies AMD's turnaround swings as a commodity cycle (PILLAR 3).
    """

    def test_memory_storage_true_via_ticker_anchor(self) -> None:
        """Seed path: no description, generic tag — the ticker anchor fires.

        MU/NVDA/AMD share "Semiconductors"; WDC/STX share "Computer Hardware"
        with DELL/ANET. With only the tag available (the seed path), the curated
        anchor is what makes the memory/storage names cyclical."""
        assert is_commodity_cyclical("Semiconductors", "Technology", ticker="MU") is True
        assert is_commodity_cyclical("Computer Hardware", "Technology", ticker="WDC") is True
        assert is_commodity_cyclical("Computer Hardware", "Technology", ticker="STX") is True
        assert is_commodity_cyclical("Computer Hardware", "Technology", ticker="SNDK") is True

    def test_memory_storage_true_via_keyword(self) -> None:
        """Comps path: description carries a memory/storage keyword → cyclical,
        even for a ticker NOT in the anchor (the keyword收口 generalizes)."""
        assert (
            is_commodity_cyclical(
                "Semiconductors",
                "Technology",
                description="Designs and manufactures DRAM and NAND memory",
            )
            is True
        )
        assert (
            is_commodity_cyclical(
                "Computer Hardware",
                "Technology",
                description="Maker of hard disk drives and HDD storage",
            )
            is True
        )

    def test_non_cyclical_semis_false(self) -> None:
        """NVDA/AMD are "Semiconductors" but NOT memory — must stay non-cyclical.

        AMD=False even though its op-margin history is highly volatile: the gate
        is the whitelist/keyword/anchor, never volatility (the AMD假阳 the design
        rejected). No description, not in the anchor → False."""
        assert is_commodity_cyclical("Semiconductors", "Technology", ticker="NVDA") is False
        assert is_commodity_cyclical("Semiconductors", "Technology", ticker="AMD") is False
        # Even with a GPU/CPU description (no memory keyword) AMD stays False.
        assert (
            is_commodity_cyclical(
                "Semiconductors",
                "Technology",
                description="Designs CPUs, GPUs and adaptive SoC products",
                ticker="AMD",
            )
            is False
        )

    def test_non_cyclical_non_semis_false(self) -> None:
        assert (
            is_commodity_cyclical("Beverages—Non-Alcoholic", "Consumer Defensive", ticker="KO")
            is False
        )
        assert (
            is_commodity_cyclical("Software—Infrastructure", "Technology", ticker="MSFT") is False
        )
        assert (
            is_commodity_cyclical("Drug Manufacturers—General", "Healthcare", ticker="JNJ") is False
        )
        assert is_commodity_cyclical(industry=None, sector=None) is False

    def test_wide_bucket_without_keyword_false(self) -> None:
        """DELL/ANET sit in "Computer Hardware" but are not memory/storage → False
        (no anchor, no keyword)."""
        assert is_commodity_cyclical("Computer Hardware", "Technology", ticker="DELL") is False
        assert (
            is_commodity_cyclical(
                "Computer Hardware",
                "Technology",
                description="Network switches and routers",
                ticker="ANET",
            )
            is False
        )

    def test_unambiguous_cyclical_industries_true(self) -> None:
        """The unambiguous whitelist fires on the industry tag alone."""
        assert is_commodity_cyclical("Steel", "Basic Materials", ticker="X") is True
        assert is_commodity_cyclical("Oil & Gas E&P", "Energy", ticker="DVN") is True
        assert is_commodity_cyclical("Marine Shipping", "Industrials", ticker="ZIM") is True
        assert is_commodity_cyclical("Auto Manufacturers", "Consumer Cyclical", ticker="F") is True

    def test_ticker_anchor_normalizes_case_and_whitespace(self) -> None:
        assert is_commodity_cyclical("Semiconductors", "Technology", ticker=" mu ") is True


class TestCommodityCyclicalBasis:
    """Which arm fired — drives honest provenance + the memory-supercycle
    narrative scoping (TSLA must not read as a memory/storage name)."""

    def test_industry_whitelist_arm(self) -> None:
        assert commodity_cyclical_basis("Auto Manufacturers") == "industry"
        assert commodity_cyclical_basis("Steel") == "industry"

    def test_memory_storage_arm_for_generic_tags(self) -> None:
        # MU/WDC ride generic buckets — a True verdict there came from the
        # keyword收口 or the curated ticker anchor.
        assert commodity_cyclical_basis("Semiconductors") == "memory_storage"
        assert commodity_cyclical_basis("Computer Hardware") == "memory_storage"
        assert commodity_cyclical_basis(None) == "memory_storage"


class TestBankNetRevenue:
    def test_jpm_q1_2026_ties_to_sec(self) -> None:
        """73.661B gross − 23.825B interest expense = 49.836B = SEC net revenue."""
        assert bank_net_revenue(73_661_000_000, 23_825_000_000) == 49_836_000_000

    def test_missing_interest_expense_returns_none(self) -> None:
        """Caliber undefined when interest expense is missing — never re-serve the
        gross figure by treating a missing interest expense as 0."""
        assert bank_net_revenue(73_661_000_000, None) is None

    def test_missing_revenue_returns_none(self) -> None:
        assert bank_net_revenue(None, 23_825_000_000) is None

    def test_zero_interest_expense_passes_through(self) -> None:
        """A real reported 0 (not None) is a valid subtraction, not 'missing'."""
        assert bank_net_revenue(50_000_000_000, 0) == 50_000_000_000


class TestBankOperatingIncomeNetCaliber:
    """The net-revenue-caliber operating-income numerator for a bank's
    operating_margin. Values anchored to live FMP (JPM FY2025 annual):
    gross 279.745B, costAndExpenses 207.150B, operatingIncome 72.595B; the
    identity gross − costAndExpenses == OI holds, so the net-caliber OI == OI.
    """

    def test_identity_holds_returns_operating_income_unchanged(self) -> None:
        """When gross − costAndExpenses == operatingIncome (interest expense
        embedded in costAndExpenses), the net-revenue-caliber OI IS FMP's OI."""
        assert (
            bank_operating_income_net_caliber(279_745_000_000, 207_150_000_000, 72_595_000_000)
            == 72_595_000_000
        )

    def test_within_rounding_tolerance_passes(self) -> None:
        """A sub-bp rounding residual must not trip the guard."""
        assert (
            bank_operating_income_net_caliber(
                279_745_000_000, 207_150_000_000, 72_595_000_000 + 500_000
            )
            == 72_595_000_000 + 500_000
        )

    def test_identity_fails_abstains_to_none(self) -> None:
        """When the identity is violated beyond tolerance (interest expense
        placed OUTSIDE costAndExpenses → OI is gross-caliber), the net-caliber OI
        cannot be reconstructed — abstain to None, never emit a mixed caliber."""
        assert (
            bank_operating_income_net_caliber(
                279_745_000_000, 207_150_000_000, 72_595_000_000 - 10_000_000_000
            )
            is None
        )

    def test_missing_component_returns_none(self) -> None:
        assert bank_operating_income_net_caliber(None, 207_150_000_000, 72_595_000_000) is None
        assert bank_operating_income_net_caliber(279_745_000_000, None, 72_595_000_000) is None
        assert bank_operating_income_net_caliber(279_745_000_000, 207_150_000_000, None) is None
