"""Tests for finrobot.engine.compute.operators.data_processor.

Hand-calculated verification for all deterministic financial computations.
"""

from __future__ import annotations


import pytest

from finrobot.engine.compute.operators.data_processor import (
    calculate_cagr,
    forecast_financials,
)
from finrobot.engine.models.financial import (
    ForecastResult,
    HistoricalMetrics,
    MarginAssumptions,
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

    def test_forecast_custom_tax_rate(self, historical: HistoricalMetrics):
        """C2 regression: tax_rate must be parameterized, not hardcoded 0.21.

        With tax_rate=0.25 (e.g. EU average):
        Year 1 EBITDA = 421.58e9 * 0.33 = 139.1214e9
        Year 1 net_income = 139.1214e9 * (1 - 0.25) = 104.34105e9
        (vs 109.905906e9 with US 0.21 — ~5% difference)
        """
        result = forecast_financials(
            historical,
            revenue_growth_assumptions=[0.07],
            margin_assumptions=MarginAssumptions(ebitda_margin_target=0.33),
            tax_rate=0.25,
        )
        assert result.net_income[0] == pytest.approx(104.34105e9, rel=1e-4)
        assert result.assumptions.tax_rate == 0.25


class TestForecastSharesFallback:
    """C1 regression: shares_outstanding must never silently fall back to 1.0."""

    def test_zero_eps_no_fallback_to_one(self):
        """When all historical EPS are zero, forecast EPS should be 0.0
        with a warning — not net_income / 1.0."""
        historical = HistoricalMetrics(
            years=[2023, 2024],
            revenue=[100e9, 110e9],
            revenue_growth_yoy=[None, 0.10],
            cogs=[60e9, 66e9],
            gross_profit=[40e9, 44e9],
            gross_margin=[0.40, 0.40],
            sga=[10e9, 11e9],
            sga_ratio=[0.10, 0.10],
            ebitda=[30e9, 33e9],
            ebitda_margin=[0.30, 0.30],
            operating_income=[25e9, 27.5e9],
            operating_margin=[0.25, 0.25],
            net_income=[0.0, 0.0],
            eps=[0.0, 0.0],
            pe_ratio=[None, None],
            cagr_revenue=0.10,
            ticker="TEST",
        )
        result = forecast_financials(
            historical,
            revenue_growth_assumptions=[0.05],
            margin_assumptions=MarginAssumptions(ebitda_margin_target=0.30),
        )
        assert result.eps[0] == 0.0
        assert any("shares_outstanding" in w for w in result.warnings)

    def test_earlier_year_eps_used_when_last_is_zero(self):
        """When last year EPS is 0 but earlier year has valid EPS,
        derive shares from the earlier year."""
        historical = HistoricalMetrics(
            years=[2022, 2023, 2024],
            revenue=[100e9, 110e9, 120e9],
            revenue_growth_yoy=[None, 0.10, 0.0909],
            cogs=[60e9, 66e9, 72e9],
            gross_profit=[40e9, 44e9, 48e9],
            gross_margin=[0.40, 0.40, 0.40],
            sga=[10e9, 11e9, 12e9],
            sga_ratio=[0.10, 0.10, 0.10],
            ebitda=[30e9, 33e9, 36e9],
            ebitda_margin=[0.30, 0.30, 0.30],
            operating_income=[25e9, 27.5e9, 30e9],
            operating_margin=[0.25, 0.25, 0.25],
            net_income=[10e9, 12e9, 0.0],
            eps=[2.0, 2.4, 0.0],  # Last year zero, earlier years valid
            pe_ratio=[None, None, None],
            cagr_revenue=0.0954,
            ticker="TEST",
        )
        result = forecast_financials(
            historical,
            revenue_growth_assumptions=[0.05],
            margin_assumptions=MarginAssumptions(ebitda_margin_target=0.30),
        )
        # Shares derived from year 2023: 12e9 / 2.4 = 5e9
        # Year 1 forecast: revenue = 120e9*1.05 = 126e9
        # EBITDA = 126e9 * 0.30 = 37.8e9
        # Net income = 37.8e9 * (1-0.21) = 29.862e9
        # EPS = 29.862e9 / 5e9 = 5.9724
        assert result.eps[0] == pytest.approx(5.9724, abs=0.01)
        assert not any("shares_outstanding" in w for w in result.warnings)
