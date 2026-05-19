"""Tests for HistoricalMetrics cash flow fields and historical_extractor.

What these tests verify beyond "code runs":
- HistoricalMetrics accepts three cash flow fields with correct types
- extract_historical_from_yfinance returns populated HistoricalMetrics including cash flow
- _get_row helper handles missing rows gracefully without raising
- Cash flow data is sorted oldest-first (same ordering as other fields)
- CAGR calculation is correct per CFA formula
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from finagent.engine.models.financial import HistoricalMetrics


# ---------------------------------------------------------------------------
# Part 1: HistoricalMetrics model — cash flow fields
# ---------------------------------------------------------------------------


class TestHistoricalMetricsCashFlowFields:
    """Verify HistoricalMetrics accepts the three new cash flow fields."""

    def _minimal_kwargs(self) -> dict:
        """Minimum valid HistoricalMetrics constructor kwargs (no cash flow)."""
        return {
            "years": [2020, 2021, 2022],
            "revenue": [1e9, 1.1e9, 1.2e9],
            "revenue_growth_yoy": [None, 0.1, 0.09],
            "cogs": [6e8, 6.6e8, 7.2e8],
            "gross_profit": [4e8, 4.4e8, 4.8e8],
            "gross_margin": [0.4, 0.4, 0.4],
            "sga": [1e8, 1.1e8, 1.2e8],
            "sga_ratio": [0.1, 0.1, 0.1],
            "ebitda": [2e8, 2.2e8, 2.4e8],
            "ebitda_margin": [0.2, 0.2, 0.2],
            "operating_income": [1.5e8, 1.65e8, 1.8e8],
            "operating_margin": [0.15, 0.15, 0.15],
            "net_income": [1e8, 1.1e8, 1.2e8],
            "eps": [2.0, 2.2, 2.4],
            "pe_ratio": [20.0, 18.0, 17.0],
            "cagr_revenue": 0.095,
            "ticker": "TEST",
        }

    def test_cash_flow_fields_default_to_empty_list(self):
        """New cash flow fields must default to [] so existing code is not broken."""
        hm = HistoricalMetrics(**self._minimal_kwargs())
        assert hm.operating_cash_flow == []
        assert hm.investing_cash_flow == []
        assert hm.financing_cash_flow == []

    def test_dcf_line_item_fields_default_to_empty_list(self):
        """D&A / CapEx / ΔNWC fields must default to [] so dcf_seed can detect
        absence and fall back to industry medians."""
        hm = HistoricalMetrics(**self._minimal_kwargs())
        assert hm.depreciation_amortization == []
        assert hm.capital_expenditure == []
        assert hm.change_in_working_capital == []

    def test_dcf_line_item_fields_accept_lists(self):
        hm = HistoricalMetrics(
            **self._minimal_kwargs(),
            depreciation_amortization=[1.1e10, 1.2e10, 1.3e10],
            capital_expenditure=[1e10, 1.1e10, 1.2e10],
            change_in_working_capital=[-5e8, -6e8, -7e8],
        )
        assert hm.depreciation_amortization == [1.1e10, 1.2e10, 1.3e10]
        assert hm.capital_expenditure == [1e10, 1.1e10, 1.2e10]
        assert hm.change_in_working_capital == [-5e8, -6e8, -7e8]

    def test_operating_cash_flow_accepts_list_of_floats(self):
        hm = HistoricalMetrics(
            **self._minimal_kwargs(),
            operating_cash_flow=[1.5e8, 1.7e8, 2.0e8],
        )
        assert hm.operating_cash_flow == [1.5e8, 1.7e8, 2.0e8]

    def test_investing_cash_flow_accepts_negative_values(self):
        """Investing cash flow is typically negative (capex)."""
        hm = HistoricalMetrics(
            **self._minimal_kwargs(),
            investing_cash_flow=[-5e7, -6e7, -7e7],
        )
        assert hm.investing_cash_flow == [-5e7, -6e7, -7e7]

    def test_financing_cash_flow_accepts_negative_values(self):
        """Financing cash flow is often negative (buybacks, dividends)."""
        hm = HistoricalMetrics(
            **self._minimal_kwargs(),
            financing_cash_flow=[-1e8, -1.1e8, -1.3e8],
        )
        assert hm.financing_cash_flow == [-1e8, -1.1e8, -1.3e8]

    def test_all_three_cash_flow_fields_together(self):
        """All three fields coexist without conflict."""
        ocf = [2e8, 2.2e8, 2.5e8]
        icf = [-3e7, -4e7, -5e7]
        fcf = [-1.5e8, -1.8e8, -2e8]
        hm = HistoricalMetrics(
            **self._minimal_kwargs(),
            operating_cash_flow=ocf,
            investing_cash_flow=icf,
            financing_cash_flow=fcf,
        )
        assert hm.operating_cash_flow == ocf
        assert hm.investing_cash_flow == icf
        assert hm.financing_cash_flow == fcf

    def test_serialises_to_dict_with_cash_flow_fields(self):
        """model_dump() must include the three new fields."""
        hm = HistoricalMetrics(
            **self._minimal_kwargs(),
            operating_cash_flow=[1e8],
            investing_cash_flow=[-2e7],
            financing_cash_flow=[-8e7],
        )
        d = hm.model_dump()
        assert "operating_cash_flow" in d
        assert "investing_cash_flow" in d
        assert "financing_cash_flow" in d
        assert d["operating_cash_flow"] == [1e8]


# ---------------------------------------------------------------------------
# Part 2: _get_row helper — unit tests without yfinance
# ---------------------------------------------------------------------------


class TestGetRow:
    """Unit tests for the _get_row helper in historical_extractor."""

    def setup_method(self):
        from finagent.engine.compute.historical_extractor import _get_row

        self._get_row = _get_row

    def test_returns_values_for_exact_name_match(self):
        df = pd.DataFrame(
            {"2020": [100.0], "2021": [110.0]},
            index=["Total Revenue"],
        )
        result = self._get_row(df, ["Total Revenue"])
        assert result is not None
        assert list(result) == [100.0, 110.0]

    def test_tries_secondary_name_when_primary_missing(self):
        df = pd.DataFrame(
            {"2020": [50.0], "2021": [55.0]},
            index=["Net Revenue"],
        )
        result = self._get_row(df, ["Total Revenue", "Net Revenue"])
        assert result is not None
        assert list(result) == [50.0, 55.0]

    def test_returns_none_when_all_names_missing(self):
        df = pd.DataFrame(
            {"2020": [100.0]},
            index=["Some Other Row"],
        )
        result = self._get_row(df, ["Total Revenue", "Net Revenue"])
        assert result is None

    def test_returns_none_for_empty_dataframe(self):
        df = pd.DataFrame()
        result = self._get_row(df, ["Total Revenue"])
        assert result is None

    def test_returns_none_for_empty_names_list(self):
        df = pd.DataFrame({"2020": [100.0]}, index=["Total Revenue"])
        result = self._get_row(df, [])
        assert result is None


# ---------------------------------------------------------------------------
# Part 3: extract_historical_from_yfinance — with mocked yfinance
# ---------------------------------------------------------------------------


def _make_income_stmt() -> pd.DataFrame:
    """Minimal income statement DataFrame matching yfinance format (columns = dates, rows = items)."""
    cols = pd.to_datetime(["2022-12-31", "2021-12-31", "2020-12-31", "2019-12-31"])
    data = {
        "Total Revenue": [400e9, 365e9, 274e9, 260e9],
        "Gross Profit": [170e9, 152e9, 104e9, 98e9],
        "EBITDA": [130e9, 120e9, 77e9, 76e9],
        "Operating Income": [119e9, 108e9, 66e9, 64e9],
        "Net Income": [99e9, 95e9, 57e9, 55e9],
        "Basic EPS": [6.15, 5.61, 3.28, 2.97],
        "Selling General Administrative": [25e9, 22e9, 19e9, 18e9],
    }
    df = pd.DataFrame(data, index=cols).T
    return df


def _make_cashflow() -> pd.DataFrame:
    """Minimal cash flow DataFrame matching yfinance format.

    Includes the three rows feeding the DCF FCF formula. CapEx is reported as
    a negative number — same convention as yfinance.
    """
    cols = pd.to_datetime(["2022-12-31", "2021-12-31", "2020-12-31", "2019-12-31"])
    data = {
        "Operating Cash Flow": [122e9, 104e9, 80e9, 69e9],
        "Investing Cash Flow": [-23e9, -15e9, -10e9, -12e9],
        "Financing Cash Flow": [-110e9, -101e9, -86e9, -90e9],
        "Depreciation And Amortization": [11e9, 11.3e9, 11.1e9, 12.5e9],
        "Capital Expenditure": [-11e9, -10e9, -7.3e9, -10e9],
        "Change In Working Capital": [1.2e9, -3e8, 8e8, -5e8],
    }
    df = pd.DataFrame(data, index=cols).T
    return df


def _make_info() -> dict:
    return {
        "trailingPE": 25.0,
        "forwardPE": 22.0,
    }


def _make_mock_ticker(income_stmt, cashflow, info):
    mock = MagicMock()
    mock.income_stmt = income_stmt
    mock.cashflow = cashflow
    mock.info = info
    return mock


class TestExtractHistoricalFromYfinance:
    """Verify extract_historical_from_yfinance returns correct HistoricalMetrics."""

    def _run(self, coro):
        # asyncio.get_event_loop() throws when no running loop exists in 3.11+;
        # use asyncio.run which creates a fresh loop per call. Avoids test
        # interference when other suites close the global loop.
        return asyncio.run(coro)

    @pytest.fixture(autouse=True)
    def mock_yfinance(self):
        income = _make_income_stmt()
        cashflow = _make_cashflow()
        info = _make_info()
        mock_ticker = _make_mock_ticker(income, cashflow, info)

        with patch("yfinance.Ticker", return_value=mock_ticker):
            yield mock_ticker

    def test_returns_historical_metrics_instance(self):
        from finagent.engine.compute.historical_extractor import (
            extract_historical_from_yfinance,
        )

        result = self._run(extract_historical_from_yfinance("AAPL"))
        assert isinstance(result, HistoricalMetrics)

    def test_ticker_is_set_correctly(self):
        from finagent.engine.compute.historical_extractor import (
            extract_historical_from_yfinance,
        )

        result = self._run(extract_historical_from_yfinance("AAPL"))
        assert result.ticker == "AAPL"

    def test_years_are_sorted_oldest_first(self):
        from finagent.engine.compute.historical_extractor import (
            extract_historical_from_yfinance,
        )

        result = self._run(extract_historical_from_yfinance("AAPL"))
        assert result.years == sorted(result.years)

    def test_revenue_list_has_correct_length(self):
        from finagent.engine.compute.historical_extractor import (
            extract_historical_from_yfinance,
        )

        result = self._run(extract_historical_from_yfinance("AAPL"))
        assert len(result.revenue) == len(result.years)

    def test_revenue_oldest_first_matches_data(self):
        """Revenue for oldest year should be smallest (260B in mock)."""
        from finagent.engine.compute.historical_extractor import (
            extract_historical_from_yfinance,
        )

        result = self._run(extract_historical_from_yfinance("AAPL"))
        # 2019=260B is first, 2022=400B is last
        assert result.revenue[0] == pytest.approx(260e9, rel=0.01)
        assert result.revenue[-1] == pytest.approx(400e9, rel=0.01)

    def test_operating_cash_flow_populated(self):
        from finagent.engine.compute.historical_extractor import (
            extract_historical_from_yfinance,
        )

        result = self._run(extract_historical_from_yfinance("AAPL"))
        assert len(result.operating_cash_flow) == len(result.years)
        # oldest first: 2019=69B, 2022=122B
        assert result.operating_cash_flow[0] == pytest.approx(69e9, rel=0.01)
        assert result.operating_cash_flow[-1] == pytest.approx(122e9, rel=0.01)

    def test_investing_cash_flow_populated_with_negatives(self):
        from finagent.engine.compute.historical_extractor import (
            extract_historical_from_yfinance,
        )

        result = self._run(extract_historical_from_yfinance("AAPL"))
        assert len(result.investing_cash_flow) == len(result.years)
        assert result.investing_cash_flow[0] < 0  # investing is typically negative

    def test_financing_cash_flow_populated(self):
        from finagent.engine.compute.historical_extractor import (
            extract_historical_from_yfinance,
        )

        result = self._run(extract_historical_from_yfinance("AAPL"))
        assert len(result.financing_cash_flow) == len(result.years)

    def test_revenue_growth_yoy_first_is_none(self):
        from finagent.engine.compute.historical_extractor import (
            extract_historical_from_yfinance,
        )

        result = self._run(extract_historical_from_yfinance("AAPL"))
        assert result.revenue_growth_yoy[0] is None

    def test_revenue_growth_yoy_second_year_correct(self):
        """2019→2020: (274-260)/260 = 0.05385."""
        from finagent.engine.compute.historical_extractor import (
            extract_historical_from_yfinance,
        )

        result = self._run(extract_historical_from_yfinance("AAPL"))
        assert result.revenue_growth_yoy[1] == pytest.approx(0.05385, abs=0.001)

    def test_cagr_revenue_is_set(self):
        from finagent.engine.compute.historical_extractor import (
            extract_historical_from_yfinance,
        )

        result = self._run(extract_historical_from_yfinance("AAPL"))
        assert result.cagr_revenue is not None
        # (400/260)^(1/3) - 1 ≈ 0.1543
        assert result.cagr_revenue == pytest.approx(0.1543, abs=0.01)

    def test_gross_margin_is_ratio_between_0_and_1(self):
        from finagent.engine.compute.historical_extractor import (
            extract_historical_from_yfinance,
        )

        result = self._run(extract_historical_from_yfinance("AAPL"))
        for gm in result.gross_margin:
            assert 0.0 <= gm <= 1.0, f"gross_margin out of range: {gm}"

    def test_ebitda_margin_is_ratio(self):
        from finagent.engine.compute.historical_extractor import (
            extract_historical_from_yfinance,
        )

        result = self._run(extract_historical_from_yfinance("AAPL"))
        for em in result.ebitda_margin:
            assert 0.0 <= em <= 1.0, f"ebitda_margin out of range: {em}"

    def test_eps_is_populated(self):
        from finagent.engine.compute.historical_extractor import (
            extract_historical_from_yfinance,
        )

        result = self._run(extract_historical_from_yfinance("AAPL"))
        assert len(result.eps) == len(result.years)
        assert all(v > 0 for v in result.eps)

    def test_depreciation_amortization_populated(self):
        """D&A is reported positive in cash flow stmt — pass through unchanged."""
        from finagent.engine.compute.historical_extractor import (
            extract_historical_from_yfinance,
        )

        result = self._run(extract_historical_from_yfinance("AAPL"))
        assert len(result.depreciation_amortization) == len(result.years)
        # oldest first: 2019=12.5B, 2022=11B
        assert result.depreciation_amortization[0] == pytest.approx(12.5e9, rel=0.01)
        assert result.depreciation_amortization[-1] == pytest.approx(11e9, rel=0.01)

    def test_capital_expenditure_sign_flipped_to_positive(self):
        """CapEx is negative in raw yfinance (cash outflow) but stored as positive
        magnitude so dcf_seed can compute capex/revenue ratios directly."""
        from finagent.engine.compute.historical_extractor import (
            extract_historical_from_yfinance,
        )

        result = self._run(extract_historical_from_yfinance("AAPL"))
        assert len(result.capital_expenditure) == len(result.years)
        # all stored as positive
        assert all(v >= 0 for v in result.capital_expenditure)
        # oldest first: 2019=10B (flipped from -10B), 2022=11B
        assert result.capital_expenditure[0] == pytest.approx(10e9, rel=0.01)
        assert result.capital_expenditure[-1] == pytest.approx(11e9, rel=0.01)

    def test_change_in_working_capital_can_be_negative(self):
        """ΔWC can be positive (WC decreased, cash released) or negative (WC built up)."""
        from finagent.engine.compute.historical_extractor import (
            extract_historical_from_yfinance,
        )

        result = self._run(extract_historical_from_yfinance("AAPL"))
        assert len(result.change_in_working_capital) == len(result.years)
        # mock has mixed signs; just check shape
        assert any(v < 0 for v in result.change_in_working_capital) or any(
            v > 0 for v in result.change_in_working_capital
        )


class TestExtractHistoricalFromYfinanceFallbackNames:
    """Test that fallback row names are used when primary names are absent."""

    def _run(self, coro):
        # asyncio.get_event_loop() throws when no running loop exists in 3.11+;
        # use asyncio.run which creates a fresh loop per call. Avoids test
        # interference when other suites close the global loop.
        return asyncio.run(coro)

    @pytest.fixture(autouse=True)
    def mock_yfinance_with_fallback_cashflow_names(self):
        """Use alternative row names for cash flow (as yfinance sometimes returns)."""
        income = _make_income_stmt()
        cols = pd.to_datetime(["2022-12-31", "2021-12-31", "2020-12-31"])
        # Use fallback names instead of primary names
        data = {
            "Cash Flow From Continuing Operating Activities": [122e9, 104e9, 80e9],
            "Cash Flow From Continuing Investing Activities": [-23e9, -15e9, -10e9],
            "Cash Flow From Continuing Financing Activities": [-110e9, -101e9, -86e9],
        }
        cashflow_alt = pd.DataFrame(data, index=cols).T
        mock_ticker = _make_mock_ticker(income, cashflow_alt, _make_info())

        with patch("yfinance.Ticker", return_value=mock_ticker):
            yield mock_ticker

    def test_fallback_cashflow_names_are_used(self):
        from finagent.engine.compute.historical_extractor import (
            extract_historical_from_yfinance,
        )

        result = self._run(extract_historical_from_yfinance("MSFT"))
        # Should still populate cash flows via fallback names
        assert len(result.operating_cash_flow) > 0
        assert len(result.investing_cash_flow) > 0
        assert len(result.financing_cash_flow) > 0

    def test_all_cash_flow_lists_same_length_as_years(self):
        from finagent.engine.compute.historical_extractor import (
            extract_historical_from_yfinance,
        )

        result = self._run(extract_historical_from_yfinance("MSFT"))
        n = len(result.years)
        assert len(result.operating_cash_flow) == n
        assert len(result.investing_cash_flow) == n
        assert len(result.financing_cash_flow) == n


class TestExtractHistoricalFromYfinanceMissingData:
    """Test graceful handling when yfinance returns empty / partial DataFrames."""

    def _run(self, coro):
        # asyncio.get_event_loop() throws when no running loop exists in 3.11+;
        # use asyncio.run which creates a fresh loop per call. Avoids test
        # interference when other suites close the global loop.
        return asyncio.run(coro)

    @pytest.fixture(autouse=True)
    def mock_yfinance_empty_cashflow(self):
        income = _make_income_stmt()
        empty_cashflow = pd.DataFrame()
        mock_ticker = _make_mock_ticker(income, empty_cashflow, _make_info())
        with patch("yfinance.Ticker", return_value=mock_ticker):
            yield mock_ticker

    def test_empty_cashflow_returns_zero_filled_lists(self):
        from finagent.engine.compute.historical_extractor import (
            extract_historical_from_yfinance,
        )

        result = self._run(extract_historical_from_yfinance("XYZ"))
        # Should not raise; cash flow fields must be zero-filled lists aligned to years
        assert len(result.operating_cash_flow) == len(result.years)
        assert all(v == 0.0 for v in result.operating_cash_flow)
        assert len(result.investing_cash_flow) == len(result.years)
        assert all(v == 0.0 for v in result.investing_cash_flow)
        assert len(result.financing_cash_flow) == len(result.years)
        assert all(v == 0.0 for v in result.financing_cash_flow)
        # DCF line items must also be zero-filled — dcf_seed will detect this
        # via sum==0 and fall back to industry medians.
        assert len(result.depreciation_amortization) == len(result.years)
        assert all(v == 0.0 for v in result.depreciation_amortization)
        assert len(result.capital_expenditure) == len(result.years)
        assert all(v == 0.0 for v in result.capital_expenditure)
        assert len(result.change_in_working_capital) == len(result.years)
        assert all(v == 0.0 for v in result.change_in_working_capital)
