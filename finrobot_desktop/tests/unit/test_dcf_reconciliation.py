"""Batch 1b/1d — the model-vs-current reconciliation inputs.

Covers three add-only fields that feed the report's assumptions reconciliation
table and the ±2pp margin swing note:

  * ``operators.dcf.margin_swing``            — the ±2pp EBITDA-margin swing
  * ``operators.dcf_seed.dcf_current_actuals`` — latest-year actuals per driver
  * ``DCFInputs.nwc_clamped``                  — the ΔNWC clamp ⚠ signal

``calculate_dcf`` is the oracle for the swing prices: its own arithmetic is
validated against a hand calculation in test_dcf.py, so here we only verify the
wrapper applies the RIGHT ±2pp shift and degrades gracefully — never the DCF
formula itself (which would be self-derivation).
"""

import math
from datetime import datetime, timezone

from finrobot.engine.models.financial import (
    BalanceSheet,
    DCFInputs,
    FinancialData,
    HistoricalMetrics,
    IncomeStatement,
    MarketData,
)
from finrobot.engine.compute.operators.dcf import calculate_dcf, margin_swing
from finrobot.engine.compute.operators.dcf_seed import dcf_current_actuals, seed_dcf_inputs


def _make_inputs(**overrides) -> DCFInputs:
    defaults = dict(
        revenue_base=100_000_000_000,
        revenue_growth_rates=[0.05] * 5,
        ebitda_margin=0.35,
        capex_pct_revenue=0.05,
        nwc_pct_revenue=0.02,
        da_pct_revenue=0.03,
        tax_rate=0.21,
        risk_free_rate=0.04,
        beta=1.2,
        equity_risk_premium=0.05,
        cost_of_debt=0.04,
        debt_ratio=0.1,
        terminal_growth_rate=0.025,
        shares_outstanding=1_000_000_000,
        net_debt=10_000_000_000,
    )
    defaults.update(overrides)
    return DCFInputs(**defaults)


def _hist(**overrides) -> HistoricalMetrics:
    """Minimal 3-year HistoricalMetrics. Only the fields dcf_current_actuals reads
    (revenue, revenue_growth_yoy, ebitda_margin, capital_expenditure,
    change_in_working_capital) carry meaningful values; the rest are placeholders."""
    years = [2022, 2023, 2024]
    defaults = dict(
        years=years,
        revenue=[80.0, 90.0, 100.0],
        revenue_growth_yoy=[None, 0.125, 0.1111],
        cogs=[None, None, None],
        gross_profit=[None, None, None],
        gross_margin=[None, None, None],
        sga=[0.0, 0.0, 0.0],
        sga_ratio=[None, None, None],
        ebitda=[40.0, 48.0, 55.0],
        ebitda_margin=[0.50, 0.533, 0.55],
        operating_income=[35.0, 42.0, 48.0],
        operating_margin=[None, None, None],
        net_income=[20.0, 24.0, 28.0],
        eps=[2.0, 2.4, 2.8],
        pe_ratio=[None, None, None],
        cagr_revenue=0.118,
        ticker="TEST",
        # FMP change_in_working_capital carries the CASH-FLOW sign (negative = NWC
        # grew = cash absorbed). dcf_current_actuals negates it, matching the seed.
        capital_expenditure=[16.0, 18.0, 30.0],
        change_in_working_capital=[-1.0, -2.0, -1.9],
    )
    defaults.update(overrides)
    return HistoricalMetrics(**defaults)


# ── margin_swing ─────────────────────────────────────────────────────────────


def test_margin_swing_applies_exact_pm_2pp_shift():
    """Both ends equal calculate_dcf run at the base margin ±2pp (wiring)."""
    inputs = _make_inputs(ebitda_margin=0.35)
    swing = margin_swing(inputs)
    assert swing is not None
    low, high = swing
    expected_low = calculate_dcf(inputs.model_copy(update={"ebitda_margin": 0.33})).implied_price
    expected_high = calculate_dcf(inputs.model_copy(update={"ebitda_margin": 0.37})).implied_price
    assert low == expected_low
    assert high == expected_high


def test_margin_swing_monotone_around_base():
    """Implied price rises with margin: low < base < high (ordering contract)."""
    inputs = _make_inputs(ebitda_margin=0.35)
    low, high = margin_swing(inputs)
    base = calculate_dcf(inputs).implied_price
    assert low is not None and high is not None
    assert low < base < high


def test_margin_swing_boundary_near_zero_low_end_out_of_band():
    """Boundary: loss-maker margin near 0 → the −2pp end leaves [0, 1] → None; the
    +2pp end still computes (or degrades to None on a non-positive terminal FCF —
    either way no crash)."""
    inputs = _make_inputs(ebitda_margin=0.01, da_pct_revenue=0.005, capex_pct_revenue=0.005)
    swing = margin_swing(inputs)
    # 0.01 − 0.02 = −0.01 < 0 → out of band → low end must be None.
    assert swing is None or swing[0] is None


def test_margin_swing_boundary_near_high_cap():
    """Boundary: margin near 0.95 → +2pp = 0.97 stays in band and computes; the
    swing is well-ordered."""
    inputs = _make_inputs(ebitda_margin=0.95)
    low, high = margin_swing(inputs)
    assert low is not None and high is not None
    assert high > low
    assert high == calculate_dcf(inputs.model_copy(update={"ebitda_margin": 0.97})).implied_price


def test_margin_swing_negative_net_debt_net_cash_still_computes():
    """Boundary: negative net debt (net cash) is a valid bridge — the swing still
    returns two finite, ordered prices, not None."""
    inputs = _make_inputs(ebitda_margin=0.35, net_debt=-25_000_000_000)
    low, high = margin_swing(inputs)
    assert low is not None and high is not None
    assert low < high


def test_margin_swing_trough_terminal_degrades_to_none_not_raise():
    """Boundary: a margin so thin that the terminal FCF turns non-positive makes
    that end degrade to None (the same BUG-074 refusal calculate_dcf raises) — the
    swing never propagates the ValueError."""
    # capex+nwc drag exceeds the tiny EBIT so the shifted terminal FCF is negative.
    inputs = _make_inputs(
        ebitda_margin=0.04, da_pct_revenue=0.02, capex_pct_revenue=0.35, nwc_pct_revenue=0.05
    )
    swing = margin_swing(inputs)  # must not raise
    # −2pp = 0.02 margin is even thinner → its terminal FCF is non-positive → None.
    assert swing is None or swing[0] is None


def test_margin_swing_zero_denominator_shares_is_structurally_guarded():
    """Boundary: shares_outstanding is gt=0 by schema, so there is no zero-share
    division; a single-share firm still yields a valid, ordered swing."""
    inputs = _make_inputs(ebitda_margin=0.35, shares_outstanding=1.0)
    low, high = margin_swing(inputs)
    assert low is not None and high is not None
    assert low < high


# ── dcf_current_actuals ──────────────────────────────────────────────────────


def test_current_actuals_margin_and_capex_are_ttm_growth_and_nwc_latest_fy():
    """EBITDA margin AND capex = TTM (income.ebitda/revenue 60.5%,
    income.capital_expenditure/revenue 35%) — NOT historical's latest annual
    (55% margin, 30% capex); growth/ΔNWC = latest fiscal year in the seed's
    caliber/sign. ``capex_is_ttm`` reports True so the report's caliber tag can
    say "TTM" truthfully."""
    actuals, capex_is_ttm = dcf_current_actuals(_fd(), _hist())
    assert actuals["ebitda_margin"] == 0.605  # TTM from financial_data, not hist 0.55
    assert math.isclose(actuals["capex_pct_revenue"], 0.35)  # TTM, not hist 30/100=0.30
    assert capex_is_ttm is True
    assert actuals["revenue_growth"] == 0.1111  # latest FY YoY
    # ΔNWC is negated: raw −1.9 / 100 = −0.019 → +0.019 (positive = cash absorbed).
    assert math.isclose(actuals["nwc_pct_revenue"], 0.019)  # latest FY


def test_current_actuals_capex_falls_back_to_latest_fy_when_ttm_unavailable():
    """No TTM capex in the canonical snapshot (thin/unavailable cash-flow
    statement for this ticker) → falls back to the latest-FY ratio from
    HistoricalMetrics, exactly the pre-TTM behavior — never fabricated, and
    ``capex_is_ttm`` reports False so the report never mislabels the fallback
    as TTM (BUG-023 displayed==actual)."""
    actuals, capex_is_ttm = dcf_current_actuals(_fd(capital_expenditure=None), _hist())
    assert math.isclose(actuals["capex_pct_revenue"], 30.0 / 100.0)  # latest FY
    assert capex_is_ttm is False
    # Margin is unaffected — it has its own independent TTM source.
    assert actuals["ebitda_margin"] == 0.605


def test_current_actuals_missing_series_is_none_never_fabricated():
    """No TTM capex AND empty cash-flow series → capex is None (not 0.0); empty
    ΔNWC series → nwc is None too."""
    actuals, capex_is_ttm = dcf_current_actuals(
        _fd(capital_expenditure=None),
        _hist(capital_expenditure=[], change_in_working_capital=[]),
    )
    assert actuals["capex_pct_revenue"] is None
    assert capex_is_ttm is False
    assert actuals["nwc_pct_revenue"] is None
    # The TTM margin still resolves from the income snapshot.
    assert actuals["ebitda_margin"] == 0.605


def test_current_actuals_ttm_margin_none_when_ebitda_missing():
    """No TTM EBITDA in the snapshot → margin None (not 0), never fabricated."""
    actuals, _capex_is_ttm = dcf_current_actuals(_fd(ebitda=None), _hist())
    assert actuals["ebitda_margin"] is None


def test_current_actuals_ttm_capex_zero_revenue_guarded_not_crash():
    """TTM capex present but revenue is 0/non-finite → ttm ratio guarded to None,
    falls back to the (also revenue-gated) latest-FY ratio rather than a
    ZeroDivisionError. Exercised via a zero-revenue FinancialData built directly
    (revenue is a required field so it can't be omitted, only zeroed)."""
    fd = _fd(capital_expenditure=35_000_000_000)
    fd.income.revenue = 0.0
    actuals, capex_is_ttm = dcf_current_actuals(fd, _hist())
    assert capex_is_ttm is False
    # historical.revenue's latest year (100.0) is non-zero, so the FY fallback
    # still resolves — the guard degrades gracefully, it doesn't cascade to None.
    assert math.isclose(actuals["capex_pct_revenue"], 30.0 / 100.0)


# ── nwc_clamped (via DCFInputs default + seed_dcf_inputs end-to-end) ──────────


def test_nwc_clamped_defaults_false_on_direct_construction():
    assert _make_inputs().nwc_clamped is False


def _fd(
    ebitda: float | None = 60_500_000_000,
    capital_expenditure: float | None = 35_000_000_000,
) -> FinancialData:
    # TTM EBITDA margin = ebitda / 100B (default 60.5%) and TTM capex ratio =
    # capital_expenditure / 100B (default 35%) — both deliberately DISTINCT from
    # _hist()'s latest annual (margin 55%, capex 30%), so the tests prove the TTM
    # source (not the historical fallback) is what's used.
    return FinancialData(
        ticker="TEST",
        company_name="Test Co",
        timestamp=datetime.now(tz=timezone.utc),
        income=IncomeStatement(
            revenue=100_000_000_000,
            ebitda=ebitda,
            net_income=28_000_000_000,
            operating_margin=0.48,
            depreciation_amortization=3_000_000_000,
            interest_expense=1_000_000_000,
            capital_expenditure=capital_expenditure,
        ),
        balance=BalanceSheet(total_debt=20_000_000_000, total_cash=10_000_000_000),
        market=MarketData(
            market_cap=800_000_000_000,
            shares_outstanding=1_000_000_000,
            current_price=800.0,
            industry="Software",
            sector="Technology",
            beta=1.1,
        ),
    )


def test_nwc_clamped_true_when_median_exceeds_band_end_to_end():
    """ΔNWC/revenue median of −15% → negated +15% > the +10% band → clamped ⚠."""
    hist = _hist(
        revenue=[100e9, 100e9, 100e9],
        change_in_working_capital=[-15e9, -14e9, -16e9],
    )
    inputs = seed_dcf_inputs(_fd(), hist)
    assert inputs.nwc_clamped is True
    # The clamp is real: the modelled nwc_pct sits at the +10% ceiling, not +15%.
    assert inputs.nwc_pct_revenue == 0.10


def test_nwc_clamped_false_for_in_band_nwc_end_to_end():
    """Small ΔNWC swings stay inside ±10% → no clamp."""
    hist = _hist(
        revenue=[100e9, 100e9, 100e9],
        change_in_working_capital=[-1e9, -2e9, -1.9e9],
    )
    inputs = seed_dcf_inputs(_fd(), hist)
    assert inputs.nwc_clamped is False
