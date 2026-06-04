# tests/integration/test_p1_5_acceptance.py
"""P1.5 acceptance gate — verifies code does real deterministic computation.
No LLM involved. Same inputs always produce same outputs."""

from finrobot.engine.models.financial import DCFInputs
from finrobot.engine.compute.operators.dcf import calculate_dcf
from finrobot.engine.compute.operators.wacc import calculate_wacc
from finrobot.engine.compute.operators.multiples import calculate_ev, calculate_multiples
from finrobot.engine.models.financial import CompanyFinancials


class TestDeterminism:
    """These tests verify that financial calculations are deterministic."""

    def test_dcf_deterministic(self):
        """Same inputs ALWAYS produce same implied price."""
        inputs = DCFInputs(
            revenue_base=435_000_000_000,
            revenue_growth_rates=[0.05, 0.05, 0.04, 0.04, 0.03],
            ebitda_margin=0.35,
            capex_pct_revenue=0.05,
            nwc_pct_revenue=0.02,
            tax_rate=0.21,
            risk_free_rate=0.04,
            beta=1.2,
            equity_risk_premium=0.05,
            cost_of_debt=0.04,
            debt_ratio=0.1,
            terminal_growth_rate=0.025,
            shares_outstanding=14_680_000_000,
            net_debt=-50_000_000_000,
            da_pct_revenue=0.0,  # Phase B: required field, pin to 0 for legacy compat
        )
        result1 = calculate_dcf(inputs)
        result2 = calculate_dcf(inputs)
        assert result1.implied_price == result2.implied_price
        assert result1.wacc == result2.wacc
        assert result1.enterprise_value == result2.enterprise_value

    def test_dcf_wacc_override_deterministic(self):
        inputs = DCFInputs(
            revenue_base=100_000_000_000,
            revenue_growth_rates=[0.05, 0.05, 0.04, 0.04, 0.03],
            ebitda_margin=0.35,
            capex_pct_revenue=0.05,
            nwc_pct_revenue=0.02,
            tax_rate=0.21,
            risk_free_rate=0.04,
            beta=1.2,
            equity_risk_premium=0.05,
            cost_of_debt=0.04,
            debt_ratio=0.1,
            terminal_growth_rate=0.025,
            shares_outstanding=1_000_000_000,
            net_debt=10_000_000_000,
            da_pct_revenue=0.0,
        )
        r1 = calculate_dcf(inputs, wacc_override=0.12)
        r2 = calculate_dcf(inputs, wacc_override=0.12)
        assert r1.implied_price == r2.implied_price
        assert r1.cost_of_equity is None
        assert r1.wacc == 0.12
        assert r2.cost_of_equity is None
        assert r2.wacc == 0.12

    def test_wacc_deterministic(self):
        coe1, wacc1 = calculate_wacc(0.04, 1.2, 0.05, 0.04, 0.21, 0.3)
        coe2, wacc2 = calculate_wacc(0.04, 1.2, 0.05, 0.04, 0.21, 0.3)
        assert wacc1 == wacc2

    def test_ev_deterministic(self):
        assert calculate_ev(100, 30, 10) == calculate_ev(100, 30, 10)


class TestNumericalCorrectness:
    """Hand-verified calculations. If these fail, the math is wrong."""

    def test_wacc_hand_calculated(self):
        """rf=4%, beta=1.2, erp=5%, cod=4%, tax=21%, D/(D+E)=30%
        CoE = 4% + 1.2 × 5% = 10%
        WACC = 70% × 10% + 30% × 4% × (1-21%) = 7% + 0.948% = 7.948%"""
        coe, wacc = calculate_wacc(0.04, 1.2, 0.05, 0.04, 0.21, 0.3)
        assert abs(coe - 0.10) < 1e-10
        assert abs(wacc - 0.07948) < 1e-6

    def test_ev_hand_calculated(self):
        assert calculate_ev(1000, 200, 50) == 1150

    def test_dcf_hand_calculated(self):
        """Hand-calculated expected value: ~$303.64. See spec for full workings.
        revenue_base=100B, 5×5% growth, EBITDA=35%, capex=5%, nwc=2%, tax=21%
        wacc_override=10%, tg=2.5%, shares=1B, net_debt=10B

        da_pct_revenue=0 keeps the legacy hand-calc valid after Phase B: with
        D&A=0 the standard formula collapses to EBITDA(1-T) - CapEx - ΔNWC.
        """
        inputs = DCFInputs(
            revenue_base=100_000_000_000,
            revenue_growth_rates=[0.05] * 5,
            ebitda_margin=0.35,
            capex_pct_revenue=0.05,
            nwc_pct_revenue=0.02,
            tax_rate=0.21,
            risk_free_rate=0.04,
            beta=1.2,
            equity_risk_premium=0.05,
            cost_of_debt=0.04,
            debt_ratio=0.1,
            terminal_growth_rate=0.025,
            shares_outstanding=1_000_000_000,
            net_debt=10_000_000_000,
            da_pct_revenue=0.0,
        )
        result = calculate_dcf(inputs, wacc_override=0.10)
        assert abs(result.implied_price - 303.64) < 0.10, (
            f"Expected ~$303.64, got ${result.implied_price:.2f}. "
            "Check FCF formula and discounting logic."
        )

    def test_fcf_formula_explicit(self):
        """Verify FCF = EBIT(1-tax) + D&A - revenue*capex_pct - revenue*nwc_pct.

        With D&A=0 the standard formula collapses to:
            FCF = EBITDA*(1-tax) - revenue*capex_pct - revenue*nwc_pct
        """
        inputs = DCFInputs(
            revenue_base=100_000_000_000,
            revenue_growth_rates=[0.05],
            ebitda_margin=0.35,
            capex_pct_revenue=0.05,
            nwc_pct_revenue=0.02,
            tax_rate=0.21,
            risk_free_rate=0.04,
            beta=1.2,
            equity_risk_premium=0.05,
            cost_of_debt=0.04,
            debt_ratio=0.1,
            terminal_growth_rate=0.025,
            shares_outstanding=1_000_000_000,
            net_debt=10_000_000_000,
            da_pct_revenue=0.0,
        )
        result = calculate_dcf(inputs)
        expected_revenue = 100_000_000_000 * 1.05
        assert abs(result.projected_revenue[0] - expected_revenue) < 1
        expected_ebitda = expected_revenue * 0.35
        assert abs(result.projected_ebitda[0] - expected_ebitda) < 1
        expected_fcf = (
            expected_ebitda * (1 - 0.21) - expected_revenue * 0.05 - expected_revenue * 0.02
        )
        assert abs(result.projected_fcf[0] - expected_fcf) < 1

    def test_multiples_hand_calculated(self):
        c = CompanyFinancials(
            ticker="X",
            revenue=100,
            ebitda=35,
            net_income=10,
            market_cap=500,
            total_debt=30,
            total_cash=10,
            gross_margin=0.4,
            operating_margin=0.2,
        )
        c = calculate_multiples(c)
        # EV = 500 + 30 - 10 = 520
        assert abs(c.enterprise_value - 520) < 1e-9
        assert abs(c.ev_ebitda - 520 / 35) < 1e-9
        assert abs(c.ev_revenue - 520 / 100) < 1e-9
        assert abs(c.pe_ratio - 500 / 10) < 1e-9
