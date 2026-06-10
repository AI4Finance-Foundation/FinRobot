import pytest
from pydantic import ValidationError

from finrobot.engine.models.financial import DCFInputs, DCFResult
from finrobot.engine.compute.operators.dcf import calculate_dcf, calculate_sensitivity


def _make_inputs(**overrides):
    # da_pct_revenue defaults to 0.0 so existing hand-calc tests (designed
    # before D&A was required) still hit the same FCF arithmetic: when D&A=0,
    # the standard formula collapses to EBITDA(1-T) - CapEx - ΔNWC.
    defaults = dict(
        revenue_base=100_000_000_000,
        revenue_growth_rates=[0.05] * 5,
        ebitda_margin=0.35,
        capex_pct_revenue=0.05,
        nwc_pct_revenue=0.02,
        da_pct_revenue=0.0,
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
    """Hand-calculated expected value: ~$357.80 per share.

    revenue_base=100B, 5×5% growth, EBITDA=35%, capex=5%, nwc=2%, da=0%, tax=21%
    wacc_override=10%, tg=2.5%, shares=1B, net_debt=10B.

    Explicit FCF margin = 0.35×0.79 − 0.05 capex − 0.02 nwc = 0.2065 of revenue.
    Terminal FCF normalizes capex→D&A×(1+g): here D&A=0 so terminal capex=0, giving
    terminal margin = 0.35×0.79 − 0 − 0.02 = 0.2565 of rev₅. rev₅=127.628B →
    terminal FCF=32.736B, TV=32.736×1.025/0.075=447.40B, PV(TV)=277.79B;
    PV(explicit FCFs)=89.996B → EV=367.79B − 10B debt = 357.79B / 1B sh = $357.80.
    Assert within $0.10."""
    inputs = _make_inputs()
    result = calculate_dcf(inputs, wacc_override=0.10)
    assert abs(result.implied_price - 357.80) < 0.10, f"Got {result.implied_price}"


def test_dcf_deterministic():
    inputs = _make_inputs()
    r1 = calculate_dcf(inputs)
    r2 = calculate_dcf(inputs)
    assert r1.implied_price == r2.implied_price
    assert r1.wacc == r2.wacc
    assert r1.enterprise_value == r2.enterprise_value


def test_currency_passthrough_is_pure_metadata():
    """``currency`` is a passthrough tag: it must reach DCFResult unchanged and
    must NOT perturb any computed number. A non-USD tag produces byte-identical
    arithmetic to the default — the value is metadata, not an input to the math."""
    usd = calculate_dcf(_make_inputs())
    twd = calculate_dcf(_make_inputs(currency="TWD"))
    assert usd.currency == "USD"  # default threads through
    assert twd.currency == "TWD"  # explicit tag threads through
    # Every computed field is identical regardless of the currency tag.
    assert twd.implied_price == usd.implied_price
    assert twd.wacc == usd.wacc
    assert twd.enterprise_value == usd.enterprise_value
    assert twd.equity_value == usd.equity_value
    assert twd.terminal_value == usd.terminal_value
    assert twd.projected_fcf == usd.projected_fcf


def test_wacc_override():
    inputs = _make_inputs()
    result = calculate_dcf(inputs, wacc_override=0.12)
    assert result.wacc == 0.12
    assert result.cost_of_equity is None


def test_tg_override():
    from finrobot.engine.compute.operators.dcf import _terminal_fcf

    inputs = _make_inputs()
    result = calculate_dcf(inputs, tg_override=0.03)
    # terminal_value capitalizes the NORMALIZED steady-state FCF (capex→D&A), not
    # the last explicit-year FCF — and at the overridden tg=0.03.
    terminal_fcf = _terminal_fcf(inputs, result.projected_revenue[-1], 0.03)
    expected_tv = terminal_fcf * (1 + 0.03) / (result.wacc - 0.03)
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


def test_negative_terminal_fcf_raises_no_negative_price():
    """BUG-074: when the STEADY-STATE terminal FCF is negative, the Gordon formula
    (tg < WACC) is still defined but would capitalize it into a perpetual NEGATIVE
    terminal value and a negative implied price per share. calculate_dcf must
    refuse — raising ValueError (mirroring the tg >= WACC degrade) so the
    equity_research pipeline skips the DCF chapter instead of printing a negative
    fair value.

    The guard is on the NORMALIZED terminal FCF (capex→D&A), not the last
    explicit-year FCF — a heavy-capex growth year is no longer mistaken for a
    perpetual trough. So the trigger is a structurally unprofitable steady state:
    here EBITDA margin (4%) sits BELOW D&A (5%), making terminal EBIT — and thus
    NOPAT and terminal FCF — negative regardless of the capex normalization.
    """
    inputs = _make_inputs(
        revenue_base=1e11,
        revenue_growth_rates=[0.02] * 5,
        ebitda_margin=0.04,
        capex_pct_revenue=0.06,
        da_pct_revenue=0.05,  # D&A > EBITDA margin → terminal EBIT < 0
        nwc_pct_revenue=0.02,
        terminal_growth_rate=0.025,  # tg < WACC: tg >= WACC guard does NOT fire
    )

    # Sanity: the NORMALIZED terminal FCF really is negative for these inputs, so
    # this exercises the terminal-FCF guard specifically (not the tg >= WACC one).
    from finrobot.engine.compute.operators.dcf import _project_full, _terminal_fcf

    revenue, _, _ = _project_full(inputs)
    assert _terminal_fcf(inputs, revenue[-1], inputs.terminal_growth_rate) < 0

    with pytest.raises(ValueError):
        calculate_dcf(inputs)

    # And no path silently returns a DCFResult carrying a negative implied price.
    try:
        result = calculate_dcf(inputs)
    except ValueError:
        result = None
    assert result is None


def test_zero_capex_zero_nwc():
    inputs = _make_inputs(capex_pct_revenue=0, nwc_pct_revenue=0)
    result = calculate_dcf(inputs)
    # FCF = EBITDA * (1 - tax)
    expected_fcf0 = result.projected_ebitda[0] * (1 - 0.21)
    assert abs(result.projected_fcf[0] - expected_fcf0) < 1


def test_dcf_result_has_no_removed_fcf_formula_field():
    """DCFResult keeps the FCF contract in code and tests, not serialized output."""
    inputs = _make_inputs()
    result = calculate_dcf(inputs, wacc_override=0.10)
    dumped = result.model_dump()
    assert "fcf_formula" not in DCFResult.model_fields
    assert "fcf_formula" not in dumped


def test_fcf_formula_explicit():
    """FCF = EBIT(1-tax) + D&A - revenue*capex_pct - revenue*nwc_pct.

    With da_pct_revenue=0 the standard formula collapses to:
        FCF = EBITDA(1-tax) - revenue*capex_pct - revenue*nwc_pct
    """
    inputs = _make_inputs()  # da_pct_revenue=0.0 by default helper
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


def test_dcf_da_tax_shield_increases_fcf():
    """D&A creates a tax shield: FCF(D&A=0.10) > FCF(D&A=0).

    Difference = rev × da_pct × tax_rate. Phase B refactor removed the
    simplified branch entirely, so this comparison is the standard formula
    with two different D&A levels.
    """
    inputs_with_da = _make_inputs(da_pct_revenue=0.10)
    inputs_no_da = _make_inputs(da_pct_revenue=0.0)

    r_with = calculate_dcf(inputs_with_da, wacc_override=0.10)
    r_no = calculate_dcf(inputs_no_da, wacc_override=0.10)

    for i in range(5):
        rev = r_with.projected_revenue[i]
        expected_diff = rev * 0.10 * 0.21
        actual_diff = r_with.projected_fcf[i] - r_no.projected_fcf[i]
        assert actual_diff == pytest.approx(expected_diff, rel=1e-9)
        # Monotonicity invariant — guarded separately by test_fcf_formula_invariants.py
        assert r_with.projected_fcf[i] > r_no.projected_fcf[i]


def test_dcf_da_pct_revenue_defaults_to_zero():
    """da_pct_revenue defaults to 0.0. This is the legacy-compat path for
    direct callers; seed_dcf_inputs always overrides with a non-zero value
    from filings or Damodaran fallback.

    Why default to 0 instead of being required: pre-Phase-B code paths
    (artifacts, snapshots, ad-hoc what-if scripts) constructed DCFInputs
    without D&A. Forcing them all to migrate would expand this PR's blast
    radius. The dcf_seed unit tests guard the "never zero from seed" path.
    """
    inputs = DCFInputs(
        revenue_base=100e9,
        revenue_growth_rates=[0.05] * 5,
        ebitda_margin=0.35,
        capex_pct_revenue=0.05,
        nwc_pct_revenue=0.02,
        # da_pct_revenue omitted — picks up 0.0 default
        tax_rate=0.21,
        risk_free_rate=0.04,
        beta=1.2,
        equity_risk_premium=0.05,
        cost_of_debt=0.04,
        debt_ratio=0.1,
        terminal_growth_rate=0.025,
        shares_outstanding=1e9,
        net_debt=10e9,
    )
    assert inputs.da_pct_revenue == 0.0


# ---------------------------------------------------------------------------
# Forward-Gordon refusal set: NaN inputs / negative equity / sub-floor spread
# ---------------------------------------------------------------------------


class TestInputFiniteness:
    """DCFInputs is the chokepoint every entry path shares (REST bodies accept
    the JSON NaN literal). Bounded fields reject NaN for free; the three
    unbounded ones needed explicit validators — a NaN sailed through every
    guard in calculate_dcf (NaN comparisons are all False) and shipped
    implied_price=NaN into the aggregation band."""

    def test_nan_growth_rate_rejected_at_model(self):
        with pytest.raises(ValidationError, match="finite"):
            _make_inputs(revenue_growth_rates=[0.10, float("nan"), 0.05])

    def test_inf_revenue_base_rejected_at_model(self):
        with pytest.raises(ValidationError, match="finite"):
            _make_inputs(revenue_base=float("inf"))

    def test_nan_net_debt_rejected_at_model(self):
        with pytest.raises(ValidationError, match="finite"):
            _make_inputs(net_debt=float("nan"))


class TestNegativeEquityBridge:
    def test_net_debt_exceeding_ev_raises_instead_of_negative_price(self):
        """BUG-074's bridge-side sibling: positive FCFs pass the terminal gate,
        but net debt > EV drove equity negative and the pipeline narrative
        printed 'implies $-1512.42 per share'. Equity fair value floors near
        zero — raise and degrade to relative valuation."""
        with pytest.raises(ValueError, match="non-positive"):
            calculate_dcf(_make_inputs(net_debt=5e12))


class TestGordonSpreadFloor:
    def test_sub_floor_spread_raises(self):
        """A 0.5% wacc−tg spread is a 200× Gordon multiplier — Monte Carlo has
        clamped per-path draws to the 1.5% floor since day one; the
        deterministic base case published the blowup as the headline price."""
        with pytest.raises(ValueError, match="spread"):
            calculate_dcf(_make_inputs(), wacc_override=0.03, tg_override=0.025)

    def test_spread_at_floor_passes(self):
        result = calculate_dcf(_make_inputs(), wacc_override=0.04, tg_override=0.025)
        assert result.implied_price > 0

    def test_sensitivity_grid_blanks_sub_floor_cells(self):
        """Grid cells must refuse exactly what the base case refuses — the
        near-diagonal blowups rendered in the sensitivity table while the
        headline raised."""
        inputs = _make_inputs()
        grid = calculate_sensitivity(inputs, wacc_range=[0.03, 0.08], tg_range=[0.025])
        # wacc=3% vs tg=2.5%: spread 0.5% < 1.5% floor → None.
        assert grid["implied_prices"][0][0] is None
        # wacc=8%: healthy spread → real price.
        assert grid["implied_prices"][1][0] is not None


class TestTerminalReinvestmentAnchor:
    """Terminal capex anchors on min(da_pct, capex_pct) — GAAP D&A polluted by
    acquisition-intangible amortization must not masquerade as perpetual
    reinvestment. Ratio fixtures come from external benchmarks: AMD FY2025 SEC
    XBRL (revenue $34.64B, capex $0.97B = 2.8%, OCF $7.71B → real FCF +$6.7B)
    against our seeded GAAP D&A 12.3%; TSLA ratios from the 2026-06-10 artifact
    seed (D&A 5.5% < capex 9.2%)."""

    def test_amortization_heavy_terminal_anchors_on_real_capex(self):
        """AMD-ratio fixture, hand-calculated: $191.09 per share.

        rev=100B, 1×0% growth, EBITDA=20.4%, D&A=12.3%, capex=2.5%, nwc=8.1%,
        terminal_nwc=1.42%, tax=15.1%, wacc_override=10%, tg=3%, shares=1B,
        net_debt=0.

        Explicit FCF₁ = (20.4−12.3)×0.849 + 12.3 − 2.5 − 8.1 = 8.5769B,
        PV = 7.7972B. Terminal anchor = min(12.3%, 2.5%) = 2.5%:
        FCF_T = (20.4−2.5)×0.849 + 2.5 − 2.5×1.03 − 1.42 = 13.7021B,
        TV = 13.7021×1.03/0.07 = 201.617B, PV(TV) = 183.288B.
        EV = 191.085B → $191.09/share.

        Under the old bare-D&A anchor the terminal margin was
        (20.4−12.3)×0.849 − 12.3×0.03 − 8.1 = −1.59% of revenue → the DCF
        chapter died (live run_7fa34496cb3a: terminal FCF −4.34e9) for a
        company whose real FCF is +$6.7B (SEC FY2025)."""
        inputs = _make_inputs(
            revenue_base=100_000_000_000,
            revenue_growth_rates=[0.0],
            ebitda_margin=0.204,
            da_pct_revenue=0.123,
            capex_pct_revenue=0.025,
            nwc_pct_revenue=0.081,
            terminal_nwc_pct_revenue=0.0142,
            tax_rate=0.151,
            terminal_growth_rate=0.03,
            net_debt=0,
        )
        result = calculate_dcf(inputs, wacc_override=0.10)
        assert abs(result.implied_price - 191.09) < 0.5, f"Got {result.implied_price}"

    def test_capex_heavy_terminal_keeps_da_anchor(self):
        """TSLA-ratio fixture, hand-calculated: $94.60 per share — identical to
        the pre-fix arithmetic, because min(5.5%, 9.2%) = 5.5% = the old D&A
        anchor. Pins that the AMD fix does NOT walk back the capex-heavy
        normalization (commit 1a677d4c, implied $28 → $38 class).

        rev=100B, 1×0% growth, EBITDA=15.1%, D&A=5.5%, capex=9.2%, nwc=−0.1%,
        tax=28%, wacc_override=10%, tg=3%: FCF₁ = 9.6×0.72+5.5−9.2+0.1
        = 3.312B, PV = 3.0109B; FCF_T = 9.6×0.72+5.5−5.665+0.1 = 6.847B,
        TV = 100.748B, PV = 91.589B → EV 94.600B → $94.60."""
        inputs = _make_inputs(
            revenue_base=100_000_000_000,
            revenue_growth_rates=[0.0],
            ebitda_margin=0.151,
            da_pct_revenue=0.055,
            capex_pct_revenue=0.092,
            nwc_pct_revenue=-0.001,
            tax_rate=0.28,
            terminal_growth_rate=0.03,
            net_debt=0,
        )
        result = calculate_dcf(inputs, wacc_override=0.10)
        assert abs(result.implied_price - 94.60) < 0.5, f"Got {result.implied_price}"


class TestTerminalNwc:
    def test_none_falls_back_to_explicit_window_nwc(self):
        """terminal_nwc_pct_revenue=None (direct REST payloads, hand-built
        inputs) must reproduce the explicit-window ΔNWC ratio in the
        perpetuity — byte-identical to passing it explicitly."""
        implicit = calculate_dcf(_make_inputs(), wacc_override=0.10)
        explicit = calculate_dcf(_make_inputs(terminal_nwc_pct_revenue=0.02), wacc_override=0.10)
        assert implicit.implied_price == explicit.implied_price
        assert implicit.terminal_value == explicit.terminal_value

    def test_scales_only_the_perpetuity_not_explicit_fcfs(self):
        """The terminal override must not leak into the explicit window: the
        projected FCF path is byte-identical, only the terminal value moves —
        and a lower steady-state drag means a HIGHER terminal value."""
        base = calculate_dcf(_make_inputs(), wacc_override=0.10)
        scaled = calculate_dcf(_make_inputs(terminal_nwc_pct_revenue=0.005), wacc_override=0.10)
        assert scaled.projected_fcf == base.projected_fcf
        assert scaled.terminal_value > base.terminal_value
        assert scaled.implied_price > base.implied_price

    def test_perpetual_nwc_subsidy_no_longer_props_up_cash_burner(self):
        """RIVN-ratio fixture: EBITDA 16.6% sits BELOW the 20.7% maintenance
        anchor — a perpetually terminal-unprofitable profile. The legacy
        fallback (ΔNWC −10% of revenue as a cash source, forever) papered over
        it and published a fair value 1.57x the market price for a cash
        burner; the growth-scaled steady-state subsidy (−1.8%) no longer
        covers the gap, so the Gordon perpetuity honestly refuses."""
        rivn_ratios = dict(
            revenue_base=100_000_000_000,
            revenue_growth_rates=[0.0],
            ebitda_margin=0.166,
            da_pct_revenue=0.207,
            capex_pct_revenue=0.231,
            nwc_pct_revenue=-0.10,
            tax_rate=0.20,
            terminal_growth_rate=0.03,
            net_debt=0,
        )
        # Legacy fallback (None → −10% forever): the subsidy alone keeps the
        # terminal FCF positive and a price prints.
        legacy = calculate_dcf(_make_inputs(**rivn_ratios), wacc_override=0.10)
        assert legacy.implied_price > 0
        # Growth-scaled steady state: subsidy shrinks to −1.8% and the
        # structurally negative perpetuity surfaces.
        with pytest.raises(ValueError, match="non-positive"):
            calculate_dcf(
                _make_inputs(**rivn_ratios, terminal_nwc_pct_revenue=-0.018),
                wacc_override=0.10,
            )
