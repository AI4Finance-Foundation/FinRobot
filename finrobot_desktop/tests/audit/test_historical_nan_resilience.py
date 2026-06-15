"""Audit: NaN resilience in the historical-extractor → calculate_cagr → dcf_seed chain.

These tests guard against a regression where yfinance's oldest column being NaN
for the revenue row caused:
  - CAGR to be NaN (nan > 0 evaluates False)
  - dcf_seed to write "历史增长率不可得" even when 4 real years existed
  - capex/da list entries to be NaN, poisoning _median_ratio

Scenarios covered:
  1. 5 columns, oldest has NaN revenue → 4 valid years → real CAGR
  2. All columns NaN revenue → 0 valid years → cagr_revenue = None
  3. 2 valid + 1 NaN column → 2 valid years → 1y CAGR
  4. dcf_seed provenance is honest when CAGR is real vs absent
  5. _median_ratio skips NaN entries; all-NaN returns None
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import pytest

from finrobot.engine.compute.operators.data_processor import calculate_cagr
from finrobot.engine.compute.operators.dcf_seed import _median_ratio, seed_dcf_inputs
from finrobot.engine.compute.coordinators.historical_extractor import _build_from_yearly
from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.types import DataType


# ---------------------------------------------------------------------------
# Helpers — build the normalized per-year DataResults a provider emits
# ---------------------------------------------------------------------------


def _yearly_results(
    years: list[int],
    revenues: list[float | None],
) -> list[DataResult]:
    """Build the canonical per-year DataResults the provider chain emits.

    A ``None`` revenue simulates the NaN cell the yfinance provider maps to
    None (that DataFrame→None translation is covered in test_yfinance_provider);
    here we guard that the consumer drops such years so they can't poison CAGR.
    EBITDA tracks revenue so the row isn't entirely empty.
    """
    out: list[DataResult] = []
    for y, rev in zip(years, revenues):
        out.append(
            DataResult(
                data={
                    "fiscal_year": f"{y}-09-30",
                    "revenue": rev,
                    "ebitda": rev * 0.30 if rev is not None else None,
                    "operating_cash_flow": 0.0,
                },
                provider="test",
                ticker="TEST",
                data_type=DataType.FINANCIALS,
                timestamp=datetime.now(tz=timezone.utc),
                warnings=[],
            )
        )
    return out


# ---------------------------------------------------------------------------
# 1. Five columns, oldest NaN → 4 valid years → real CAGR
# ---------------------------------------------------------------------------


class TestOldestColumnNanRevenue:
    """Simulates AAPL FY21-FY25 where FY21 revenue is NaN."""

    def setup_method(self) -> None:
        results = _yearly_results(
            years=[2021, 2022, 2023, 2024, 2025],
            revenues=[None, 394_328e6, 383_285e6, 391_035e6, 416_161e6],
        )
        self.result = _build_from_yearly("AAPL", results, max_years=5, trailing_pe=None)

    def test_nan_year_excluded(self) -> None:
        """FY21 (NaN revenue) must be dropped from the year list."""
        assert 2021 not in self.result.years

    def test_four_years_retained(self) -> None:
        assert len(self.result.years) == 4
        assert self.result.years == [2022, 2023, 2024, 2025]

    def test_cagr_is_finite_number(self) -> None:
        """CAGR must be a finite float, not NaN or None."""
        assert self.result.cagr_revenue is not None
        assert math.isfinite(self.result.cagr_revenue)

    def test_cagr_value_ballpark(self) -> None:
        """AAPL FY22-FY25 revenue CAGR ≈ 1.8% — verify order of magnitude."""
        assert self.result.cagr_revenue is not None
        # 394B → 416B over 3 years: CAGR ~ (416/394)^(1/3)-1 ≈ 1.8%
        assert pytest.approx(self.result.cagr_revenue, abs=0.01) == pytest.approx(0.018, abs=0.01)

    def test_revenue_list_has_no_zero_sentinel_for_nan_year(self) -> None:
        """The NaN year must not appear as 0.0 in the revenue list."""
        assert 0.0 not in self.result.revenue


# ---------------------------------------------------------------------------
# 2. All columns NaN revenue → 0 valid years → empty / None
# ---------------------------------------------------------------------------


class TestAllColumnsNanRevenue:
    """When every column has NaN revenue, extractor should return empty but valid model."""

    def setup_method(self) -> None:
        results = _yearly_results(
            years=[2022, 2023, 2024],
            revenues=[None, None, None],
        )
        self.result = _build_from_yearly("TEST", results, max_years=5, trailing_pe=None)

    def test_years_empty(self) -> None:
        assert self.result.years == []

    def test_cagr_is_none(self) -> None:
        assert self.result.cagr_revenue is None

    def test_revenue_empty(self) -> None:
        assert self.result.revenue == []


# ---------------------------------------------------------------------------
# 3. Mixed: 2 valid + 1 NaN column → 2 valid years → 1y CAGR
# ---------------------------------------------------------------------------


class TestMixedNanRevenue:
    def setup_method(self) -> None:
        results = _yearly_results(
            years=[2022, 2023, 2024],
            revenues=[None, 383_285e6, 391_035e6],
        )
        self.result = _build_from_yearly("TEST", results, max_years=5, trailing_pe=None)

    def test_two_years_retained(self) -> None:
        assert self.result.years == [2023, 2024]

    def test_cagr_is_one_year_growth(self) -> None:
        # 383285 → 391035 over 1 year: CAGR = 391035/383285 - 1 ≈ 2.02%
        assert self.result.cagr_revenue is not None
        assert pytest.approx(self.result.cagr_revenue, abs=0.005) == pytest.approx(
            0.0202, abs=0.005
        )


# ---------------------------------------------------------------------------
# 3b. Margins: revenue present but numerator missing → None, not fabricated 0%
# ---------------------------------------------------------------------------


class TestMissingNumeratorMarginsAreNone:
    """A year with revenue present but a margin numerator (gross_profit /
    ebitda / operating_income / sga) absent must yield None for that margin —
    NOT 0%, which would (a) drag the forecast's historical-mean margin down and
    (b) paint a false 0% point on the margin-trend chart. None ≠ 0."""

    def setup_method(self) -> None:
        results = [
            DataResult(
                data={"fiscal_year": "2024-09-30", "revenue": 1000.0},  # numerators absent
                provider="test",
                ticker="TEST",
                data_type=DataType.FINANCIALS,
                timestamp=datetime.now(tz=timezone.utc),
                warnings=[],
            ),
            DataResult(
                data={
                    "fiscal_year": "2025-09-30",
                    "revenue": 1200.0,
                    "gross_profit": 600.0,
                    "ebitda": 360.0,
                    "operating_income": 240.0,
                    "sga_expense": 120.0,
                },
                provider="test",
                ticker="TEST",
                data_type=DataType.FINANCIALS,
                timestamp=datetime.now(tz=timezone.utc),
                warnings=[],
            ),
        ]
        self.result = _build_from_yearly("TEST", results, max_years=5, trailing_pe=None)

    def test_missing_year_margins_are_none(self) -> None:
        assert self.result.gross_margin[0] is None
        assert self.result.ebitda_margin[0] is None
        assert self.result.operating_margin[0] is None
        assert self.result.sga_ratio[0] is None

    def test_present_year_margins_computed(self) -> None:
        assert self.result.gross_margin[1] == pytest.approx(0.5)
        assert self.result.ebitda_margin[1] == pytest.approx(0.3)
        assert self.result.operating_margin[1] == pytest.approx(0.2)
        assert self.result.sga_ratio[1] == pytest.approx(0.1)

    def test_genuine_zero_numerator_stays_zero_not_none(self) -> None:
        """A genuinely *reported* 0 (not a missing field) must produce a real 0%
        margin — the None signal is reserved for absent data."""
        results = [
            DataResult(
                data={"fiscal_year": "2025-09-30", "revenue": 1000.0, "operating_income": 0.0},
                provider="test",
                ticker="TEST",
                data_type=DataType.FINANCIALS,
                timestamp=datetime.now(tz=timezone.utc),
                warnings=[],
            ),
        ]
        result = _build_from_yearly("TEST", results, max_years=5, trailing_pe=None)
        assert result.operating_margin[0] == 0.0


# ---------------------------------------------------------------------------
# 4. calculate_cagr: NaN inputs return None
# ---------------------------------------------------------------------------


class TestCalculateCagrNanGuard:
    def test_nan_start_returns_none(self) -> None:
        assert calculate_cagr(float("nan"), 400e9, 3) is None

    def test_nan_end_returns_none(self) -> None:
        assert calculate_cagr(394e9, float("nan"), 3) is None

    def test_both_nan_returns_none(self) -> None:
        assert calculate_cagr(float("nan"), float("nan"), 3) is None

    def test_normal_case_unaffected(self) -> None:
        result = calculate_cagr(394e9, 416e9, 3)
        assert result is not None
        assert math.isfinite(result)


# ---------------------------------------------------------------------------
# 5. _median_ratio: NaN in list entries are skipped
# ---------------------------------------------------------------------------


class TestMedianRatioNanSkip:
    def test_nan_numerator_skipped(self) -> None:
        # Without NaN skip: nan/100 = nan, poisoning the median
        result = _median_ratio(
            [float("nan"), 10.0, 12.0],
            [100.0, 100.0, 100.0],
            min_samples=3,
        )
        # Only 10/100=0.10 and 12/100=0.12 counted → median 0.11, count 2
        assert result is not None
        median, count = result
        assert pytest.approx(median, abs=0.01) == pytest.approx(0.11, abs=0.01)
        assert count == 2

    def test_nan_denominator_skipped(self) -> None:
        result = _median_ratio(
            [10.0, 11.0, 12.0],
            [100.0, float("nan"), 100.0],
            min_samples=3,
        )
        # 10/100 and 12/100 counted (NaN den row skipped) → median 0.11
        assert result is not None

    def test_all_nan_returns_none(self) -> None:
        result = _median_ratio(
            [float("nan"), float("nan")],
            [float("nan"), float("nan")],
            min_samples=2,
        )
        assert result is None


# ---------------------------------------------------------------------------
# 6. dcf_seed provenance is honest: real CAGR vs NaN-polluted
# ---------------------------------------------------------------------------


def _make_minimal_financials() -> Any:
    """Import here to avoid circular import at module level."""
    from datetime import datetime, timezone

    from finrobot.engine.models.financial import (
        BalanceSheet,
        FinancialData,
        IncomeStatement,
        MarketData,
        ValuationMetrics,
    )

    return FinancialData(
        ticker="AAPL",
        company_name="Apple Inc.",
        timestamp=datetime.now(tz=timezone.utc),
        income=IncomeStatement(
            revenue=391_035_000_000,
            ebitda=131_900_000_000,
            net_income=93_736_000_000,
            gross_margin=0.46,
            operating_margin=0.30,
            depreciation_amortization=11_445_000_000,
            interest_expense=3_750_000_000,
        ),
        balance=BalanceSheet(
            total_debt=106_629_000_000,
            total_cash=65_171_000_000,
        ),
        market=MarketData(
            market_cap=3_500_000_000_000,
            shares_outstanding=15_115_000_000,
            current_price=232.0,
            pe_ratio=37.4,
            industry="Consumer Electronics",
            sector="Technology",
            beta=1.25,
        ),
        valuation=ValuationMetrics(),
    )


class TestDcfSeedProvenance:
    def test_real_cagr_provenance_contains_cagr_value(self) -> None:
        from finrobot.engine.models.financial import HistoricalMetrics

        hist = HistoricalMetrics(
            years=[2022, 2023, 2024, 2025],
            revenue=[394_328e6, 383_285e6, 391_035e6, 416_161e6],
            revenue_growth_yoy=[None, -0.028, 0.020, 0.064],
            cogs=[],
            gross_profit=[],
            gross_margin=[0.43, 0.44, 0.46, 0.47],
            sga=[],
            sga_ratio=[],
            ebitda=[130e9, 126e9, 132e9, 145e9],
            ebitda_margin=[0.33, 0.33, 0.34, 0.35],
            operating_income=[],
            operating_margin=[],
            net_income=[],
            eps=[],
            pe_ratio=[],
            cagr_revenue=0.018,  # real CAGR
            ticker="AAPL",
            depreciation_amortization=[11_104e6, 11_519e6, 11_445e6, 11_698e6],
            capital_expenditure=[10_708e6, 10_959e6, 9_447e6, 12_715e6],
            change_in_working_capital=[0.0, 0.0, 0.0, 0.0],
        )
        inputs = seed_dcf_inputs(_make_minimal_financials(), hist)
        prov = inputs.assumption_provenance["revenue_growth_rates"]
        # Must contain CAGR percentage, not "unavailable" or "gaps"
        assert "CAGR" in prov or "%" in prov
        assert "unavailable" not in prov
        assert "gaps" not in prov

    def test_nan_cagr_provenance_is_honest(self) -> None:
        """When cagr_revenue is NaN (not None), provenance must say 'NaN缺口', not '历史增长率不可得'."""
        from finrobot.engine.models.financial import HistoricalMetrics

        hist = HistoricalMetrics(
            years=[2022, 2023],
            revenue=[394_328e6, 383_285e6],
            revenue_growth_yoy=[None, -0.028],
            cogs=[],
            gross_profit=[],
            gross_margin=[0.43, 0.44],
            sga=[],
            sga_ratio=[],
            ebitda=[130e9, 126e9],
            ebitda_margin=[0.33, 0.33],
            operating_income=[],
            operating_margin=[],
            net_income=[],
            eps=[],
            pe_ratio=[],
            cagr_revenue=float("nan"),  # explicit NaN — simulates upstream pollution
            ticker="AAPL",
        )
        inputs = seed_dcf_inputs(_make_minimal_financials(), hist)
        prov = inputs.assumption_provenance["revenue_growth_rates"]
        # Must acknowledge the NaN, not pretend data is simply unavailable
        assert "gaps" in prov or "NaN" in prov

    def test_none_cagr_provenance_says_data_insufficient(self) -> None:
        """When cagr_revenue is None (no data), provenance says 'histor data insufficient'."""
        from finrobot.engine.models.financial import HistoricalMetrics

        hist = HistoricalMetrics(
            years=[],
            revenue=[],
            revenue_growth_yoy=[],
            cogs=[],
            gross_profit=[],
            gross_margin=[],
            sga=[],
            sga_ratio=[],
            ebitda=[],
            ebitda_margin=[],
            operating_income=[],
            operating_margin=[],
            net_income=[],
            eps=[],
            pe_ratio=[],
            cagr_revenue=None,
            ticker="AAPL",
        )
        inputs = seed_dcf_inputs(_make_minimal_financials(), hist)
        prov = inputs.assumption_provenance["revenue_growth_rates"]
        assert "historical" in prov
        # Must NOT blame NaN when the issue is data absence
        assert "gaps" not in prov
