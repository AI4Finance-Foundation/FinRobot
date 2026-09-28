"""Property-based fuzz over the DCF / WACC operators (hypothesis).

Complements the point-value tests in test_dcf.py (external-benchmark hand
calcs) and the NaN-injection gate in tests/audit/test_operator_finiteness_gate.py
(fixed non-finite probes). The increment here is DISTRIBUTIONAL: relations that
must hold across the whole financially-legal input domain, not at chosen points.

Properties pinned:
  1. Monotonicity — implied price non-increasing in WACC, non-decreasing in
     terminal growth (within the Gordon-legal region).
  2. Round-trip — _price_for(g) → solve_for_implied_growth recovers g to
     bisection tolerance.
  3. Boundary gates — tg >= wacc and non-positive terminal FCF raise ValueError
     in both the forward DCF and the reverse kernel; the sub-floor Gordon
     spread raises in calculate_dcf but is deliberately ACCEPTED by _price_for
     (reverse kernel reports the market's absurd implied params, 协议 §2).
  4. Finiteness — over the legal domain calculate_dcf either raises one of its
     four documented degrade-path ValueErrors or returns all-finite numbers;
     it never leaks NaN/Inf and never fabricates a number on a refused model.
  5. WACC — convex-combination bound (between after-tax debt cost and equity
     cost) and equal-cost collapse.

Strategy discipline: generators constrain to the legal domain up front (no
assume() sieves). The "healthy" composite keeps the steady-state terminal FCF
margin (ebitda−anchor)(1−tax) − anchor·g − nwc strictly positive by
construction; the "cash-burner" composite forces it negative to hit the gate.
No point-value expectations are asserted anywhere here — relations only —
so no external benchmark is required (测试纪律: point values would need one).
"""

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from finrobot.engine.compute.operators.dcf import (
    _price_for,
    calculate_dcf,
    solve_for_implied_growth,
)
from finrobot.engine.compute.operators.wacc import calculate_wacc
from finrobot.engine.models.financial import DCFInputs, DCFResult
from finrobot.engine.models.valuation_thresholds import MIN_GORDON_SPREAD

# Wide-but-finite settings: pure arithmetic per example, so 100 examples per
# property keeps the whole module well under the 30s suite-increment budget.
# deadline=None — hypothesis per-example deadlines flake under parallel-session
# machine load, and these are CPU-only properties.
COMMON = settings(max_examples=100, deadline=None)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def healthy_dcf_inputs(
    draw: st.DrawFn,
    net_debt_lo: float = -0.3,
    net_debt_hi: float = 0.3,
) -> DCFInputs:
    """DCFInputs over a financially realistic, Gordon-legal domain.

    Domain guarantees (so calculate_dcf's terminal-FCF gate never trips):
      explicit FCF margin = e(1-t) + d·t − c − n  >= 0.15·0.65 − 0.06 − 0.03 > 0
      terminal FCF margin = (e−a)(1−t) − a·g − nwc_t >= (0.15−0.06)·0.65
                            − 0.06·0.05 − 0.03 > 0   (a = min(d, c))
    The CAPM WACC implied by the rate params is >= ~1.98%, and terminal growth
    is drawn at <= wacc − (MIN_GORDON_SPREAD + 0.001), so the no-override path
    through calculate_dcf clears the tg and spread gates by construction.
    Equity CAN still go non-positive at high net debt — finiteness treats that
    documented refusal as a pass (explicit raise, not a fabricated number).
    """
    revenue_base = draw(st.floats(1e8, 5e11))
    n_years = draw(st.integers(3, 7))
    growth = draw(st.lists(st.floats(-0.05, 0.25), min_size=n_years, max_size=n_years))
    ebitda_margin = draw(st.floats(0.15, 0.45))
    capex_pct = draw(st.floats(0.01, 0.06))
    da_pct = draw(st.floats(0.01, 0.06))
    nwc_pct = draw(st.floats(0.0, 0.03))
    terminal_nwc = draw(st.one_of(st.none(), st.floats(0.0, 0.02)))
    tax_rate = draw(st.floats(0.10, 0.35))

    risk_free = draw(st.floats(0.015, 0.05))
    beta = draw(st.floats(0.5, 2.0))
    erp = draw(st.floats(0.03, 0.07))
    cost_of_debt = draw(st.floats(0.02, 0.08))
    debt_ratio = draw(st.floats(0.0, 0.6))
    _, capm_wacc = calculate_wacc(risk_free, beta, erp, cost_of_debt, tax_rate, debt_ratio)
    tg_cap = min(0.05, capm_wacc - (MIN_GORDON_SPREAD + 0.001))
    terminal_growth = draw(st.floats(0.0, max(0.0, tg_cap)))

    net_debt = draw(st.floats(net_debt_lo, net_debt_hi)) * revenue_base
    shares = draw(st.floats(1e6, 2e10))

    return DCFInputs(
        revenue_base=revenue_base,
        revenue_growth_rates=growth,
        ebitda_margin=ebitda_margin,
        capex_pct_revenue=capex_pct,
        nwc_pct_revenue=nwc_pct,
        terminal_nwc_pct_revenue=terminal_nwc,
        da_pct_revenue=da_pct,
        tax_rate=tax_rate,
        risk_free_rate=risk_free,
        beta=beta,
        equity_risk_premium=erp,
        cost_of_debt=cost_of_debt,
        debt_ratio=debt_ratio,
        terminal_growth_rate=terminal_growth,
        shares_outstanding=shares,
        net_debt=net_debt,
    )


@st.composite
def cash_burner_inputs(draw: st.DrawFn) -> DCFInputs:
    """Inputs whose steady-state terminal FCF is negative BY CONSTRUCTION.

    terminal margin <= (0.05 − a)(1−t) + 0 − 0.30 < 0 for every draw, so the
    Gordon perpetuity is undefined and both the forward DCF and the reverse
    kernel must refuse (BUG-074 gate).
    """
    revenue_base = draw(st.floats(1e8, 1e11))
    n_years = draw(st.integers(3, 6))
    growth = draw(st.lists(st.floats(0.0, 0.20), min_size=n_years, max_size=n_years))
    return DCFInputs(
        revenue_base=revenue_base,
        revenue_growth_rates=growth,
        ebitda_margin=draw(st.floats(0.0, 0.05)),
        capex_pct_revenue=draw(st.floats(0.01, 0.04)),
        nwc_pct_revenue=draw(st.floats(0.30, 0.50)),
        da_pct_revenue=draw(st.floats(0.01, 0.04)),
        tax_rate=draw(st.floats(0.10, 0.30)),
        risk_free_rate=0.04,
        beta=1.0,
        equity_risk_premium=0.05,
        cost_of_debt=0.04,
        debt_ratio=0.2,
        terminal_growth_rate=0.02,
        shares_outstanding=draw(st.floats(1e6, 1e10)),
        net_debt=0.0,
    )


# Override-axis draws used where the test controls WACC directly.
wacc_overrides = st.floats(0.06, 0.18)
mid_year_flags = st.booleans()


def _tolerance(*prices: float) -> float:
    """Relative float-noise budget for monotonicity comparisons."""
    return 1e-9 * max(1.0, *(abs(p) for p in prices))


# ---------------------------------------------------------------------------
# 1. Monotonicity
# ---------------------------------------------------------------------------


@COMMON
@given(
    inputs=healthy_dcf_inputs(net_debt_lo=-0.3, net_debt_hi=0.0),
    wacc=wacc_overrides,
    delta=st.floats(1e-4, 0.05),
    mid_year=mid_year_flags,
)
def test_implied_price_nonincreasing_in_wacc(
    inputs: DCFInputs, wacc: float, delta: float, mid_year: bool
) -> None:
    """Raising the discount rate must never raise the implied price.

    net_debt <= 0 in this draw so the equity>0 gate cannot trip at the higher
    WACC and turn a monotonicity check into a refusal comparison.
    """
    tg = min(inputs.terminal_growth_rate, wacc - MIN_GORDON_SPREAD - 0.001)
    lo = calculate_dcf(inputs, wacc_override=wacc, tg_override=tg, mid_year=mid_year)
    hi = calculate_dcf(inputs, wacc_override=wacc + delta, tg_override=tg, mid_year=mid_year)
    assert hi.implied_price <= lo.implied_price + _tolerance(lo.implied_price, hi.implied_price), (
        f"WACC {wacc:.4f}->{wacc + delta:.4f} RAISED price {lo.implied_price} -> {hi.implied_price}"
    )


@COMMON
@given(
    inputs=healthy_dcf_inputs(net_debt_lo=-0.3, net_debt_hi=0.0),
    wacc=wacc_overrides,
    frac_lo=st.floats(0.0, 1.0),
    frac_hi=st.floats(0.0, 1.0),
    mid_year=mid_year_flags,
)
def test_implied_price_nondecreasing_in_terminal_growth(
    inputs: DCFInputs, wacc: float, frac_lo: float, frac_hi: float, mid_year: bool
) -> None:
    """Higher perpetual growth (still clearing the Gordon spread floor) must
    never lower the implied price.

    Both tg draws live in [0, wacc − floor − margin] as fractions of that
    span, so both calls clear calculate_dcf's spread gate by construction.
    The terminal FCF itself shrinks with g (capex = anchor·(1+g)), but within
    the healthy domain the perpetuity numerator stays positive and the
    (wacc − g) denominator effect dominates — price is still monotone.
    """
    span = wacc - MIN_GORDON_SPREAD - 0.001
    tg_a, tg_b = sorted((frac_lo * span, frac_hi * span))
    low = calculate_dcf(inputs, wacc_override=wacc, tg_override=tg_a, mid_year=mid_year)
    high = calculate_dcf(inputs, wacc_override=wacc, tg_override=tg_b, mid_year=mid_year)
    assert high.implied_price >= low.implied_price - _tolerance(
        low.implied_price, high.implied_price
    ), (
        f"tg {tg_a:.4f}->{tg_b:.4f} at WACC {wacc:.4f} LOWERED price "
        f"{low.implied_price} -> {high.implied_price}"
    )


# ---------------------------------------------------------------------------
# 2. Round-trip: _price_for ∘ solve_for_implied_growth ≈ identity
# ---------------------------------------------------------------------------


@COMMON
@given(
    inputs=healthy_dcf_inputs(net_debt_lo=-0.3, net_debt_hi=0.1),
    growth=st.floats(-0.09, 0.49),
    wacc=wacc_overrides,
    tg_frac=st.floats(0.0, 1.0),
    horizon=st.integers(3, 7),
    mid_year=mid_year_flags,
)
def test_implied_growth_round_trips_through_price(
    inputs: DCFInputs,
    growth: float,
    wacc: float,
    tg_frac: float,
    horizon: int,
    mid_year: bool,
) -> None:
    """Price a known constant growth with the kernel, then ask the bisection
    solver what growth that price implies — it must recover the seed.

    growth is drawn strictly inside the solver's default (−0.10, 0.50) bracket
    and price is strictly increasing in growth over the healthy domain, so the
    target always lands inside [price_at_lo, price_at_hi]. Bisection halts on
    bracket width < 1e-4, so |implied − seed| <= 1e-4; assert with cushion.
    """
    tg = tg_frac * (wacc - 0.02)  # keep tg < wacc with a clean 2pp margin
    price = _price_for(inputs, growth, wacc, tg, horizon, mid_year)
    result = solve_for_implied_growth(
        inputs,
        price,
        horizon_years=horizon,
        wacc_override=wacc,
        tg_override=tg,
        mid_year=mid_year,
    )
    implied = result["implied_growth"]
    assert implied is not None, f"seed growth {growth} priced to {price} but solver found no root"
    assert result["converged"] is True
    assert abs(implied - growth) < 5e-4, (
        f"round-trip drift: seeded g={growth:.6f}, solver returned {implied:.6f} "
        f"(price {price:.4f}, wacc {wacc:.4f}, tg {tg:.4f}, horizon {horizon})"
    )


# ---------------------------------------------------------------------------
# 3. Boundary gates
# ---------------------------------------------------------------------------


@COMMON
@given(
    inputs=healthy_dcf_inputs(),
    wacc=st.floats(0.05, 0.18),
    excess=st.floats(0.0, 0.05),
)
def test_terminal_growth_at_or_above_wacc_raises(
    inputs: DCFInputs, wacc: float, excess: float
) -> None:
    """tg >= wacc leaves the Gordon perpetuity undefined: both the forward DCF
    and the reverse kernel must raise, never price through it."""
    tg = wacc + excess
    with pytest.raises(ValueError, match="must be less than WACC"):
        calculate_dcf(inputs, wacc_override=wacc, tg_override=tg)
    with pytest.raises(ValueError, match="must be less than WACC"):
        _price_for(inputs, 0.05, wacc, tg, 5, False)


@COMMON
@given(
    inputs=healthy_dcf_inputs(),
    wacc=st.floats(0.05, 0.18),
    spread=st.floats(1e-4, MIN_GORDON_SPREAD - 1e-4),
)
def test_sub_floor_gordon_spread_forward_raises_reverse_accepts(
    inputs: DCFInputs, wacc: float, spread: float
) -> None:
    """A spread under MIN_GORDON_SPREAD is a forward-DCF refusal (blowup
    multiplier, not a valuation) — but the reverse kernel must still price it:
    its documented job is reporting the absurd params a market price implies,
    so its search domain deliberately reaches past the floor (协议 §2)."""
    tg = wacc - spread
    with pytest.raises(ValueError, match="below the"):
        calculate_dcf(inputs, wacc_override=wacc, tg_override=tg)
    price = _price_for(inputs, 0.05, wacc, tg, 5, False)
    assert math.isfinite(price)


@COMMON
@given(inputs=cash_burner_inputs())
def test_nonpositive_terminal_fcf_raises_everywhere(inputs: DCFInputs) -> None:
    """A negative steady-state terminal FCF must be refused symmetrically by
    the forward DCF and the reverse kernel (BUG-074 family) — capitalizing a
    perpetual cash burn into a negative 'fair value' is not a valuation."""
    with pytest.raises(ValueError, match="non-positive"):
        calculate_dcf(inputs, wacc_override=0.10, tg_override=0.02)
    with pytest.raises(ValueError, match="non-positive"):
        _price_for(inputs, 0.05, 0.10, 0.02, 5, False)


# ---------------------------------------------------------------------------
# 4. Finiteness over the legal domain
# ---------------------------------------------------------------------------

_NUMERIC_SCALARS = (
    "wacc",
    "terminal_value",
    "pv_terminal",
    "pv_fcf_total",
    "enterprise_value",
    "equity_value",
    "implied_price",
)

# The four documented degrade-path refusals (shared Gordon rejection set +
# the equity bridge). Any OTHER ValueError text is a real bug, re-raised.
_DOCUMENTED_REFUSALS = (
    "must be less than WACC",
    "below the",
    "non-positive",
)


@COMMON
@given(inputs=healthy_dcf_inputs(net_debt_lo=-0.3, net_debt_hi=0.3), mid_year=mid_year_flags)
def test_calculate_dcf_outputs_all_finite_or_documented_refusal(
    inputs: DCFInputs, mid_year: bool
) -> None:
    """Over the legal domain calculate_dcf has exactly two behaviours: an
    explicit documented ValueError (degrade to relative valuation) or a result
    whose every numeric field is finite. NaN/Inf leakage — the T4#5 disease —
    is a failure in either branch."""
    try:
        result: DCFResult = calculate_dcf(inputs, mid_year=mid_year)
    except ValueError as exc:
        assert any(s in str(exc) for s in _DOCUMENTED_REFUSALS), (
            f"undocumented ValueError from legal-domain inputs: {exc}"
        )
        return
    for field in _NUMERIC_SCALARS:
        value = getattr(result, field)
        assert math.isfinite(value), f"{field} is non-finite: {value!r}"
    assert result.cost_of_equity is not None and math.isfinite(result.cost_of_equity)
    for series_name in ("projected_revenue", "projected_ebitda", "projected_fcf"):
        series = getattr(result, series_name)
        assert len(series) == result.projection_years
        assert all(math.isfinite(v) for v in series), f"{series_name} leaked non-finite"


# ---------------------------------------------------------------------------
# 5. WACC properties
# ---------------------------------------------------------------------------


@COMMON
@given(
    risk_free=st.floats(0.0, 0.06),
    beta=st.floats(0.0, 2.5),
    erp=st.floats(0.0, 0.08),
    cost_of_debt=st.floats(0.0, 0.12),
    tax_rate=st.floats(0.0, 0.40),
    debt_ratio=st.floats(0.0, 1.0),
)
def test_wacc_between_after_tax_debt_cost_and_equity_cost(
    risk_free: float,
    beta: float,
    erp: float,
    cost_of_debt: float,
    tax_rate: float,
    debt_ratio: float,
) -> None:
    """WACC is a convex combination of the two capital costs (weights sum to 1
    by construction: E/(D+E) = 1 − debt_ratio), so it must lie between the
    after-tax cost of debt and the cost of equity."""
    cost_of_equity, wacc = calculate_wacc(risk_free, beta, erp, cost_of_debt, tax_rate, debt_ratio)
    after_tax_debt = cost_of_debt * (1 - tax_rate)
    lo, hi = sorted((after_tax_debt, cost_of_equity))
    eps = 1e-12 + 1e-9 * max(abs(lo), abs(hi))
    assert lo - eps <= wacc <= hi + eps, (
        f"WACC {wacc} escaped [{lo}, {hi}] (coe={cost_of_equity}, "
        f"atcd={after_tax_debt}, debt_ratio={debt_ratio})"
    )


@COMMON
@given(
    risk_free=st.floats(0.01, 0.05),
    beta=st.floats(0.5, 2.0),
    erp=st.floats(0.03, 0.07),
    tax_rate=st.floats(0.0, 0.40),
    debt_ratio=st.floats(0.0, 1.0),
)
def test_wacc_collapses_to_common_cost_when_costs_equal(
    risk_free: float, beta: float, erp: float, tax_rate: float, debt_ratio: float
) -> None:
    """When the after-tax debt cost equals the equity cost, the capital mix is
    irrelevant: WACC must equal that common cost at any debt ratio."""
    cost_of_equity = risk_free + beta * erp
    cost_of_debt = cost_of_equity / (1 - tax_rate)  # pre-tax cost whose after-tax == coe
    _, wacc = calculate_wacc(risk_free, beta, erp, cost_of_debt, tax_rate, debt_ratio)
    assert math.isclose(wacc, cost_of_equity, rel_tol=1e-9, abs_tol=1e-12), (
        f"equal-cost WACC {wacc} != common cost {cost_of_equity} at dr={debt_ratio}"
    )
