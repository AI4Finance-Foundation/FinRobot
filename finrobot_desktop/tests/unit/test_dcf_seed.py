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

import math
from datetime import datetime, timezone

import pytest

from finrobot.engine.compute.operators.dcf import calculate_dcf, solve_for_implied_growth
from finrobot.engine.compute.operators.dcf_seed import (
    COST_OF_DEBT_CAP,
    COST_OF_DEBT_FLOOR,
    _cost_of_debt,
    _decay_growth_schedule,
    _effective_tax_rate,
    _median_ratio,
    _terminal_nwc_pct,
    _median_recent,
    _weighted_ratio,
    seed_dcf_inputs,
)
from finrobot.engine.compute.operators.monte_carlo import run_monte_carlo
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
    def test_returns_median_and_count_of_pairs(self):
        # 10/100=0.10, 20/100=0.20, 30/100=0.30 → median 0.20 over 3 samples
        assert _median_ratio([10, 20, 30], [100, 100, 100]) == (pytest.approx(0.20), 3)

    def test_returns_none_when_too_few_samples(self):
        assert _median_ratio([10], [100]) is None

    def test_returns_none_when_denominator_zero(self):
        assert _median_ratio([10, 20], [0, 0]) is None

    def test_returns_none_when_all_numerator_zero(self):
        """zero-filled cashflow row should fall through to industry default."""
        assert _median_ratio([0, 0, 0], [100, 100, 100]) is None

    def test_uses_most_recent_window(self):
        """BUG-026: window (3y) slices the recent years independently of the
        min_samples threshold. A 5y history keeps only the newest 3 — the two
        oldest outliers must not pull the median around."""
        # First two are weird outliers; last three (30, 30, 30) are the window.
        result = _median_ratio([1000, -50, 30, 30, 30], [100, 100, 100, 100, 100])
        assert result == (pytest.approx(0.30), 3)

    def test_window_3_picks_newest_three_not_two(self):
        """Regression for BUG-026: the median must reflect the newest 3 years,
        not the last 2. With 5 ascending samples the 2y median (0.40,0.50→0.45)
        and the 3y median (0.30,0.40,0.50→0.40) differ — assert it's the 3y one."""
        result = _median_ratio([10, 20, 30, 40, 50], [100, 100, 100, 100, 100])
        assert result == (pytest.approx(0.40), 3)

    def test_short_history_reports_real_count_not_window(self):
        """A 2y history sliced [-3:] still yields only 2 samples — the returned
        count is 2, never the 3y window, so provenance can't overstate the data."""
        result = _median_ratio([20, 40], [100, 100])
        assert result == (pytest.approx(0.30), 2)


class TestMedianRecent:
    def test_returns_median_and_count_of_window(self):
        # Newest 3 of [0.20,0.30,0.32,0.33] = 0.30,0.32,0.33 → median 0.32, count 3
        assert _median_recent([0.20, 0.30, 0.32, 0.33]) == (pytest.approx(0.32), 3)

    def test_skips_zero_values(self):
        # 0.0 is skipped, only 0.30 survives → median 0.30, count 1
        assert _median_recent([0.0, 0.30]) == (pytest.approx(0.30), 1)

    def test_returns_none_when_all_zero(self):
        assert _median_recent([0.0, 0.0, 0.0]) is None

    def test_short_history_reports_real_count(self):
        """2y history sliced [-3:] yields 2 samples — count is the real 2."""
        assert _median_recent([0.30, 0.34]) == (pytest.approx(0.32), 2)


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


class TestCostOfDebtProvenanceClamp:
    """BUG-023: a clamped cost of debt must be marked in provenance, never
    presented as if it were the raw interest/debt ratio."""

    def test_clamp_below_floor_marked(self):
        fin = _aapl_financials()
        # Tiny interest on a large debt balance → raw rate ≪ 2% floor.
        fin = fin.model_copy(
            update={"income": fin.income.model_copy(update={"interest_expense": 1.0})}
        )
        inputs = seed_dcf_inputs(fin, _aapl_historical())
        assert inputs.cost_of_debt == COST_OF_DEBT_FLOOR
        assert "夹至下限" in inputs.assumption_provenance["cost_of_debt"]

    def test_clamp_above_cap_marked(self):
        fin = _aapl_financials()
        # Huge interest → raw rate ≫ 20% cap.
        fin = fin.model_copy(
            update={"income": fin.income.model_copy(update={"interest_expense": 50e9})}
        )
        inputs = seed_dcf_inputs(fin, _aapl_historical())
        assert inputs.cost_of_debt == COST_OF_DEBT_CAP
        assert "夹至上限" in inputs.assumption_provenance["cost_of_debt"]

    def test_normal_rate_not_marked_as_clamped(self):
        inputs = seed_dcf_inputs(_aapl_financials(), _aapl_historical())
        prov = inputs.assumption_provenance["cost_of_debt"]
        assert "夹至" not in prov
        assert "最新利息支出 / 总债务" in prov


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
        # Provider raw beta 1.25, Blume-adjusted: 2/3·1.25 + 1/3·1.0 = 1.1667.
        assert self.inputs.beta == pytest.approx(1.1667, abs=0.01)

    def test_cost_of_debt_derived_from_interest_expense(self):
        # 3.75B / 106B ≈ 3.54%
        assert self.inputs.cost_of_debt == pytest.approx(0.0354, abs=0.001)

    def test_net_debt_signed_correctly(self):
        # AAPL has net cash position (debt 106B − cash 65B = +41B net debt)
        assert self.inputs.net_debt == pytest.approx(41_458_000_000)

    def test_growth_schedule_length_matches_projection_years(self):
        sched = self.inputs.revenue_growth_rates
        assert len(sched) == 10
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

    def test_debt_ratio_capped_at_80_percent(self):
        """Market leverage is capped at 80% for WACC weighting. Above that the thin
        equity sliver lets a low after-tax cost of debt drag WACC below terminal
        growth, making the Gordon perpetuity undefined. Regression for the crash on
        very low-WACC, high-leverage profiles (utilities / REITs)."""
        levered = self.financials.model_copy(
            update={
                "balance": self.financials.balance.model_copy(update={"total_debt": 900e9}),
                "market": self.financials.market.model_copy(update={"market_cap": 100e9}),
            }
        )
        inputs = seed_dcf_inputs(levered, self.historical)
        # raw debt_ratio = 900 / (900 + 100) = 0.90, capped to 0.80
        assert inputs.debt_ratio == pytest.approx(0.80)


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

    def test_negative_company_ebitda_margin_rejection_is_disclosed(self):
        hist = _aapl_historical().model_copy(update={"ebitda_margin": [-0.30, -0.20, -0.10, -0.05]})
        inputs = seed_dcf_inputs(_aapl_financials(), hist)
        provenance = inputs.assumption_provenance["ebitda_margin"]

        assert inputs.ebitda_margin > 0
        assert "行业中位数" in provenance
        assert "-10.0%" in provenance
        assert "为非正" in provenance


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
        assert inputs.revenue_growth_rates[-1] == pytest.approx(0.030)
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


# ---------------------------------------------------------------------------
# BUG-026 — historical-median window is 3 years and provenance reports the
# REAL sample count (never a hardcoded "3")
# ---------------------------------------------------------------------------


def _five_year_historical() -> HistoricalMetrics:
    """5-year history (oldest first) where the newest-3 median differs from the
    newest-2 median, so a window regression to 2y would be detectable."""
    revenue = [100e9, 100e9, 100e9, 100e9, 100e9]
    # capex/rev climbs each year: 1%,2%,3%,4%,5%. Newest-3 median = 4%; a 2y
    # window would give 4.5% — the values diverge, pinning the window at 3.
    capex = [1e9, 2e9, 3e9, 4e9, 5e9]
    # D&A flat at 3% so da_pct is stable regardless of window.
    da = [3e9, 3e9, 3e9, 3e9, 3e9]
    # EBITDA margin climbs: newest-3 median = 33%; newest-2 would be 33.5%.
    ebitda_margin = [0.30, 0.31, 0.32, 0.33, 0.34]
    return HistoricalMetrics(
        years=[2020, 2021, 2022, 2023, 2024],
        revenue=revenue,
        revenue_growth_yoy=[None, 0.0, 0.0, 0.0, 0.0],
        cogs=[60e9] * 5,
        gross_profit=[40e9] * 5,
        gross_margin=[0.40] * 5,
        sga=[10e9] * 5,
        sga_ratio=[0.10] * 5,
        ebitda=[m * 100e9 for m in ebitda_margin],
        ebitda_margin=ebitda_margin,
        operating_income=[25e9] * 5,
        operating_margin=[0.25] * 5,
        net_income=[20e9] * 5,
        eps=[2.0] * 5,
        pe_ratio=[None, None, None, None, 20.0],
        cagr_revenue=0.0,
        ticker="AAPL",
        operating_cash_flow=[30e9] * 5,
        investing_cash_flow=[-5e9] * 5,
        financing_cash_flow=[-10e9] * 5,
        depreciation_amortization=da,
        capital_expenditure=capex,
        change_in_working_capital=[-1e9, -1e9, -1e9, -1e9, -1e9],
    )


def _two_year_historical() -> HistoricalMetrics:
    """Exactly 2 fiscal years of history — sliced [-3:] still yields only 2
    samples, so provenance must honestly say "过去 2 年", never "过去 3 年"."""
    revenue = [100e9, 100e9]
    capex = [3e9, 5e9]  # 3%, 5% → median 4%, count 2
    da = [3e9, 3e9]
    ebitda_margin = [0.30, 0.34]  # median 0.32, count 2
    return HistoricalMetrics(
        years=[2023, 2024],
        revenue=revenue,
        revenue_growth_yoy=[None, 0.0],
        cogs=[60e9, 60e9],
        gross_profit=[40e9, 40e9],
        gross_margin=[0.40, 0.40],
        sga=[10e9, 10e9],
        sga_ratio=[0.10, 0.10],
        ebitda=[m * 100e9 for m in ebitda_margin],
        ebitda_margin=ebitda_margin,
        operating_income=[25e9, 25e9],
        operating_margin=[0.25, 0.25],
        net_income=[20e9, 20e9],
        eps=[2.0, 2.0],
        pe_ratio=[None, 20.0],
        cagr_revenue=0.0,
        ticker="AAPL",
        operating_cash_flow=[30e9, 30e9],
        investing_cash_flow=[-5e9, -5e9],
        financing_cash_flow=[-10e9, -10e9],
        depreciation_amortization=da,
        capital_expenditure=capex,
        change_in_working_capital=[-1e9, -1e9],
    )


class TestMedianWindowBug026:
    """BUG-026: the seed slices the newest 3 fiscal years for every historical
    median and the provenance string reports the ACTUAL sample count used."""

    def test_five_year_history_uses_newest_three(self):
        inputs = seed_dcf_inputs(_aapl_financials(), _five_year_historical())
        # capex/rev over newest 3 years (3%,4%,5%) → median 4%, NOT the 2y 4.5%.
        assert inputs.capex_pct_revenue == pytest.approx(0.04)
        # ebitda margin over newest 3 (32%,33%,34%) → median 33%, not 2y 33.5%.
        assert inputs.ebitda_margin == pytest.approx(0.33)

    def test_five_year_provenance_says_three_years(self):
        inputs = seed_dcf_inputs(_aapl_financials(), _five_year_historical())
        prov = inputs.assumption_provenance
        assert "过去 3 年 CapEx" in prov["capex_pct_revenue"]
        assert "过去 3 年 D&A" in prov["da_pct_revenue"]
        assert "过去 3 年 EBITDA" in prov["ebitda_margin"]
        assert "过去 3 年 ΔNWC" in prov["nwc_pct_revenue"]

    def test_two_year_history_works_and_provenance_says_two_years(self):
        """Only 2 years of data: median still computed (count 2) and the label
        reports the real "过去 2 年", never a hardcoded 3 (would re-lie)."""
        inputs = seed_dcf_inputs(_aapl_financials(), _two_year_historical())
        assert inputs.capex_pct_revenue == pytest.approx(0.04)  # median(3%,5%)
        assert inputs.ebitda_margin == pytest.approx(0.32)  # median(30%,34%)
        prov = inputs.assumption_provenance
        assert "过去 2 年 CapEx" in prov["capex_pct_revenue"]
        assert "过去 2 年 D&A" in prov["da_pct_revenue"]
        assert "过去 2 年 EBITDA" in prov["ebitda_margin"]
        assert "过去 2 年 ΔNWC" in prov["nwc_pct_revenue"]
        # Must NOT claim 3 years of history it doesn't have.
        assert "过去 3 年" not in prov["capex_pct_revenue"]
        assert "过去 3 年" not in prov["ebitda_margin"]


class TestForwardGrowthSeed:
    """forward_growth (analyst consensus) takes precedence over trailing CAGR.

    AAPL's trailing 5y CAGR is ~3.3% (dragged by the FY22-24 plateau); consensus
    expects a reacceleration. Seeding the explicit window from consensus stops
    the DCF contradicting the pipeline's own forward projection.
    """

    def test_forward_growth_drives_explicit_window_over_trailing(self):
        inputs = seed_dcf_inputs(
            _aapl_financials(), _aapl_historical(), forward_growth=[0.149, 0.084, 0.071]
        )
        sched = inputs.revenue_growth_rates
        assert sched[0] == pytest.approx(0.149)
        assert sched[1] == pytest.approx(0.084)
        assert sched[2] == pytest.approx(0.071)
        # not the ~3% trailing CAGR the old seed would have produced
        assert sched[0] > 0.10

    def test_forward_tail_decays_to_terminal(self):
        inputs = seed_dcf_inputs(
            _aapl_financials(), _aapl_historical(), forward_growth=[0.149, 0.084, 0.071]
        )
        sched = inputs.revenue_growth_rates
        assert len(sched) == 10  # DEFAULT_PROJECTION_YEARS
        assert sched[-1] == pytest.approx(inputs.terminal_growth_rate)
        # monotone-decreasing tail after the explicit consensus years
        tail = sched[2:]
        assert all(a >= b - 1e-9 for a, b in zip(tail, tail[1:]))

    def test_forward_growth_respects_40pct_cap(self):
        inputs = seed_dcf_inputs(
            _aapl_financials(), _aapl_historical(), forward_growth=[0.82, 0.42, 0.20]
        )
        assert inputs.revenue_growth_rates[0] == pytest.approx(0.40)
        assert inputs.revenue_growth_rates[1] == pytest.approx(0.40)

    def test_forward_growth_provenance_is_chinese_and_names_consensus(self):
        inputs = seed_dcf_inputs(
            _aapl_financials(), _aapl_historical(), forward_growth=[0.149, 0.084, 0.071]
        )
        prov = inputs.assumption_provenance["revenue_growth_rates"]
        assert "一致预期" in prov

    def test_empty_forward_growth_falls_back_to_trailing(self):
        base = seed_dcf_inputs(_aapl_financials(), _aapl_historical())
        fb = seed_dcf_inputs(_aapl_financials(), _aapl_historical(), forward_growth=[])
        assert fb.revenue_growth_rates == base.revenue_growth_rates
        assert (
            fb.assumption_provenance["revenue_growth_rates"]
            == (base.assumption_provenance["revenue_growth_rates"])
        )

    def test_nan_in_forward_growth_does_not_poison_schedule(self):
        """A non-finite consensus point must never reach revenue_growth_rates —
        max()/min() pass NaN through, which would make calculate_dcf return an
        implied_price of NaN. The operator filters it at its own boundary."""
        inputs = seed_dcf_inputs(
            _aapl_financials(),
            _aapl_historical(),
            forward_growth=[0.149, float("nan"), 0.071],
        )
        assert all(math.isfinite(g) for g in inputs.revenue_growth_rates)
        # the two finite consensus points survive, in order
        assert inputs.revenue_growth_rates[0] == pytest.approx(0.149)
        assert inputs.revenue_growth_rates[1] == pytest.approx(0.071)

    def test_all_nonfinite_forward_growth_falls_back_to_trailing(self):
        base = seed_dcf_inputs(_aapl_financials(), _aapl_historical())
        fb = seed_dcf_inputs(
            _aapl_financials(),
            _aapl_historical(),
            forward_growth=[float("nan"), float("inf")],
        )
        assert fb.revenue_growth_rates == base.revenue_growth_rates
        assert "一致预期" not in fb.assumption_provenance["revenue_growth_rates"]

    def test_provenance_fy_count_never_exceeds_projection_window(self):
        """When consensus is longer than projection_years the tail years are
        dropped — provenance must report the years actually kept (FY1-3 into a
        3y window), never the raw input length (would claim FY1-6)."""
        inputs = seed_dcf_inputs(
            _aapl_financials(),
            _aapl_historical(),
            projection_years=3,
            forward_growth=[0.149, 0.084, 0.071, 0.06, 0.05, 0.04],
        )
        assert len(inputs.revenue_growth_rates) == 3
        prov = inputs.assumption_provenance["revenue_growth_rates"]
        assert "FY1-3" in prov
        assert "FY1-6" not in prov


class TestInputsFetchedAtProvenance:
    """门四溯源半: the seeded DCFInputs must carry WHEN its market/financial
    inputs were fetched, so every surface that prints a DCF (REST /dcf-seed,
    what-if, chat MC, artifact) can show "inputs as of X" without an artifact
    envelope. Stamped from FinancialData.timestamp — the canonical fetch time —
    never from a wall clock (the operator stays pure)."""

    def test_seed_stamps_inputs_fetched_at_from_financials(self) -> None:
        fin = _aapl_financials()
        inputs = seed_dcf_inputs(fin, _aapl_historical())
        assert inputs.inputs_fetched_at == fin.timestamp

    def test_direct_construction_defaults_to_none(self) -> None:
        """User-supplied inputs (REST /dcf body) have no fetch time — the field
        must stay honestly None, never a fabricated now()."""
        from finrobot.engine.models.financial import DCFInputs

        inputs = DCFInputs(
            revenue_base=391e9,
            revenue_growth_rates=[0.05] * 5,
            ebitda_margin=0.33,
            tax_rate=0.16,
            capex_pct_revenue=0.025,
            nwc_pct_revenue=0.005,
            terminal_growth_rate=0.025,
            risk_free_rate=0.043,
            beta=1.25,
            equity_risk_premium=0.046,
            cost_of_debt=0.04,
            debt_ratio=0.03,
            net_debt=41e9,
            shares_outstanding=15.1e9,
            da_pct_revenue=0.03,
        )
        assert inputs.inputs_fetched_at is None


class TestTerminalNwcPct:
    """Marginal NWC ratio median(ΔNWC_build/Δrevenue) × terminal growth — the
    steady-state ΔNWC drag. FMP changeInWorkingCapital carries the cash-flow
    sign (negative = NWC grew = cash consumed), so build = −value."""

    def test_growth_years_marginal_ratio_scaled_by_tg(self):
        # i=1: build=1, Δrev=10 → 0.10; i=2: build=2, Δrev=11 → 0.1818
        # median = 0.1409 → × 3% = 0.42%
        result = _terminal_nwc_pct([0.0, -1.0, -2.0], [100.0, 110.0, 121.0], 0.03)
        assert result is not None
        marginal, terminal = result
        assert abs(marginal - 0.14091) < 1e-4
        assert abs(terminal - 0.0042273) < 1e-6

    def test_declining_revenue_years_skipped_and_all_declining_returns_none(self):
        # Δrev ≤ 0 everywhere → no usable marginal ratio → honest None
        assert _terminal_nwc_pct([0.0, -1.0, -2.0], [121.0, 110.0, 100.0], 0.03) is None

    def test_nan_rows_filtered(self):
        result = _terminal_nwc_pct([0.0, float("nan"), -2.0], [100.0, 110.0, 121.0], 0.03)
        assert result is not None
        marginal, _ = result
        assert abs(marginal - (2.0 / 11.0)) < 1e-9

    def test_zero_cwc_treated_as_missing_row(self):
        # cwc == 0 follows the _median_ratio convention: row absent from the
        # cashflow statement, not a genuine zero build.
        assert _terminal_nwc_pct([0.0, 0.0, 0.0], [100.0, 110.0, 121.0], 0.03) is None

    def test_noise_clamped_to_marginal_band(self):
        # One-off settlement: build 50 on Δrev 10 → ratio 5.0, clamped to 0.6
        # → terminal = 0.6 × 3% = 1.8%
        result = _terminal_nwc_pct([0.0, -50.0], [100.0, 110.0], 0.03)
        assert result is not None
        marginal, terminal = result
        assert marginal == 0.60
        assert abs(terminal - 0.018) < 1e-12

    def test_cash_source_negative_ratio_clamped_symmetrically(self):
        # Positive cwc = NWC released cash (payables float). Extreme release
        # clamps at −0.6 → terminal −1.8%: the RIVN perpetual-subsidy ceiling.
        result = _terminal_nwc_pct([0.0, 50.0], [100.0, 110.0], 0.03)
        assert result is not None
        marginal, terminal = result
        assert marginal == -0.60
        assert abs(terminal - (-0.018)) < 1e-12


class TestSeedTerminalNwc:
    def test_seed_populates_terminal_nwc_with_provenance(self):
        """AAPL fixture: growth years are FY22 (Δrev 28.5B, build −1.2B) and
        FY24 (Δrev 7.75B, build −1.9B) — FY23 revenue declined and is skipped.
        median(−0.0421, −0.2452) = −0.1436 → × tg 3% ≈ −0.43%."""
        inputs = seed_dcf_inputs(_aapl_financials(), _aapl_historical())
        assert inputs.terminal_nwc_pct_revenue is not None
        assert abs(inputs.terminal_nwc_pct_revenue - (-0.0043097)) < 1e-4
        prov = inputs.assumption_provenance["terminal_nwc_pct_revenue"]
        assert "边际 NWC 比率" in prov

    def test_seed_falls_back_to_none_without_growth_years(self):
        hist = _aapl_historical()
        hist.revenue = [391e9, 383e9, 380e9, 370e9]  # monotonically declining
        inputs = seed_dcf_inputs(_aapl_financials(), hist)
        assert inputs.terminal_nwc_pct_revenue is None
        prov = inputs.assumption_provenance["terminal_nwc_pct_revenue"]
        assert "沿用" in prov


# ---------------------------------------------------------------------------
# Cyclical through-cycle normalization (改动点 2/3) — MU-like memory fixture.
#
# A commodity-cyclical's EBITDA margin / CapEx% / D&A% must be taken across the
# FULL peak→trough→recovery window, not the trailing 3y (which for memory is
# whichever phase the cycle is in NOW). The earnings base differs from the
# non-cyclical path ONLY when cyclical=True; cyclical=False must be逐位 identical
# to the unchanged trailing-3y path (KO 不许崩). Anchored to the SEC-verified MU
# op-margin cycle (FY2017→FY2025): peak 49.3% FY2018, trough −37.0% FY2023,
# recovery FY2024/25 (scripts/_cyclical_normalization_validation.py).
# ---------------------------------------------------------------------------


def _mu_financials() -> FinancialData:
    """MU-like snapshot: current TTM revenue ~$58B (AI super-cycle run-rate, NOT
    the trough FY), generic "Semiconductors" tag (the seed path's ticker anchor
    is what makes it cyclical — the tag alone can't separate MU from NVDA)."""
    return FinancialData(
        ticker="MU",
        company_name="Micron Technology, Inc.",
        timestamp=datetime.now(tz=timezone.utc),
        income=IncomeStatement(
            revenue=58_120_000_000,
            ebitda=29_000_000_000,
            net_income=8_539_000_000,
            gross_margin=0.40,
            operating_margin=0.26,
            depreciation_amortization=8_352_000_000,
            interest_expense=500_000_000,
            income_tax_expense=900_000_000,
        ),
        balance=BalanceSheet(
            total_debt=13_000_000_000,
            total_cash=9_600_000_000,
        ),
        market=MarketData(
            market_cap=1_070_000_000_000,
            shares_outstanding=1_127_734_051,
            current_price=949.88,
            pe_ratio=11.0,
            industry="Semiconductors",
            sector="Technology",
            beta=1.30,
        ),
        valuation=ValuationMetrics(),
    )


def _mu_cyclical_historical() -> HistoricalMetrics:
    """9-year MU history (FY2017→FY2025, oldest first), SEC-anchored op margins.

    op_margin: 28.9, 49.3(peak), 31.5, 14.0, 22.7, 31.5, −37.0(trough), 5.2, 26.1.
    EBITDA margin = op_margin + D&A% per year. The trailing-3y window (FY23/24/25:
    −37/5.2/26.1 op → low EBITDA margins) differs sharply from the full-cycle
    median, so cyclical=True vs False is detectable on this fixture.
    """
    revenue = [
        20_322e6,
        30_391e6,
        23_406e6,
        21_435e6,
        27_705e6,
        30_758e6,
        15_540e6,
        25_111e6,
        37_378e6,
    ]
    op_income = [
        5_868e6,
        14_994e6,
        7_376e6,
        3_003e6,
        6_283e6,
        9_702e6,
        -5_745e6,
        1_304e6,
        9_770e6,
    ]
    da = [
        3_861e6,
        4_759e6,
        5_424e6,
        5_650e6,
        6_214e6,
        7_116e6,
        7_756e6,
        7_780e6,
        8_352e6,
    ]
    capex = [
        4_734e6,
        8_879e6,
        9_780e6,
        8_223e6,
        10_030e6,
        12_067e6,
        7_676e6,
        8_386e6,
        15_857e6,
    ]
    # EBITDA = operating income + D&A; margin = EBITDA / revenue.
    ebitda = [oi + d for oi, d in zip(op_income, da)]
    ebitda_margin = [e / r for e, r in zip(ebitda, revenue)]
    op_margin = [oi / r for oi, r in zip(op_income, revenue)]
    years = [2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]
    return HistoricalMetrics(
        years=years,
        revenue=revenue,
        revenue_growth_yoy=[None] + [None] * 8,
        cogs=[r * 0.7 for r in revenue],
        gross_profit=[r * 0.3 for r in revenue],
        gross_margin=[0.3] * 9,
        sga=[r * 0.05 for r in revenue],
        sga_ratio=[0.05] * 9,
        ebitda=ebitda,
        ebitda_margin=ebitda_margin,
        operating_income=op_income,
        operating_margin=op_margin,
        net_income=op_income,  # proxy; not read by the earnings-base path
        eps=[1.0] * 9,
        pe_ratio=[None] * 8 + [11.0],
        cagr_revenue=0.08,
        ticker="MU",
        operating_cash_flow=[r * 0.3 for r in revenue],
        investing_cash_flow=[-c for c in capex],
        financing_cash_flow=[0.0] * 9,
        depreciation_amortization=da,
        capital_expenditure=capex,
        change_in_working_capital=[-500e6] * 9,
    )


class TestWeightedRatio:
    """Revenue-weighted Σnum/Σden — the cyclical D&A% normalizer."""

    def test_weights_by_denominator_not_per_year_mean(self):
        # Weighted = Σnum/Σden = (10+30)/(100+300) = 40/400 = 0.10, vs the per-year
        # ratio mean (0.10, 0.10 → 0.10 by construction). Use a big-denominator,
        # low-ratio year against a small-denominator, high-ratio year to separate:
        # ratios 1% and 50%; weighted = (10+50)/(1000+100) = 60/1100 ≈ 5.45%, far
        # below the per-year mean (25.5%) — the large year dominates.
        result = _weighted_ratio([10, 50], [1000, 100], window=12)
        assert result is not None
        ratio, n = result
        assert ratio == pytest.approx(60 / 1100)
        assert n == 2

    def test_downweights_trough_spiked_ratio(self):
        # Trough year: D&A 50 on collapsed revenue 100 → 50% ratio; two normal
        # years: 24 on 1000 → 2.4%. Weighted Σ(24+24+50)/Σ(1000+1000+100) =
        # 98/2100 ≈ 4.67%, far below the 50% trough spike a naive max would see.
        result = _weighted_ratio([24, 24, 50], [1000, 1000, 100], window=12)
        assert result is not None
        ratio, n = result
        assert ratio == pytest.approx(98 / 2100)
        assert n == 3

    def test_skips_zero_and_nan_rows(self):
        # 0 (missing-row convention) and NaN are dropped; the two real rows remain
        # → Σ(20+40)/Σ(100+100) = 0.30 over 2 usable pairs.
        result = _weighted_ratio([0, float("nan"), 20, 40], [100, 100, 100, 100], window=12)
        assert result == (pytest.approx(0.30), 2)

    def test_none_when_too_few_samples(self):
        assert _weighted_ratio([10], [100], window=12) is None


class TestCyclicalNormalization:
    def test_cyclical_uses_full_cycle_window_not_trailing_3y(self):
        """The cyclical EBITDA margin must straddle the whole cycle, so it differs
        from the trailing-3y (recovery-phase) median this fixture would otherwise
        give. Full-cycle median EBITDA margin sits well above the depressed
        trailing-3y (FY23/24/25) median — the normalization is doing real work."""
        cyc = seed_dcf_inputs(_mu_financials(), _mu_cyclical_historical(), cyclical=True)
        non = seed_dcf_inputs(_mu_financials(), _mu_cyclical_historical(), cyclical=False)
        # Trailing-3y EBITDA margins (FY23/24/25) on the fixture: low/negative-op
        # years pull the 3y median below the full-cycle median.
        assert cyc.ebitda_margin != pytest.approx(non.ebitda_margin)
        # Full-cycle median EBITDA margin is the median of all 9 years.
        full = sorted(m for m in _mu_cyclical_historical().ebitda_margin)
        expected_full_median = full[len(full) // 2]
        assert cyc.ebitda_margin == pytest.approx(expected_full_median, abs=0.005)

    def test_cyclical_da_is_revenue_weighted_through_cycle(self):
        """D&A% uses Σ D&A / Σ revenue across the cycle (down-weights the trough's
        spiked D&A/revenue), not the trailing-3y per-year median."""
        cyc = seed_dcf_inputs(_mu_financials(), _mu_cyclical_historical(), cyclical=True)
        hist = _mu_cyclical_historical()
        expected = sum(hist.depreciation_amortization) / sum(hist.revenue)
        # da_pct clamped to [0.005, 0.40]; expected ~22% is inside.
        assert cyc.da_pct_revenue == pytest.approx(expected, abs=0.005)

    def test_cyclical_capex_converges_to_maintenance_anchor(self):
        """MU's through-cycle CapEx (~38%) is growth-capex inflated (vs D&A ~24%);
        a cyclical normalized to through-cycle earnings must reinvest at the
        maintenance level min(D&A, CapEx) — the same anchor terminal value uses —
        so the explicit-window CapEx is pulled down to D&A%, not the full 38%."""
        cyc = seed_dcf_inputs(_mu_financials(), _mu_cyclical_historical(), cyclical=True)
        # CapEx is capped at D&A (maintenance), so they coincide for MU.
        assert cyc.capex_pct_revenue == pytest.approx(cyc.da_pct_revenue, abs=1e-9)
        # And it is materially below the raw through-cycle CapEx median (~38%).
        hist = _mu_cyclical_historical()
        raw_capex_pairs = sorted(c / r for c, r in zip(hist.capital_expenditure, hist.revenue))
        raw_capex_median = raw_capex_pairs[len(raw_capex_pairs) // 2]
        assert cyc.capex_pct_revenue < raw_capex_median - 0.05
        assert "维护性再投资" in cyc.assumption_provenance["capex_pct_revenue"]

    def test_cyclical_capex_anchor_is_noop_when_capex_below_da(self):
        """A low-capex cyclical (WDC/STX: CapEx ≈ D&A already) is NOT raised — the
        maintenance anchor only ever LOWERS capex, never invents reinvestment."""
        hist = _mu_cyclical_historical()
        # Force capex well below D&A so min(D&A, CapEx) = CapEx (the WDC/STX shape).
        low_capex = [d * 0.3 for d in hist.depreciation_amortization]
        low = hist.model_copy(update={"capital_expenditure": low_capex})
        cyc = seed_dcf_inputs(_mu_financials(), low, cyclical=True)
        expected_capex_median = sorted(c / r for c, r in zip(low_capex, hist.revenue))[
            len(low_capex) // 2
        ]
        # Unchanged from the raw through-cycle CapEx median (no maintenance cap).
        assert cyc.capex_pct_revenue == pytest.approx(expected_capex_median, abs=0.005)
        assert "维护性再投资" not in cyc.assumption_provenance["capex_pct_revenue"]

    def test_cyclical_provenance_exposes_cycle_shape(self):
        """Provenance must carry the peak/trough/median the normalized base
        straddles (the analyst 下钻 传感器) + the Damodaran口径 marker."""
        cyc = seed_dcf_inputs(_mu_financials(), _mu_cyclical_historical(), cyclical=True)
        prov = cyc.assumption_provenance
        assert "cyclical_normalization" in prov
        assert "through-cycle" in prov["ebitda_margin"]
        assert "峰" in prov["ebitda_margin"] and "谷" in prov["ebitda_margin"]
        # Damodaran normalization marker, not the trailing-3y wording.
        assert "非近 3 年中位" in prov["ebitda_margin"]

    def test_full_cycle_claim_names_real_peak_trough_fy(self):
        """The 9y MU fixture genuinely spans a full cycle, so the provenance may
        claim '罩完整周期' — and must name the REAL peak (FY2018) and trough
        (FY2023) fiscal years, not an unconditional template phrase."""
        cyc = seed_dcf_inputs(_mu_financials(), _mu_cyclical_historical(), cyclical=True)
        note = cyc.assumption_provenance["cyclical_normalization"]
        assert "罩完整" in note
        assert "FY2018" in note  # peak
        assert "FY2023" in note  # trough
        # The disclosed window count = the 9 usable years actually in-window.
        assert "9 年" in note

    def test_truncated_window_does_not_claim_full_cycle(self):
        """A short-history cyclical (only the recovery phase, <6y) must NOT claim a
        full cycle — that was the overclaim. The provenance instead discloses the
        truncated window honestly. Mirrors a name where SEC deep history is
        unavailable and only the FMP/yfinance ~4y window survives."""
        hist = _mu_cyclical_historical()
        # Keep only the last 4 fiscal years (FY2022-25) — no FY2018 peak in-window.
        trunc = hist.model_copy(
            update={
                "years": hist.years[-4:],
                "revenue": hist.revenue[-4:],
                "operating_income": hist.operating_income[-4:],
                "operating_margin": hist.operating_margin[-4:],
                "ebitda": hist.ebitda[-4:],
                "ebitda_margin": hist.ebitda_margin[-4:],
                "depreciation_amortization": hist.depreciation_amortization[-4:],
                "capital_expenditure": hist.capital_expenditure[-4:],
            }
        )
        cyc = seed_dcf_inputs(_mu_financials(), trunc, cyclical=True)
        note = cyc.assumption_provenance["cyclical_normalization"]
        # The depressed-recovery 4y window DOES carry a real swing (FY2023 trough →
        # FY2025 recovery), but is too SHALLOW (<6y) to be a full cycle.
        assert "罩完整 峰→谷→恢复 周期" not in note
        assert "未必罩完整周期" in note or "可能未罩完整周期" in note
        # Still names what it actually has.
        assert "FY20" in note

    def test_non_cyclical_path_is_bit_identical_to_default(self):
        """KO 不许崩: a non-cyclical seeded with cyclical=False must be byte-for-
        byte identical to the default call (no cyclical kwarg). The cyclical
        branch must not perturb the established trailing-3y path at all."""
        # Same instances on both calls — _aapl_financials() stamps a fresh now()
        # timestamp each call, so reuse one snapshot to isolate the cyclical flag.
        fin = _aapl_financials()
        hist = _aapl_historical()
        default = seed_dcf_inputs(fin, hist)
        explicit_false = seed_dcf_inputs(fin, hist, cyclical=False)
        assert explicit_false.model_dump() == default.model_dump()

    def test_non_cyclical_has_no_cycle_provenance(self):
        non = seed_dcf_inputs(_aapl_financials(), _aapl_historical(), cyclical=False)
        assert "cyclical_normalization" not in non.assumption_provenance
        assert "through-cycle" not in non.assumption_provenance["ebitda_margin"]

    def test_memory_storage_arm_named_in_provenance(self):
        """MU rides the generic "Semiconductors" tag (ticker anchor / keyword arm),
        so its provenance names memory/storage — the substring the thesis prompt's
        supercycle reframe gates on."""
        cyc = seed_dcf_inputs(_mu_financials(), _mu_cyclical_historical(), cyclical=True)
        note = cyc.assumption_provenance["cyclical_normalization"]
        assert "memory/storage" in note
        assert "行业白名单" not in note

    def test_industry_arm_does_not_claim_memory_storage(self):
        """An auto OEM (TSLA-like) qualifies via the UNCONDITIONAL industry
        whitelist — its provenance must name that arm, NOT fabricate a
        "memory/storage 命中" (live TSLA artifact 2fadab carried exactly that
        fabricated claim). The thesis prompt's memory-supercycle reframe keys on
        the substring, so the wrong arm wording also mis-frames the narrative."""
        fin = _mu_financials().model_copy(deep=True)
        fin.market.industry = "Auto Manufacturers"
        cyc = seed_dcf_inputs(fin, _mu_cyclical_historical(), cyclical=True)
        note = cyc.assumption_provenance["cyclical_normalization"]
        assert "memory/storage" not in note
        assert "行业白名单" in note
        # Still a through-cycle normalization — only the arm label differs.
        assert "through-cycle" in note


class TestCyclicalSeedEquivalence:
    """改动点 3: the five seed consumers (MC / sensitivity / reverse / REST /
    report) all consume the SAME DCFInputs —改 the seed earnings base and they
    inherit the through-cycle口径. Pin that the cyclical seed round-trips through
    calculate_dcf, MC, and the reverse solver exactly as the non-cyclical one."""

    def test_mc_collapses_to_dcf_on_cyclical_inputs(self):
        """Perturbation→0: the MC distribution for cyclical-seeded inputs must
        collapse onto calculate_dcf's implied price — the same equivalence gate
        the non-cyclical path passes, proving MC inherits the normalized base
        with no separate earnings recomputation."""
        inputs = seed_dcf_inputs(_mu_financials(), _mu_cyclical_historical(), cyclical=True)
        deterministic = calculate_dcf(inputs).implied_price
        result = run_monte_carlo(
            inputs,
            current_price=949.88,
            n_simulations=200,
            revenue_growth_std=0.0,
            ebitda_margin_std=0.0,
            wacc_std=0.0,
            terminal_growth_std=0.0,
            seed=42,
        )
        expected = round(deterministic, 2)
        assert result.percentiles["50"] == pytest.approx(expected, abs=0.01)
        assert result.mean == pytest.approx(expected, abs=0.01)
        assert result.std == pytest.approx(0.0, abs=0.01)

    def test_reverse_growth_round_trips_on_cyclical_inputs(self):
        """solve_for_implied_growth(inputs, forward_price) recovers the seed's own
        explicit growth — the reverse solver speaks the same forward map on the
        cyclical-seeded inputs (the normalization changed only the earnings base,
        not the growth schedule contract)."""
        inputs = seed_dcf_inputs(_mu_financials(), _mu_cyclical_historical(), cyclical=True)
        forward = calculate_dcf(inputs, wacc_override=0.10)
        reverse = solve_for_implied_growth(
            inputs,
            target_price=forward.implied_price,
            horizon_years=len(inputs.revenue_growth_rates),
            wacc_override=0.10,
        )
        assert reverse["implied_growth"] is not None
        assert abs(reverse["computed_price"] - forward.implied_price) < 0.10
