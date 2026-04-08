"""Tests for finagent.engine.compute.data_processor.

Hand-calculated verification for all deterministic financial computations.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from finagent.engine.compute.data_processor import (
    calculate_cagr,
    extract_historical_metrics,
    forecast_financials,
)
from finagent.engine.models.financial import (
    FinancialData,
    ForecastResult,
    HistoricalMetrics,
    MarginAssumptions,
    PriceHistory,
)


# ---------------------------------------------------------------------------
# calculate_cagr
# ---------------------------------------------------------------------------


class TestCalculateCagr:
    def test_basic_cagr(self):
        """CAGR = (end/start)^(1/n) - 1. Source: CFA Institute.
        100 -> 150 over 5 years = (150/100)^(1/5) - 1 ~ 0.08447"""
        result = calculate_cagr(100, 150, 5)
        assert result == pytest.approx(0.08447, abs=0.001)

    def test_cagr_one_year(self):
        """100 -> 200 in 1 year = 100% growth."""
        result = calculate_cagr(100, 200, 1)
        assert result == pytest.approx(1.0)

    def test_cagr_zero_start(self):
        assert calculate_cagr(0, 100, 5) is None

    def test_cagr_negative_start(self):
        assert calculate_cagr(-100, 100, 5) is None

    def test_cagr_zero_years(self):
        assert calculate_cagr(100, 200, 0) is None

    def test_cagr_negative_years(self):
        assert calculate_cagr(100, 200, -3) is None

    def test_cagr_negative_end(self):
        """Negative end value: formula still valid (declining revenue)."""
        # (50/100)^(1/3) - 1 = 0.7937.. - 1 = -0.2063
        result = calculate_cagr(100, 50, 3)
        assert result is not None
        assert result == pytest.approx(-0.2063, abs=0.001)

    def test_cagr_same_value(self):
        """No growth: CAGR = 0."""
        result = calculate_cagr(100, 100, 5)
        assert result == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Helpers to construct FinancialData
# ---------------------------------------------------------------------------


def _make_financial_data(
    ticker: str,
    year: int,
    revenue: float,
    ebitda: float,
    net_income: float,
    gross_margin: float,
    operating_margin: float,
    market_cap: float,
    shares_outstanding: float,
    current_price: float,
    sga_expense: float | None = None,
) -> FinancialData:
    return FinancialData(
        ticker=ticker,
        timestamp=datetime(year, 12, 31),
        revenue=revenue,
        ebitda=ebitda,
        net_income=net_income,
        gross_margin=gross_margin,
        operating_margin=operating_margin,
        market_cap=market_cap,
        shares_outstanding=shares_outstanding,
        current_price=current_price,
        sga_expense=sga_expense,
    )


# ---------------------------------------------------------------------------
# extract_historical_metrics
# ---------------------------------------------------------------------------


class TestExtractHistoricalMetrics:
    """3 years of Apple-like data with known values for hand verification.

    Year 1 (2022): rev=300e9, ebitda=100e9, ni=70e9, gm=0.43, om=0.30
    Year 2 (2023): rev=350e9, ebitda=120e9, ni=85e9, gm=0.44, om=0.31
    Year 3 (2024): rev=394e9, ebitda=130e9, ni=95e9, gm=0.45, om=0.32
    """

    @pytest.fixture()
    def three_year_data(self) -> list[FinancialData]:
        return [
            _make_financial_data(
                "AAPL", 2022, 300e9, 100e9, 70e9, 0.43, 0.30,
                market_cap=2400e9, shares_outstanding=15e9, current_price=160.0,
                sga_expense=24e9,
            ),
            _make_financial_data(
                "AAPL", 2023, 350e9, 120e9, 85e9, 0.44, 0.31,
                market_cap=2800e9, shares_outstanding=15e9, current_price=186.67,
                sga_expense=28e9,
            ),
            _make_financial_data(
                "AAPL", 2024, 394e9, 130e9, 95e9, 0.45, 0.32,
                market_cap=2970e9, shares_outstanding=15e9, current_price=198.0,
                sga_expense=32e9,
            ),
        ]

    def test_years_sorted_oldest_first(self, three_year_data: list[FinancialData]):
        result = extract_historical_metrics(three_year_data)
        assert result.years == [2022, 2023, 2024]

    def test_revenue_values(self, three_year_data: list[FinancialData]):
        result = extract_historical_metrics(three_year_data)
        assert result.revenue == [300e9, 350e9, 394e9]

    def test_revenue_growth_yoy(self, three_year_data: list[FinancialData]):
        """YoY growth: first year None, then (350-300)/300 ~ 0.1667,
        (394-350)/350 ~ 0.1257."""
        result = extract_historical_metrics(three_year_data)
        assert result.revenue_growth_yoy[0] is None
        assert result.revenue_growth_yoy[1] == pytest.approx(0.1667, abs=0.001)
        assert result.revenue_growth_yoy[2] == pytest.approx(0.1257, abs=0.001)

    def test_cogs_from_gross_margin(self, three_year_data: list[FinancialData]):
        """COGS = revenue * (1 - gross_margin).
        Year 1: 300e9 * (1-0.43) = 171e9
        Year 2: 350e9 * (1-0.44) = 196e9
        Year 3: 394e9 * (1-0.45) = 216.7e9"""
        result = extract_historical_metrics(three_year_data)
        assert result.cogs[0] == pytest.approx(171e9, rel=1e-6)
        assert result.cogs[1] == pytest.approx(196e9, rel=1e-6)
        assert result.cogs[2] == pytest.approx(216.7e9, rel=1e-6)

    def test_gross_profit(self, three_year_data: list[FinancialData]):
        """Gross profit = revenue - COGS.
        Year 1: 300e9 - 171e9 = 129e9"""
        result = extract_historical_metrics(three_year_data)
        assert result.gross_profit[0] == pytest.approx(129e9, rel=1e-6)
        assert result.gross_profit[1] == pytest.approx(154e9, rel=1e-6)
        assert result.gross_profit[2] == pytest.approx(177.3e9, rel=1e-6)

    def test_gross_margin_passthrough(self, three_year_data: list[FinancialData]):
        result = extract_historical_metrics(three_year_data)
        assert result.gross_margin == [0.43, 0.44, 0.45]

    def test_ebitda_margin(self, three_year_data: list[FinancialData]):
        """EBITDA margin = ebitda / revenue.
        Year 1: 100e9/300e9 ~ 0.3333
        Year 2: 120e9/350e9 ~ 0.3429
        Year 3: 130e9/394e9 ~ 0.3299"""
        result = extract_historical_metrics(three_year_data)
        assert result.ebitda_margin[0] == pytest.approx(0.3333, abs=0.001)
        assert result.ebitda_margin[1] == pytest.approx(0.3429, abs=0.001)
        assert result.ebitda_margin[2] == pytest.approx(0.3299, abs=0.001)

    def test_operating_margin_passthrough(self, three_year_data: list[FinancialData]):
        result = extract_historical_metrics(three_year_data)
        assert result.operating_margin == [0.30, 0.31, 0.32]

    def test_operating_income(self, three_year_data: list[FinancialData]):
        """Operating income = revenue * operating_margin.
        Year 1: 300e9 * 0.30 = 90e9"""
        result = extract_historical_metrics(three_year_data)
        assert result.operating_income[0] == pytest.approx(90e9, rel=1e-6)
        assert result.operating_income[1] == pytest.approx(108.5e9, rel=1e-6)
        assert result.operating_income[2] == pytest.approx(126.08e9, rel=1e-6)

    def test_sga_and_ratio(self, three_year_data: list[FinancialData]):
        """SGA ratio = sga / revenue.
        Year 1: 24e9/300e9 = 0.08"""
        result = extract_historical_metrics(three_year_data)
        assert result.sga == [24e9, 28e9, 32e9]
        assert result.sga_ratio[0] == pytest.approx(0.08, abs=0.001)
        assert result.sga_ratio[1] == pytest.approx(0.08, abs=0.001)
        assert result.sga_ratio[2] == pytest.approx(0.08122, abs=0.001)

    def test_eps(self, three_year_data: list[FinancialData]):
        """EPS = net_income / shares_outstanding.
        Year 1: 70e9 / 15e9 ~ 4.667"""
        result = extract_historical_metrics(three_year_data)
        assert result.eps[0] == pytest.approx(4.667, abs=0.01)
        assert result.eps[1] == pytest.approx(5.667, abs=0.01)
        assert result.eps[2] == pytest.approx(6.333, abs=0.01)

    def test_pe_ratio_without_price_data(self, three_year_data: list[FinancialData]):
        """Without PriceHistory, PE ratio is None for all years."""
        result = extract_historical_metrics(three_year_data)
        assert all(pe is None for pe in result.pe_ratio)
        assert result.price_data_available is False

    def test_pe_ratio_with_price_data(self, three_year_data: list[FinancialData]):
        """With PriceHistory, PE = current_price / EPS.
        EPS year3 = 6.333, price = 198.0, PE = 198.0/6.333 ~ 31.26"""
        price = PriceHistory(
            ticker="AAPL", period="1y", data_points=252,
            current_price=198.0, high_52w=210.0, low_52w=150.0, avg_price=180.0,
        )
        result = extract_historical_metrics(three_year_data, price_data=price)
        assert result.price_data_available is True
        # PE = current_price / EPS (hand-calculated literals)
        # Year 1: 198.0 / 4.667 = 42.43
        # Year 3: 198.0 / 6.333 = 31.27
        assert result.pe_ratio[0] == pytest.approx(42.43, abs=0.1)
        assert result.pe_ratio[2] == pytest.approx(31.27, abs=0.1)

    def test_cagr_revenue(self, three_year_data: list[FinancialData]):
        """Revenue CAGR over 2 periods (3 data points):
        (394e9 / 300e9)^(1/2) - 1 ~ 0.1460"""
        result = extract_historical_metrics(three_year_data)
        assert result.cagr_revenue is not None
        assert result.cagr_revenue == pytest.approx(0.1460, abs=0.001)

    def test_ticker(self, three_year_data: list[FinancialData]):
        result = extract_historical_metrics(three_year_data)
        assert result.ticker == "AAPL"

    def test_unsorted_input_gets_sorted(self):
        """Data passed in reverse order should still sort oldest-first."""
        data = [
            _make_financial_data(
                "MSFT", 2024, 200e9, 80e9, 60e9, 0.70, 0.40,
                market_cap=3000e9, shares_outstanding=7.5e9, current_price=400.0,
            ),
            _make_financial_data(
                "MSFT", 2022, 150e9, 60e9, 45e9, 0.68, 0.38,
                market_cap=2100e9, shares_outstanding=7.5e9, current_price=280.0,
            ),
        ]
        result = extract_historical_metrics(data)
        assert result.years == [2022, 2024]
        assert result.revenue == [150e9, 200e9]

    def test_sga_none_defaults_to_zero(self):
        """When sga_expense is None, use 0.0."""
        data = [
            _make_financial_data(
                "GOOG", 2023, 300e9, 100e9, 70e9, 0.56, 0.27,
                market_cap=1500e9, shares_outstanding=6e9, current_price=250.0,
                sga_expense=None,
            ),
        ]
        result = extract_historical_metrics(data)
        assert result.sga == [0.0]
        assert result.sga_ratio == [0.0]

    def test_single_year_no_growth(self):
        """Single year of data: growth is None, CAGR is None."""
        data = [
            _make_financial_data(
                "GOOG", 2024, 300e9, 100e9, 70e9, 0.56, 0.27,
                market_cap=1500e9, shares_outstanding=6e9, current_price=250.0,
            ),
        ]
        result = extract_historical_metrics(data)
        assert result.revenue_growth_yoy == [None]
        assert result.cagr_revenue is None


# ---------------------------------------------------------------------------
# forecast_financials
# ---------------------------------------------------------------------------


class TestForecastFinancials:
    """Deterministic forecast with hand-calculated verification.

    Base (from historical):
    - Last year revenue = 394e9
    - Last year = 2024
    - shares_outstanding derived from last year data
    - Historical avg EBITDA margin ~ (0.3333+0.3429+0.3299)/3 ~ 0.3354
    - Historical avg gross margin = (0.43+0.44+0.45)/3 ~ 0.44
    - Historical avg SGA ratio = (0.08+0.08+0.08122)/3 ~ 0.08041

    Growth assumptions: [0.07, 0.06, 0.05]
    """

    @pytest.fixture()
    def historical(self) -> HistoricalMetrics:
        return HistoricalMetrics(
            years=[2022, 2023, 2024],
            revenue=[300e9, 350e9, 394e9],
            revenue_growth_yoy=[None, 0.1667, 0.1257],
            cogs=[171e9, 196e9, 216.7e9],
            gross_profit=[129e9, 154e9, 177.3e9],
            gross_margin=[0.43, 0.44, 0.45],
            sga=[24e9, 28e9, 32e9],
            sga_ratio=[0.08, 0.08, 0.08122],
            ebitda=[100e9, 120e9, 130e9],
            ebitda_margin=[0.3333, 0.3429, 0.3299],
            operating_income=[90e9, 108.5e9, 126.08e9],
            operating_margin=[0.30, 0.31, 0.32],
            net_income=[70e9, 85e9, 95e9],
            eps=[4.667, 5.667, 6.333],
            pe_ratio=[None, None, None],
            cagr_revenue=0.146,
            ticker="AAPL",
        )

    def test_forecast_revenue_year1(self, historical: HistoricalMetrics):
        """Year 1 revenue: 394e9 * 1.07 = 421.58e9"""
        result = forecast_financials(
            historical,
            revenue_growth_assumptions=[0.07, 0.06, 0.05],
            margin_assumptions=MarginAssumptions(ebitda_margin_target=0.33),
        )
        assert result.revenue[0] == pytest.approx(421.58e9, rel=1e-4)

    def test_forecast_revenue_year2(self, historical: HistoricalMetrics):
        """Year 2 revenue: 421.58e9 * 1.06 = 446.8748e9"""
        result = forecast_financials(
            historical,
            revenue_growth_assumptions=[0.07, 0.06, 0.05],
            margin_assumptions=MarginAssumptions(ebitda_margin_target=0.33),
        )
        assert result.revenue[1] == pytest.approx(446.8748e9, rel=1e-4)

    def test_forecast_revenue_year3(self, historical: HistoricalMetrics):
        """Year 3 revenue: 446.8748e9 * 1.05 = 469.21854e9"""
        result = forecast_financials(
            historical,
            revenue_growth_assumptions=[0.07, 0.06, 0.05],
            margin_assumptions=MarginAssumptions(ebitda_margin_target=0.33),
        )
        assert result.revenue[2] == pytest.approx(469.21854e9, rel=1e-4)

    def test_forecast_ebitda_with_target_margin(self, historical: HistoricalMetrics):
        """EBITDA = revenue * ebitda_margin_target.
        Year 1: 421.58e9 * 0.33 = 139.1214e9"""
        result = forecast_financials(
            historical,
            revenue_growth_assumptions=[0.07, 0.06, 0.05],
            margin_assumptions=MarginAssumptions(ebitda_margin_target=0.33),
        )
        assert result.ebitda[0] == pytest.approx(139.1214e9, rel=1e-4)

    def test_forecast_net_income(self, historical: HistoricalMetrics):
        """Net income = EBITDA * (1 - tax_rate).
        Year 1: 139.1214e9 * (1 - 0.21) = 109.905906e9"""
        result = forecast_financials(
            historical,
            revenue_growth_assumptions=[0.07, 0.06, 0.05],
            margin_assumptions=MarginAssumptions(ebitda_margin_target=0.33),
        )
        assert result.net_income[0] == pytest.approx(109.905906e9, rel=1e-4)

    def test_forecast_eps(self, historical: HistoricalMetrics):
        """EPS = net_income / shares_outstanding.

        Hand calculation:
        1. shares = last_ni / last_eps = 95e9 / 6.333 ≈ 15.001e9
        2. Year 1 net_income = 109.905906e9 (from test_forecast_net_income)
        3. Year 1 EPS = 109.905906e9 / 15.001e9 ≈ 7.327
        """
        result = forecast_financials(
            historical,
            revenue_growth_assumptions=[0.07, 0.06, 0.05],
            margin_assumptions=MarginAssumptions(ebitda_margin_target=0.33),
        )
        assert result.eps[0] == pytest.approx(7.327, abs=0.01)

    def test_forecast_years(self, historical: HistoricalMetrics):
        """Forecast years continue from last historical year."""
        result = forecast_financials(
            historical,
            revenue_growth_assumptions=[0.07, 0.06, 0.05],
            margin_assumptions=MarginAssumptions(ebitda_margin_target=0.33),
        )
        assert result.years == [2025, 2026, 2027]

    def test_forecast_uses_historical_avg_margin_when_no_target(
        self, historical: HistoricalMetrics
    ):
        """When no ebitda_margin_target, use avg of historical EBITDA margins.

        Hand calculation:
        avg margin = (0.3333 + 0.3429 + 0.3299) / 3 = 0.33537
        year 1 revenue = 394e9 * 1.07 = 421.58e9
        year 1 ebitda = 421.58e9 * 0.33537 = 141.393e9
        """
        result = forecast_financials(
            historical,
            revenue_growth_assumptions=[0.07],
            margin_assumptions=MarginAssumptions(),  # no targets
        )
        assert result.assumptions.ebitda_margin == pytest.approx(0.33537, rel=1e-4)
        assert result.ebitda[0] == pytest.approx(141.393e9, rel=1e-3)

    def test_forecast_assumptions_recorded(self, historical: HistoricalMetrics):
        """ForecastAssumptions must record the exact values used."""
        result = forecast_financials(
            historical,
            revenue_growth_assumptions=[0.07, 0.06, 0.05],
            margin_assumptions=MarginAssumptions(ebitda_margin_target=0.33),
        )
        assert result.assumptions.revenue_growth_rates == [0.07, 0.06, 0.05]
        assert result.assumptions.ebitda_margin == 0.33
        assert result.assumptions.tax_rate == 0.21

    def test_forecast_returns_pydantic_model(self, historical: HistoricalMetrics):
        result = forecast_financials(
            historical,
            revenue_growth_assumptions=[0.07],
            margin_assumptions=MarginAssumptions(ebitda_margin_target=0.33),
        )
        assert isinstance(result, ForecastResult)

    def test_forecast_length_matches_assumptions(self, historical: HistoricalMetrics):
        """Number of forecast years = number of growth assumptions."""
        for n in [1, 2, 3, 5]:
            growth = [0.05] * n
            result = forecast_financials(
                historical,
                revenue_growth_assumptions=growth,
                margin_assumptions=MarginAssumptions(ebitda_margin_target=0.33),
            )
            assert len(result.years) == n
            assert len(result.revenue) == n
            assert len(result.ebitda) == n
            assert len(result.net_income) == n
            assert len(result.eps) == n
