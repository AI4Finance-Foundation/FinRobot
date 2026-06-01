"""Tests for dcf_seed — single authoritative DCFInputs builder.

What these tests verify beyond "code runs":
- AAPL-like fixture (FY24 figures) produces DCFInputs in the right ballpark
  vs market consensus. Every assumption traces back to either ticker history
  or industry median.
- da_pct_revenue is *never None* — the simplified-FCF branch is gone.
- Provenance dict has an entry for every DCFInputs field — the UI relies on
  this for the assumption-source tooltip.
- Falls through history → industry default → Total Market cleanly when each
  layer's data is missing.
- _decay_growth_schedule produces monotone-decreasing curves landing exactly
  on terminal_growth at year N.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from finrobot.engine.compute.dcf_seed import (
    _cost_of_debt,
    _decay_growth_schedule,
    _effective_tax_rate,
    _median_ratio,
    _median_recent,
    seed_dcf_inputs,
)
from finrobot.engine.models.financial import (
    BalanceSheet,
    FinancialData,
    HistoricalMetrics,
    IncomeStatement,
    MarketData,
    ValuationMetrics,
)


# ---------------------------------------------------------------------------
# Helpers — module-level fixtures simulating AAPL FY24 data
# ---------------------------------------------------------------------------


def _aapl_financials() -> FinancialData:
    """Snapshot resembling AAPL FY24 (Sep 2024)."""
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


def _aapl_historical() -> HistoricalMetrics:
    """4-year history aligned to FY21–FY24 — oldest first."""
    revenue = [365_817_000_000, 394_328_000_000, 383_285_000_000, 391_035_000_000]
    ebitda = [123_136_000_000, 130_541_000_000, 125_820_000_000, 131_900_000_000]
    return HistoricalMetrics(
        years=[2021, 2022, 2023, 2024],
        revenue=revenue,
        revenue_growth_yoy=[None, 0.078, -0.028, 0.020],
        cogs=[212e9, 223e9, 214e9, 210e9],
        gross_profit=[152e9, 170e9, 169e9, 180e9],
        gross_margin=[0.42, 0.43, 0.44, 0.46],
        sga=[22e9, 25e9, 25e9, 26e9],
        sga_ratio=[0.06, 0.063, 0.065, 0.066],
        ebitda=ebitda,
        ebitda_margin=[e / r for e, r in zip(ebitda, revenue)],
        operating_income=[108e9, 119e9, 114e9, 122e9],
        operating_margin=[0.296, 0.302, 0.297, 0.312],
        net_income=[94e9, 99e9, 96e9, 93e9],
        eps=[5.61, 6.11, 6.13, 6.08],
        pe_ratio=[None, None, None, 37.4],
        cagr_revenue=0.022,
        ticker="AAPL",
        operating_cash_flow=[104e9, 122e9, 110e9, 118e9],
        investing_cash_flow=[-15e9, -23e9, -3e9, -10e9],
        financing_cash_flow=[-93e9, -110e9, -108e9, -122e9],
        depreciation_amortization=[11_284_000_000, 11_104_000_000, 11_519_000_000, 11_445_000_000],
        capital_expenditure=[11_085_000_000, 10_708_000_000, 10_959_000_000, 9_447_000_000],
        change_in_working_capital=[-2_500_000_000, 1_200_000_000, -800_000_000, 1_900_000_000],
    )


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


class TestMedianRatio:
    def test_returns_median_of_pairs(self):
        # 10/100=0.10, 20/100=0.20, 30/100=0.30 → median 0.20
        assert _median_ratio([10, 20, 30], [100, 100, 100], min_samples=3) == pytest.approx(0.20)

    def test_returns_none_when_too_few_samples(self):
        assert _median_ratio([10], [100], min_samples=2) is None

    def test_returns_none_when_denominator_zero(self):
        assert _median_ratio([10, 20], [0, 0], min_samples=2) is None

    def test_returns_none_when_all_numerator_zero(self):
        """zero-filled cashflow row should fall through to industry default."""
        assert _median_ratio([0, 0, 0], [100, 100, 100], min_samples=3) is None

    def test_uses_most_recent_window(self):
        """Older years shouldn't pull the median around — use last min_samples."""
        # First two are weird outliers, last two are stable
        result = _median_ratio([1000, -50, 30, 30], [100, 100, 100, 100], min_samples=2)
        assert result == pytest.approx(0.30)


class TestMedianRecent:
    def test_returns_median_of_recent_window(self):
        assert _median_recent([0.20, 0.30, 0.32, 0.33], min_samples=2) == pytest.approx(0.325)

    def test_skips_zero_values(self):
        assert _median_recent([0.0, 0.30], min_samples=2) == pytest.approx(0.30)

    def test_returns_none_when_all_zero(self):
        assert _median_recent([0.0, 0.0, 0.0], min_samples=2) is None


class TestDecayGrowthSchedule:
    def test_lands_on_terminal_growth_at_end(self):
        sched = _decay_growth_schedule(0.20, 0.025, years=5)
        assert sched[0] == pytest.approx(0.20)
        assert sched[-1] == pytest.approx(0.025)

    def test_monotone_decreasing(self):
        sched = _decay_growth_schedule(0.20, 0.025, years=5)
        for a, b in zip(sched, sched[1:]):
            assert a >= b, f"non-monotone at {sched}"

    def test_single_year_returns_base(self):
        sched = _decay_growth_schedule(0.15, 0.025, years=1)
        assert sched == [0.15]

    def test_mature_firm_below_gdp_holds_flat(self):
        """AAPL-like edge: 4y CAGR 2.2% < terminal 2.5%. Don't artificially
        boost up to GDP — hold flat; perpetuity handles eventual catch-up."""
        sched = _decay_growth_schedule(0.022, 0.025, years=5)
        assert sched == [0.022] * 5

    def test_exactly_at_terminal_holds_flat(self):
        sched = _decay_growth_schedule(0.025, 0.025, years=4)
        assert sched == [0.025] * 4


class TestCostOfDebt:
    def test_normal_case(self):
        # 3.75B / 106B = 3.54% ≈ AAPL FY24
        rate = _cost_of_debt(3_750_000_000, 106_000_000_000)
        assert rate == pytest.approx(0.0354, abs=0.001)

    def test_clamps_below_floor(self):
        rate = _cost_of_debt(1, 100_000_000_000)  # 0.0000001%
        assert rate == 0.02  # floor

    def test_clamps_above_cap(self):
        rate = _cost_of_debt(50e9, 100e9)  # 50%
        assert rate == 0.20  # cap

    def test_returns_none_when_debt_zero(self):
        assert _cost_of_debt(1e9, 0) is None

    def test_returns_none_when_interest_missing(self):
        assert _cost_of_debt(None, 100e9) is None


# ---------------------------------------------------------------------------
# Main seed_dcf_inputs — end-to-end AAPL fixture
# ---------------------------------------------------------------------------


class TestSeedDcfInputsAapl:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.financials = _aapl_financials()
        self.historical = _aapl_historical()
        self.inputs = seed_dcf_inputs(self.financials, self.historical)

    def test_revenue_base_is_latest_annual(self):
        assert self.inputs.revenue_base == pytest.approx(391_035_000_000)

    def test_da_pct_revenue_is_never_none(self):
        """The simplified-FCF branch is gone — da_pct_revenue must always be a number."""
        assert self.inputs.da_pct_revenue is not None
        assert self.inputs.da_pct_revenue > 0

    def test_da_pct_matches_historical_median(self):
        """AAPL D&A / Revenue ~ 11.4B / 391B ≈ 2.9%."""
        assert self.inputs.da_pct_revenue == pytest.approx(0.029, abs=0.005)

    def test_capex_pct_matches_historical_median(self):
        """AAPL CapEx / Revenue ~ 9.4B / 391B ≈ 2.4-2.7%."""
        assert 0.02 <= self.inputs.capex_pct_revenue <= 0.04

    def test_ebitda_margin_matches_history(self):
        """AAPL EBITDA margin ~ 32-34%."""
        assert 0.30 <= self.inputs.ebitda_margin <= 0.36

    def test_beta_from_provider(self):
        assert self.inputs.beta == pytest.approx(1.25, abs=0.01)

    def test_cost_of_debt_derived_from_interest_expense(self):
        # 3.75B / 106B ≈ 3.54%
        assert self.inputs.cost_of_debt == pytest.approx(0.0354, abs=0.001)

    def test_net_debt_signed_correctly(self):
        # AAPL has net cash position (debt 106B − cash 65B = +41B net debt)
        assert self.inputs.net_debt == pytest.approx(41_458_000_000)

    def test_growth_schedule_length_matches_projection_years(self):
        sched = self.inputs.revenue_growth_rates
        assert len(sched) == 5
        # AAPL fixture has CAGR=2.2% < terminal 2.5% → flat schedule. Real
        # AAPL 5y CAGR is closer to 8% so this is a fixture-specific edge.
        # Either way, schedule must be monotone non-increasing.
        for a, b in zip(sched, sched[1:]):
            assert a >= b

    def test_provenance_covers_all_critical_fields(self):
        """The UI relies on these keys — every assumption shown must have a source."""
        critical = {
            "revenue_base",
            "revenue_growth_rates",
            "ebitda_margin",
            "capex_pct_revenue",
            "da_pct_revenue",
            "nwc_pct_revenue",
            "tax_rate",
            "beta",
            "cost_of_debt",
            "debt_ratio",
            "risk_free_rate",
            "equity_risk_premium",
            "terminal_growth_rate",
            "shares_outstanding",
            "net_debt",
        }
        assert critical <= set(self.inputs.assumption_provenance)

    def test_provenance_messages_are_chinese(self):
        """Provenance text should be human-readable Chinese for retail users."""
        for key, msg in self.inputs.assumption_provenance.items():
            # At least one CJK char in each message
            assert any("一" <= ch <= "鿿" for ch in msg), f"{key}: {msg}"

    def test_nwc_pct_revenue_positive_when_working_capital_drains_cash(self):
        """FMP changeInWorkingCapital carries the cash-flow sign (negative = NWC
        grew = cash consumed). The seed must flip it to a POSITIVE nwc_pct_revenue
        ("cash drag"), the same convention as capex (stored absolute), so the FCF
        formula EBIT(1-t)+D&A-CapEx-ΔNWC reduces FCF when working capital grows.

        Regression for the sign-inversion bug: passing the raw provider value made
        `- rev * nwc_pct_revenue` *add* cash, inflating FCF for every cash-consuming
        company (verified live: AAPL FY25 FCF came out ~+37B too high)."""
        hist = self.historical.model_copy(
            update={"change_in_working_capital": [-3e9, -4e9, -3.5e9, -5e9]}
        )
        inputs = seed_dcf_inputs(self.financials, hist)
        assert inputs.nwc_pct_revenue > 0


class TestSeedDcfInputsIndustryFallback:
    """When ticker history is missing, every field should fall through to industry median."""

    @pytest.fixture
    def empty_history(self) -> HistoricalMetrics:
        return HistoricalMetrics(
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

    def test_seeds_run_to_completion_without_history(self, empty_history):
        inputs = seed_dcf_inputs(_aapl_financials(), empty_history)
        assert inputs.da_pct_revenue > 0
        assert inputs.capex_pct_revenue > 0
        assert inputs.ebitda_margin > 0

    def test_provenance_marks_industry_fallback(self, empty_history):
        """When history isn't available, provenance should say "行业中位数"."""
        inputs = seed_dcf_inputs(_aapl_financials(), empty_history)
        assert "行业" in inputs.assumption_provenance["capex_pct_revenue"]
        assert "行业" in inputs.assumption_provenance["da_pct_revenue"]


class TestSeedDcfInputsUnknownIndustry:
    """Total Market fallback when industry doesn't map to any Damodaran row."""

    def test_unknown_industry_still_produces_valid_inputs(self):
        financials = _aapl_financials()
        # Force an industry that won't match anything
        financials = financials.model_copy(
            update={"market": financials.market.model_copy(update={"industry": "UnmappableXYZ"})}
        )
        inputs = seed_dcf_inputs(financials, _aapl_historical())
        # Should still produce a valid DCFInputs — Total Market fallback
        assert inputs.da_pct_revenue > 0
        assert 0.3 <= inputs.beta <= 2.5


class TestDecliningFirmGrowth:
    """Negative revenue CAGR must flow through — not be clamped to a flat 0%.

    The old floor of 0.0 forced every structurally-declining firm to a 0%
    explicit schedule, overstating fair value for exactly the over-valued
    names the SELL/short path relies on (DCF must be able to land below price).
    """

    def test_negative_cagr_not_clamped_to_zero(self):
        fin = _aapl_financials()
        hist = _aapl_historical().model_copy(update={"cagr_revenue": -0.10})
        inputs = seed_dcf_inputs(fin, hist)
        # Base growth reflects the decline, not 0%.
        assert inputs.revenue_growth_rates[0] == pytest.approx(-0.10)
        # base ≤ terminal → held flat across the explicit window.
        assert all(r == pytest.approx(-0.10) for r in inputs.revenue_growth_rates)
        # Provenance must not falsely claim a "衰减" that doesn't happen.
        assert "持平" in inputs.assumption_provenance["revenue_growth_rates"]

    def test_severe_decline_floored_at_minus_20pct(self):
        fin = _aapl_financials()
        hist = _aapl_historical().model_copy(update={"cagr_revenue": -0.50})
        inputs = seed_dcf_inputs(fin, hist)
        assert inputs.revenue_growth_rates[0] == pytest.approx(-0.20)

    def test_high_growth_still_decays_to_terminal(self):
        # Regression: the positive-growth decay path must be unchanged.
        fin = _aapl_financials()
        hist = _aapl_historical().model_copy(update={"cagr_revenue": 0.30})
        inputs = seed_dcf_inputs(fin, hist)
        assert inputs.revenue_growth_rates[0] == pytest.approx(0.30)
        assert inputs.revenue_growth_rates[-1] == pytest.approx(0.025)
        assert "衰减" in inputs.assumption_provenance["revenue_growth_rates"]


# ---------------------------------------------------------------------------
# Effective tax rate (B) — company rate from income_tax_expense vs industry
# ---------------------------------------------------------------------------


class TestEffectiveTaxRate:
    def test_meta_like_rate(self):
        # META: tax 18.715B / pretax (70.587B + 18.715B) = 20.96%
        assert _effective_tax_rate(18_715_000_000, 70_587_000_000) == pytest.approx(
            0.2096, abs=1e-3
        )

    def test_none_when_tax_missing(self):
        assert _effective_tax_rate(None, 70e9) is None

    def test_none_when_net_income_missing(self):
        assert _effective_tax_rate(15e9, None) is None

    def test_none_on_loss_year_nonpositive_pretax(self):
        # Loss-maker with a tax benefit → pretax = NI + tax can be ≤ 0
        assert _effective_tax_rate(-5e9, -10e9) is None

    def test_none_on_implausible_high_rate(self):
        # > 45% signals a one-off item, not the run-rate → fall back to industry
        assert _effective_tax_rate(60e9, 40e9) is None

    def test_seed_uses_company_rate_over_industry(self):
        # A profitable internet-mapped company must NOT inherit the distorted
        # "Software (Internet)" industry aggregate (40%) when its own filing
        # gives a real effective rate.
        fin = _aapl_financials()
        fin.income.income_tax_expense = 18_715_000_000
        fin.income.net_income = 70_587_000_000
        inputs = seed_dcf_inputs(fin, _aapl_historical())
        assert inputs.tax_rate == pytest.approx(0.2096, abs=1e-3)
        assert "最新财报有效税率" in inputs.assumption_provenance["tax_rate"]


# ---------------------------------------------------------------------------
# CapEx consistency cap (C) — industry fallback can't exceed EBITDA margin
# ---------------------------------------------------------------------------


class TestCapexConsistencyCap:
    def test_industry_capex_capped_at_ebitda_margin(self):
        # No company CapEx history → falls back to industry. With a company
        # EBITDA margin (50%) below a pathological industry CapEx (e.g. Software
        # (Internet) 31.8%... here forced higher), CapEx is capped at the EBITDA
        # margin so FCF can't be structurally negative.
        fin = _aapl_financials()
        # Empty capex history forces the industry fallback; keep a known EBITDA margin.
        hist = _aapl_historical().model_copy(
            update={"capital_expenditure": [], "ebitda_margin": [0.50, 0.50, 0.50, 0.50]}
        )
        inputs = seed_dcf_inputs(fin, hist)
        # Cap fires only if industry capex > ebitda_margin; assert the invariant holds.
        assert inputs.capex_pct_revenue <= inputs.ebitda_margin + 1e-9

    def test_company_capex_never_capped(self):
        # When the company's own CapEx history is present it is used verbatim —
        # the consistency guard must not touch it even if low.
        inputs = seed_dcf_inputs(_aapl_financials(), _aapl_historical())
        assert 0.02 <= inputs.capex_pct_revenue <= 0.04
        assert "过去 3 年 CapEx" in inputs.assumption_provenance["capex_pct_revenue"]
