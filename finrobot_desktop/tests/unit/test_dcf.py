import pytest
from finagent.engine.models.financial import DCFInputs
from finagent.engine.compute.dcf import calculate_dcf, calculate_sensitivity


def _make_inputs(**overrides):
    defaults = dict(
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
    )
    defaults.update(overrides)
    return DCFInputs(**defaults)


def test_dcf_correctness_hand_calculated():
    """Hand-calculated expected value: ~$303.64 per share.
    revenue_base=100B, 5×5% growth, EBITDA=35%, capex=5%, nwc=2%, tax=21%
    wacc_override=10%, tg=2.5%, shares=1B, net_debt=10B
    See spec for full workings. Assert within $0.10."""
    inputs = _make_inputs()
    result = calculate_dcf(inputs, wacc_override=0.10)
    assert abs(result.implied_price - 303.64) < 0.10, f"Got {result.implied_price}"


def test_dcf_deterministic():
    inputs = _make_inputs()
    r1 = calculate_dcf(inputs)
    r2 = calculate_dcf(inputs)
    assert r1.implied_price == r2.implied_price
    assert r1.wacc == r2.wacc
    assert r1.enterprise_value == r2.enterprise_value


def test_wacc_override():
    inputs = _make_inputs()
    result = calculate_dcf(inputs, wacc_override=0.12)
    assert result.wacc == 0.12
    assert result.cost_of_equity is None


def test_tg_override():
    inputs = _make_inputs()
    result = calculate_dcf(inputs, tg_override=0.03)
    # verify terminal_value uses 0.03
    final_fcf = result.projected_fcf[-1]
    expected_tv = final_fcf * (1 + 0.03) / (result.wacc - 0.03)
    assert abs(result.terminal_value - expected_tv) < 1


def test_sensitivity_table_dimensions():
    inputs = _make_inputs()
    wacc_range = [0.08, 0.09, 0.10]
    tg_range = [0.02, 0.025]
    table = calculate_sensitivity(inputs, wacc_range, tg_range)
    assert len(table["implied_prices"]) == 3
    assert all(len(row) == 2 for row in table["implied_prices"])


def test_sensitivity_higher_wacc_lower_price():
    inputs = _make_inputs()
    wacc_range = [0.08, 0.09, 0.10, 0.11, 0.12]
    tg_range = [0.02]
    table = calculate_sensitivity(inputs, wacc_range, tg_range)
    prices = [row[0] for row in table["implied_prices"] if row[0] is not None]
    assert prices == sorted(prices, reverse=True)


def test_sensitivity_higher_tg_higher_price():
    inputs = _make_inputs()
    wacc_range = [0.10]
    tg_range = [0.01, 0.02, 0.03]
    table = calculate_sensitivity(inputs, wacc_range, tg_range)
    prices = [p for p in table["implied_prices"][0] if p is not None]
    assert prices == sorted(prices)


def test_sensitivity_none_where_tg_gte_wacc():
    inputs = _make_inputs()
    wacc_range = [0.05]
    tg_range = [0.03, 0.05, 0.06]  # 0.05 == wacc, 0.06 > wacc → both None
    table = calculate_sensitivity(inputs, wacc_range, tg_range)
    row = table["implied_prices"][0]
    assert row[0] is not None  # 0.03 < 0.05 → valid
    assert row[1] is None  # 0.05 == 0.05 → None
    assert row[2] is None  # 0.06 > 0.05 → None


def test_terminal_growth_gte_wacc_raises():
    inputs = _make_inputs(terminal_growth_rate=0.025)
    with pytest.raises(ValueError):
        calculate_dcf(inputs, wacc_override=0.02)  # tg=0.025 >= wacc=0.02


def test_zero_capex_zero_nwc():
    inputs = _make_inputs(capex_pct_revenue=0, nwc_pct_revenue=0)
    result = calculate_dcf(inputs)
    # FCF = EBITDA * (1 - tax)
    expected_fcf0 = result.projected_ebitda[0] * (1 - 0.21)
    assert abs(result.projected_fcf[0] - expected_fcf0) < 1


def test_fcf_formula_explicit():
    """FCF = EBITDA*(1-tax) - revenue*capex_pct - revenue*nwc_pct"""
    inputs = _make_inputs()
    result = calculate_dcf(inputs)
    rev0 = result.projected_revenue[0]
    ebitda0 = result.projected_ebitda[0]
    expected = ebitda0 * (1 - 0.21) - rev0 * 0.05 - rev0 * 0.02
    assert abs(result.projected_fcf[0] - expected) < 1


# --- P2a: standard FCF formula with D&A ---


def test_dcf_standard_formula_with_da_hand_calculated():
    """Standard FCF formula: EBIT(1-T) + D&A - CapEx - ΔNWC.

    Inputs:
      - revenue_base: 100B, growth: [0.05]*5, ebitda_margin: 0.35
      - da_pct_revenue: 0.10, capex_pct: 0.05, nwc_pct: 0.02, tax: 0.21
      - wacc_override: 0.10, tg: 0.025

    Year 1 hand calculation:
      rev      = 100B × 1.05 = 105B
      ebitda   = 105B × 0.35 = 36.75B
      da       = 105B × 0.10 = 10.5B
      ebit     = 36.75B - 10.5B = 26.25B
      fcf      = 26.25B × 0.79 + 10.5B - 105B × 0.05 - 105B × 0.02
               = 20.7375B + 10.5B - 5.25B - 2.1B
               = 23.8875B

    Compare to simplified formula (no D&A):
      fcf_simplified = 36.75B × 0.79 - 5.25B - 2.1B = 21.6825B

    The standard formula gives higher FCF because D&A provides a tax shield.
    Difference = D&A × tax_rate = 10.5B × 0.21 = 2.205B
    23.8875 - 21.6825 = 2.205B ✓

    Source: Damodaran, "Investment Valuation" 3rd Ed., Chapter 12.
    """
    inputs = _make_inputs(da_pct_revenue=0.10)
    result = calculate_dcf(inputs, wacc_override=0.10)

    # Y1 FCF check
    assert result.projected_fcf[0] == pytest.approx(23_887_500_000, rel=1e-9)

    # Formula tag
    assert result.fcf_formula == "standard_with_da"


def test_dcf_simplified_formula_when_da_none():
    """When da_pct_revenue is None, use P1.5 simplified formula."""
    inputs = _make_inputs()  # da_pct_revenue defaults to None
    result = calculate_dcf(inputs, wacc_override=0.10)
    assert result.fcf_formula == "simplified"
    # Y1 FCF should match simplified: EBITDA*(1-T) - capex - nwc
    rev1 = 100e9 * 1.05
    expected_fcf = rev1 * 0.35 * 0.79 - rev1 * 0.05 - rev1 * 0.02
    assert result.projected_fcf[0] == pytest.approx(expected_fcf, rel=1e-9)


def test_dcf_da_tax_shield_difference():
    """Standard - simplified = D&A × tax_rate (the tax shield)."""
    inputs_with_da = _make_inputs(da_pct_revenue=0.10)
    inputs_without = _make_inputs()

    r_with = calculate_dcf(inputs_with_da, wacc_override=0.10)
    r_without = calculate_dcf(inputs_without, wacc_override=0.10)

    # For each year, difference should be rev × da_pct × tax_rate
    for i in range(5):
        rev = r_with.projected_revenue[i]
        expected_diff = rev * 0.10 * 0.21
        actual_diff = r_with.projected_fcf[i] - r_without.projected_fcf[i]
        assert actual_diff == pytest.approx(expected_diff, rel=1e-9)


def test_dcf_da_zero_equivalent_to_simplified():
    """da_pct_revenue=0.0 means no D&A → EBIT=EBITDA, but formula is 'standard_with_da'."""
    inputs_da0 = _make_inputs(da_pct_revenue=0.0)
    inputs_none = _make_inputs()

    r_da0 = calculate_dcf(inputs_da0, wacc_override=0.10)
    r_none = calculate_dcf(inputs_none, wacc_override=0.10)

    # FCF values should be identical (D&A=0 → no tax shield difference)
    for i in range(5):
        assert r_da0.projected_fcf[i] == pytest.approx(r_none.projected_fcf[i], rel=1e-9)

    # But formula label differs
    assert r_da0.fcf_formula == "standard_with_da"
    assert r_none.fcf_formula == "simplified"
