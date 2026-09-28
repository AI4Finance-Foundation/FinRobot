"""Tests for DDM (Dividend Discount Model) compute module.

All expected values are hand-calculated with explicit workings.
DDM formula: Equity Value = Sum(PV of projected dividends) + PV(terminal value)
Terminal Value = D_n * (1 + tg) / (CoE - tg)  (Gordon Growth Model)
Cost of Equity = Risk-Free Rate + Beta * Equity Risk Premium  (CAPM)
"""

import pytest

from finrobot.engine.compute.operators.ddm import calculate_ddm, calculate_ddm_sensitivity
from finrobot.engine.models.financial import DDMInputs


def _make_inputs(**overrides: object) -> DDMInputs:
    """Build DDMInputs with reasonable bank defaults."""
    defaults: dict[str, object] = dict(
        dividend_per_share=3.0,
        dividend_growth_rates=[0.05, 0.05, 0.05, 0.04, 0.03],
        payout_ratio=0.5,
        risk_free_rate=0.045,
        beta=1.0,
        equity_risk_premium=0.055,
        terminal_growth_rate=0.025,
        shares_outstanding=3_000_000_000,
        current_price=150.0,
    )
    defaults.update(overrides)
    return DDMInputs(**defaults)  # type: ignore[arg-type]


class TestDDMBasic:
    """Core DDM calculation tests with hand-calculated expected values."""

    def test_cost_of_equity(self) -> None:
        """CAPM: CoE = 0.045 + 1.0 * 0.055 = 0.10 (10%)."""
        inputs = _make_inputs()
        result = calculate_ddm(inputs)
        assert result.cost_of_equity == pytest.approx(0.10, abs=0.001)

    def test_projected_dividends(self) -> None:
        """Year 1: 3.0 * 1.05 = 3.15, Year 2: 3.15 * 1.05 = 3.3075, etc."""
        inputs = _make_inputs()
        result = calculate_ddm(inputs)
        assert len(result.projected_dividends) == 5
        assert result.projected_dividends[0] == pytest.approx(3.15, abs=0.01)
        assert result.projected_dividends[1] == pytest.approx(3.3075, abs=0.01)
        # Year 3: 3.3075 * 1.05 = 3.472875
        assert result.projected_dividends[2] == pytest.approx(3.472875, abs=0.01)
        # Year 4: 3.472875 * 1.04 = 3.61179
        assert result.projected_dividends[3] == pytest.approx(3.61179, abs=0.01)
        # Year 5: 3.61179 * 1.03 = 3.72014
        assert result.projected_dividends[4] == pytest.approx(3.72014, abs=0.01)

    def test_pv_dividends(self) -> None:
        """PV(D_i) = D_i / (1 + CoE)^i, with CoE = 0.10."""
        inputs = _make_inputs()
        result = calculate_ddm(inputs)
        # PV(D1) = 3.15 / 1.10 = 2.8636...
        assert result.pv_dividends[0] == pytest.approx(3.15 / 1.10, abs=0.01)
        # PV(D2) = 3.3075 / 1.10^2 = 2.7335...
        assert result.pv_dividends[1] == pytest.approx(3.3075 / 1.10**2, abs=0.01)

    def test_terminal_value(self) -> None:
        """Terminal: D5 * (1 + tg) / (CoE - tg) = 3.72014 * 1.025 / (0.10 - 0.025)."""
        inputs = _make_inputs()
        result = calculate_ddm(inputs)
        d5 = result.projected_dividends[-1]
        terminal_dividend = d5 * (1 + 0.025)
        expected_tv = terminal_dividend / (0.10 - 0.025)
        assert result.terminal_dividend == pytest.approx(terminal_dividend, abs=0.01)
        assert result.terminal_value == pytest.approx(expected_tv, abs=0.1)

    def test_pv_terminal(self) -> None:
        """PV(TV) = TV / (1 + CoE)^5."""
        inputs = _make_inputs()
        result = calculate_ddm(inputs)
        expected_pv = result.terminal_value / (1.10**5)
        assert result.pv_terminal == pytest.approx(expected_pv, abs=0.1)

    def test_equity_value_positive(self) -> None:
        """Equity value = sum(PV dividends) + PV(terminal) > 0."""
        inputs = _make_inputs()
        result = calculate_ddm(inputs)
        assert result.equity_value_per_share > 0
        expected = sum(result.pv_dividends) + result.pv_terminal
        assert result.equity_value_per_share == pytest.approx(expected, abs=0.01)

    def test_full_hand_calculation(self) -> None:
        """Full DDM hand calculation.

        Inputs: DPS=3.0, growth=[5%,5%,5%,4%,3%], tg=2.5%, CoE=10%

        Projected dividends:
          Y1: 3.0 * 1.05 = 3.15
          Y2: 3.15 * 1.05 = 3.3075
          Y3: 3.3075 * 1.05 = 3.472875
          Y4: 3.472875 * 1.04 = 3.61179
          Y5: 3.61179 * 1.03 = 3.720144

        PV dividends:
          PV1: 3.15 / 1.10 = 2.86364
          PV2: 3.3075 / 1.21 = 2.73347
          PV3: 3.472875 / 1.331 = 2.60922
          PV4: 3.61179 / 1.4641 = 2.46697
          PV5: 3.720144 / 1.61051 = 2.30989
          Sum PV dividends = 12.98319

        Terminal:
          Terminal div = 3.720144 * 1.025 = 3.81315
          TV = 3.81315 / (0.10 - 0.025) = 50.842
          PV(TV) = 50.842 / 1.61051 = 31.569

        Equity value per share = 12.983 + 31.569 = 44.55
        """
        inputs = _make_inputs()
        result = calculate_ddm(inputs)
        # Allow wider tolerance because of cumulative rounding
        assert result.equity_value_per_share == pytest.approx(44.55, abs=0.1)


class TestDDMTerminalPayout:
    """Terminal payout normalization (consistent two-stage DDM).

    A firm whose growth has slowed to the perpetuity rate can pay out far more
    than its trailing payout. Holding a low trailing payout into perpetuity (the
    naive Gordon terminal) understates value for low-payout, high-ROE compounders
    like banks. ``terminal_payout_ratio`` corrects the terminal dividend.
    """

    def test_none_is_naive_gordon(self) -> None:
        """Default (None) reproduces the constant-payout terminal exactly."""
        inputs = _make_inputs()  # no terminal_payout_ratio
        result = calculate_ddm(inputs)
        d5 = result.projected_dividends[-1]
        # Naive terminal dividend = D5 * (1 + tg), no step-up.
        assert result.terminal_dividend == pytest.approx(d5 * 1.025, abs=0.001)

    def test_terminal_payout_steps_up_terminal_dividend(self) -> None:
        """Terminal dividend = D5 * (1+tg) * (terminal_payout / trailing_payout).

        trailing payout 0.25, terminal payout 0.75 ⇒ 3× step-up.
        """
        inputs = _make_inputs(payout_ratio=0.25, terminal_payout_ratio=0.75)
        result = calculate_ddm(inputs)
        d5 = result.projected_dividends[-1]
        expected = d5 * 1.025 * (0.75 / 0.25)
        assert result.terminal_dividend == pytest.approx(expected, abs=0.001)

    def test_stage1_dividends_unaffected_by_terminal_payout(self) -> None:
        """The step-up touches only the terminal phase, not explicit dividends."""
        naive = calculate_ddm(_make_inputs(payout_ratio=0.25))
        normalized = calculate_ddm(_make_inputs(payout_ratio=0.25, terminal_payout_ratio=0.75))
        assert normalized.projected_dividends == naive.projected_dividends
        assert normalized.pv_dividends_total == pytest.approx(naive.pv_dividends_total, abs=0.001)

    def test_higher_terminal_payout_higher_value(self) -> None:
        """A higher sustainable terminal payout lifts the equity value."""
        low = calculate_ddm(_make_inputs(payout_ratio=0.25, terminal_payout_ratio=0.30))
        high = calculate_ddm(_make_inputs(payout_ratio=0.25, terminal_payout_ratio=0.85))
        assert high.equity_value_per_share > low.equity_value_per_share

    def test_sensitivity_applies_same_stepup(self) -> None:
        """Sensitivity grid uses the same terminal-payout normalization."""
        inputs = _make_inputs(payout_ratio=0.25, terminal_payout_ratio=0.75)
        coe = inputs.risk_free_rate + inputs.beta * inputs.equity_risk_premium
        table = calculate_ddm_sensitivity(inputs, [coe], [inputs.terminal_growth_rate])
        cell = table["implied_prices"][0][0]
        headline = calculate_ddm(inputs).equity_value_per_share
        assert cell is not None
        assert cell == pytest.approx(headline, rel=0.001)

    def test_jpm_consistent_two_stage(self) -> None:
        """End-to-end JPM baseline (yfinance 2026-05-29).

        DPS=$6.00, payout=28.24%, ROE=16.465%, beta=1.023, rf=4.3%, ERP=5.5%,
        tg=2.5%, 5y decay from sustainable g=ROE×(1−payout)=11.82% → 2.5%,
        terminal payout = 1 − tg/ROE = 84.82%.

        The naive constant-payout DDM yields ~$102 (a −66% "strong sell" on a
        bank trading at 14× P/E — indefensible). The consistent two-stage value
        lands ~$243 (−18%), cross-checking the residual-income model (~$241).
        """
        g = 0.16465 * (1 - 0.2824)  # 0.118152
        years = 5
        step = (g - 0.025) / (years - 1)
        schedule = [g - step * i for i in range(years)]
        term_payout = 1 - 0.025 / 0.16465  # 0.84818
        inputs = _make_inputs(
            dividend_per_share=6.00,
            dividend_growth_rates=schedule,
            payout_ratio=0.2824,
            terminal_payout_ratio=term_payout,
            risk_free_rate=0.043,
            beta=1.023,
            equity_risk_premium=0.055,
            terminal_growth_rate=0.025,
            shares_outstanding=2_679_511_418,
            current_price=296.225,
            return_on_equity=0.16465,
            book_value_per_share=128.379,
        )
        result = calculate_ddm(inputs)
        # CoE = 0.043 + 1.023*0.055 = 0.099265
        assert result.cost_of_equity == pytest.approx(0.099265, abs=1e-5)
        # Defensible: same order of magnitude as price, not a 0.3× crash.
        assert 220.0 < result.equity_value_per_share < 270.0
        assert -0.30 < result.upside < -0.05


class TestDDMEdgeCases:
    """Edge cases and error handling."""

    def test_terminal_growth_exceeds_coe_pydantic(self) -> None:
        """Terminal growth > 0.05 is rejected by Pydantic field constraint."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            _make_inputs(
                risk_free_rate=0.045,
                beta=0.5,
                equity_risk_premium=0.04,
                terminal_growth_rate=0.07,  # > le=0.05 constraint
            )

    def test_terminal_growth_exceeds_coe_at_compute(self) -> None:
        """Terminal growth >= cost of equity raises ValueError in calculate_ddm.

        When CoE is very low (e.g., beta=0, rf=0.03 => CoE=0.03) and
        terminal_growth is within Pydantic bounds but >= CoE.
        """
        inputs = _make_inputs(
            risk_free_rate=0.03,
            beta=0.0,  # CoE = 0.03 + 0 * 0.055 = 0.03
            equity_risk_premium=0.055,
            terminal_growth_rate=0.04,  # 0.04 >= 0.03
        )
        with pytest.raises(ValueError, match="Terminal growth"):
            calculate_ddm(inputs)

    def test_terminal_growth_equals_coe(self) -> None:
        """Terminal growth == cost of equity should also raise ValueError."""
        # CoE = 0.03 + 0.0 * 0.055 = 0.03; tg = 0.03
        inputs = _make_inputs(
            risk_free_rate=0.03,
            beta=0.0,
            equity_risk_premium=0.055,
            terminal_growth_rate=0.03,
        )
        with pytest.raises(ValueError, match="Terminal growth"):
            calculate_ddm(inputs)

    def test_single_period(self) -> None:
        """DDM with only 1 growth period."""
        inputs = _make_inputs(dividend_growth_rates=[0.05])
        result = calculate_ddm(inputs)
        assert len(result.projected_dividends) == 1
        assert result.projected_dividends[0] == pytest.approx(3.15, abs=0.01)

    def test_zero_growth(self) -> None:
        """DDM with 0% growth — should still produce valid results."""
        inputs = _make_inputs(
            dividend_growth_rates=[0.0, 0.0, 0.0],
            terminal_growth_rate=0.0,
        )
        result = calculate_ddm(inputs)
        # All projected dividends equal 3.0 (no growth)
        for d in result.projected_dividends:
            assert d == pytest.approx(3.0, abs=0.01)
        # Terminal: 3.0 * 1.0 / 0.10 = 30.0
        assert result.terminal_value == pytest.approx(30.0, abs=0.1)

    def test_deterministic(self) -> None:
        """Same inputs produce same outputs."""
        inputs = _make_inputs()
        r1 = calculate_ddm(inputs)
        r2 = calculate_ddm(inputs)
        assert r1.equity_value_per_share == r2.equity_value_per_share
        assert r1.cost_of_equity == r2.cost_of_equity

    def test_higher_coe_lower_value(self) -> None:
        """Higher cost of equity should produce lower equity value."""
        inputs_low = _make_inputs(beta=0.8)  # CoE = 0.045 + 0.8*0.055 = 0.089
        inputs_high = _make_inputs(beta=1.5)  # CoE = 0.045 + 1.5*0.055 = 0.1275
        r_low = calculate_ddm(inputs_low)
        r_high = calculate_ddm(inputs_high)
        assert r_low.equity_value_per_share > r_high.equity_value_per_share

    def test_higher_growth_higher_value(self) -> None:
        """Higher dividend growth should produce higher equity value."""
        inputs_low = _make_inputs(dividend_growth_rates=[0.02] * 5)
        inputs_high = _make_inputs(dividend_growth_rates=[0.08] * 5)
        r_low = calculate_ddm(inputs_low)
        r_high = calculate_ddm(inputs_high)
        assert r_high.equity_value_per_share > r_low.equity_value_per_share

    def test_upside_property(self) -> None:
        """Upside = equity_value / current_price - 1."""
        inputs = _make_inputs(current_price=40.0)
        result = calculate_ddm(inputs)
        expected_upside = result.equity_value_per_share / 40.0 - 1
        assert result.upside == pytest.approx(expected_upside, abs=0.001)


class TestDDMSensitivity:
    """Sensitivity table tests."""

    def test_sensitivity_dimensions(self) -> None:
        """Table has correct dimensions."""
        inputs = _make_inputs()
        coe_range = [0.08, 0.09, 0.10]
        tg_range = [0.02, 0.025]
        table = calculate_ddm_sensitivity(inputs, coe_range, tg_range)
        prices = table["implied_prices"]
        assert len(prices) == 3  # type: ignore[arg-type]
        assert all(len(row) == 2 for row in prices)  # type: ignore[union-attr]

    def test_sensitivity_none_where_tg_gte_coe(self) -> None:
        """Cells where tg >= CoE should be None."""
        inputs = _make_inputs()
        coe_range = [0.05]
        tg_range = [0.03, 0.05, 0.06]  # 0.05 == CoE, 0.06 > CoE
        table = calculate_ddm_sensitivity(inputs, coe_range, tg_range)
        row = table["implied_prices"][0]  # type: ignore[index]
        assert row[0] is not None  # 0.03 < 0.05
        assert row[1] is None  # 0.05 == 0.05
        assert row[2] is None  # 0.06 > 0.05

    def test_sensitivity_higher_coe_lower_price(self) -> None:
        """Higher CoE should produce lower equity value (all else equal)."""
        inputs = _make_inputs()
        coe_range = [0.08, 0.09, 0.10, 0.11, 0.12]
        tg_range = [0.02]
        table = calculate_ddm_sensitivity(inputs, coe_range, tg_range)
        prices = [row[0] for row in table["implied_prices"] if row[0] is not None]  # type: ignore[union-attr, index]
        assert prices == sorted(prices, reverse=True)


class TestDDMModels:
    """Tests for DDMInputs and DDMResult Pydantic models."""

    def test_ddm_inputs_validation(self) -> None:
        """DDMInputs should enforce field constraints."""
        with pytest.raises(Exception):
            DDMInputs(
                dividend_per_share=-1.0,  # must be > 0
                dividend_growth_rates=[0.05],
                payout_ratio=0.5,
                risk_free_rate=0.045,
                beta=1.0,
                equity_risk_premium=0.055,
                terminal_growth_rate=0.025,
                shares_outstanding=3e9,
                current_price=150.0,
            )

    def test_ddm_inputs_optional_bank_fields(self) -> None:
        """Bank-specific fields should be optional."""
        inputs = _make_inputs(
            book_value_per_share=55.0,
            return_on_equity=0.12,
            tier1_ratio=0.14,
            net_interest_margin=0.028,
        )
        assert inputs.book_value_per_share == 55.0
        assert inputs.return_on_equity == 0.12
        assert inputs.tier1_ratio == 0.14
        assert inputs.net_interest_margin == 0.028

    def test_ddm_inputs_without_bank_fields(self) -> None:
        """Bank-specific fields default to None."""
        inputs = _make_inputs()
        assert inputs.book_value_per_share is None
        assert inputs.return_on_equity is None
        assert inputs.tier1_ratio is None
        assert inputs.net_interest_margin is None


class TestNonLifeInsurerDegradation:
    """The standalone DDM degrades to relative valuation for a non-life insurer
    (2026-07-06). Its underwriting-cycle ROE + buyback-driven low payout blow the DDM
    to multiples of price even at through-cycle ROE (live: ALL DDM +530% / TRV +177%),
    so ddm_params emits structured=None + a machine-readable P/B-comps routing before
    any fetch — a traceable degradation, not a refusal. A life insurer / bank does NOT
    hit this gate (covered by TestIsNonLifeInsurer)."""

    def _insurer_fd(self, industry: str):
        from datetime import datetime, timezone

        from finrobot.engine.models.financial import (
            BalanceSheet,
            FinancialData,
            IncomeStatement,
            MarketData,
            ValuationMetrics,
        )

        return FinancialData(
            ticker="ALL",
            income=IncomeStatement(revenue=6e10, ebitda=1e10, net_income=1e10),
            balance=BalanceSheet(total_debt=8e9, total_cash=5e9),
            market=MarketData(
                current_price=250.0,
                shares_outstanding=2.6e8,
                market_cap=6.5e10,
                industry=industry,
                sector="Financial Services",
            ),
            valuation=ValuationMetrics(),
            data_source="test",
            timestamp=datetime.now(tz=timezone.utc),
        )

    async def test_ddm_seed_degrades_for_non_life_insurer(self) -> None:
        from unittest.mock import MagicMock

        from finrobot.engine.pipelines.ddm import _execute_ddm_calc, _execute_ddm_seed

        fd = self._insurer_fd("Insurance - Property & Casualty")
        ctx: dict[str, object] = {"historical_data": fd}
        # Gate fires BEFORE any data-layer fetch, so deps is never touched.
        seed = await _execute_ddm_seed(MagicMock(), MagicMock(), "", ctx, "ALL")
        assert seed.structured is None
        assert "not applicable" in seed.text.lower()
        assert "p/b" in seed.text.lower() or "comps" in seed.text.lower()

        # ddm_calc passes the degraded state through (no meaningless DDMResult).
        ctx["ddm_params"] = seed.structured
        calc = await _execute_ddm_calc(MagicMock(), MagicMock(), "", ctx, "ALL")
        assert calc.structured is None
