"""Tests for primitives/industry.py — bank classification + net-revenue caliber.

``bank_net_revenue`` expected values are anchored to external truth (SEC XBRL,
JPM FY-Q1 2026 ending 2026-03-31, verified 2026-06-08):
  net interest income (us-gaap:InterestIncomeExpenseNet)    = 25.366B
  noninterest income  (us-gaap:NoninterestIncome)           = 24.470B
  total net revenue   (us-gaap:RevenuesNetOfInterestExpense)= 49.836B  (= NII + noninterest)
FMP serves gross revenue 73.661B and interestExpense 23.825B for that quarter;
73.661B − 23.825B = 49.836B ties to SEC to the penny.
"""

from finrobot.engine.primitives.industry import bank_net_revenue, is_bank


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
