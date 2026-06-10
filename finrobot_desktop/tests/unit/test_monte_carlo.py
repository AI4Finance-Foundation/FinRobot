from __future__ import annotations

import numpy as np
import pytest

from finrobot.engine.compute.operators.dcf import calculate_dcf
from finrobot.engine.compute.operators.monte_carlo import (
    MonteCarloRequest,
    _bounded_perturb,
    _percentile_rank,
    deterministic_seed,
    run_monte_carlo,
)
from finrobot.engine.models.financial import DCFInputs


def _inputs() -> DCFInputs:
    return DCFInputs(
        revenue_base=400_000_000_000.0,
        revenue_growth_rates=[0.06, 0.05, 0.04, 0.04, 0.03],
        ebitda_margin=0.30,
        capex_pct_revenue=0.06,
        nwc_pct_revenue=0.02,
        da_pct_revenue=0.05,
        tax_rate=0.21,
        risk_free_rate=0.04,
        beta=1.2,
        equity_risk_premium=0.05,
        cost_of_debt=0.04,
        debt_ratio=0.25,
        terminal_growth_rate=0.025,
        shares_outstanding=15_500_000_000.0,
        net_debt=60_000_000_000.0,
    )


def test_monte_carlo_request_rejects_odd_simulation_count() -> None:
    with pytest.raises(ValueError, match="even"):
        MonteCarloRequest(inputs=_inputs(), current_price=160.0, n_simulations=101)


def test_run_monte_carlo_rejects_odd_simulation_count() -> None:
    with pytest.raises(ValueError, match="even"):
        run_monte_carlo(_inputs(), current_price=160.0, n_simulations=101, seed=1)


def test_run_monte_carlo_preserves_even_simulation_count_assumption() -> None:
    result = run_monte_carlo(_inputs(), current_price=160.0, n_simulations=100, seed=1)

    assert result.assumptions_used["n_simulations"] == 100
    assert result.n_valid <= 100


@pytest.mark.parametrize("mid_year", [False, True])
def test_perturbation_zero_mc_equals_deterministic_dcf(mid_year: bool) -> None:
    """Equivalence gate: MC and calculate_dcf must speak the SAME terminal
    economics (dcf._terminal_fcf's capex→D&A normalization).

    With every perturbation std at 0 each simulated path is the base case, so
    the whole distribution must collapse onto calculate_dcf's implied price.
    The fixture is deliberately capex-heavy (capex 6% vs D&A 5% of revenue):
    the pre-fix MC capitalized the LAST EXPLICIT-YEAR FCF (full growth-phase
    capex) into the perpetuity, which pinned the distribution ~26% below the
    deterministic DCF chapter of the same report.
    """
    inputs = _inputs()
    deterministic = calculate_dcf(inputs, mid_year=mid_year).implied_price

    result = run_monte_carlo(
        inputs,
        current_price=160.0,
        n_simulations=200,
        revenue_growth_std=0.0,
        ebitda_margin_std=0.0,
        wacc_std=0.0,
        terminal_growth_std=0.0,
        seed=42,
        mid_year=mid_year,
    )

    expected = round(deterministic, 2)
    assert result.percentiles["5"] == pytest.approx(expected, abs=0.01)
    assert result.percentiles["50"] == pytest.approx(expected, abs=0.01)
    assert result.percentiles["95"] == pytest.approx(expected, abs=0.01)
    assert result.mean == pytest.approx(expected, abs=0.01)
    # All noise sources (including beta, which scales with wacc_std) are off,
    # so the distribution must be a degenerate point.
    assert result.std == pytest.approx(0.0, abs=0.01)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        # All legal DCFInputs values (rfr ge=0, tgr ge=0, beta ge=0) that sit
        # BELOW the MC domain floors (0.005 / 0.005 / 0.3). The old one-sided
        # np.maximum silently rewrote the base even at std=0 — probe measured
        # MC P50 drifting -4.9% (rfr 0.3%, zero-rate regimes), +2.0% (tgr
        # 0.3%) and -15.9% (beta 0.2, low-beta utility) against calculate_dcf
        # in the SAME report.
        ("risk_free_rate", 0.003),
        ("terminal_growth_rate", 0.003),
        ("beta", 0.2),
    ],
)
def test_below_floor_base_with_zero_std_still_equals_deterministic_dcf(
    field: str, value: float
) -> None:
    inputs = _inputs().model_copy(update={field: value})
    deterministic = round(calculate_dcf(inputs).implied_price, 2)

    result = run_monte_carlo(
        inputs,
        current_price=160.0,
        n_simulations=200,
        revenue_growth_std=0.0,
        ebitda_margin_std=0.0,
        wacc_std=0.0,
        terminal_growth_std=0.0,
        seed=42,
    )

    assert result.percentiles["50"] == pytest.approx(deterministic, abs=0.01)
    assert result.std == pytest.approx(0.0, abs=0.01)


class TestBoundedPerturb:
    """Antithetic symmetry of the domain floor (Glasserman Ch.4: the pairing
    only cancels noise if +Z and -Z are treated symmetrically). A one-sided
    np.maximum(floor, base + noise) truncated only the lower tail: probe
    measured E[tgr] = 1.198% for base 1.0%, std 1.0% — a +20% relative
    upward bias injected into every Gordon terminal value."""

    def test_pairs_mirror_exactly_around_base(self) -> None:
        noise = np.array([0.004, 0.02, -0.02, 0.0007])
        up = _bounded_perturb(0.01, noise, 0.005)
        down = _bounded_perturb(0.01, -noise, 0.005)
        # Each (Z, -Z) pair averages to the base exactly — zero input bias.
        np.testing.assert_allclose((up + down) / 2, 0.01, rtol=0, atol=1e-15)

    def test_mean_is_exactly_unbiased_under_gaussian_noise(self) -> None:
        rng = np.random.default_rng(0)
        z = rng.normal(0, 0.01, 100_000)
        noise = np.concatenate([z, -z])
        out = _bounded_perturb(0.01, noise, 0.005)
        assert float(out.mean()) == pytest.approx(0.01, abs=1e-12)

    def test_floor_still_enforced(self) -> None:
        noise = np.array([-1.0, 1.0])
        out = _bounded_perturb(0.01, noise, 0.005)
        assert out.min() >= 0.005
        # Symmetric cap: the upper bound mirrors the floor around the base.
        assert out.max() <= 0.015

    def test_base_at_or_below_floor_collapses_to_base(self) -> None:
        noise = np.array([-0.01, 0.0, 0.01])
        np.testing.assert_allclose(_bounded_perturb(0.005, noise, 0.005), 0.005)
        # A base below the floor is a legal model input (e.g. rfr=0.3%) —
        # honour it as given, exactly like calculate_dcf does.
        np.testing.assert_allclose(_bounded_perturb(0.003, noise, 0.005), 0.003)


class TestPercentileRank:
    """Midpoint tie convention — scipy.stats.percentileofscore(kind='mean').
    side='right' alone counted ties as 'below', reporting 100% (or 0% after
    rounding skew) when the current price sits exactly ON a degenerate
    distribution; the honest answer is 50%."""

    def test_ties_count_half(self) -> None:
        prices = np.array([1.0, 2.0, 2.0, 3.0])
        assert _percentile_rank(prices, 2.0) == pytest.approx(50.0)

    def test_degenerate_distribution_reads_fifty(self) -> None:
        prices = np.full(200, 82.83)
        assert _percentile_rank(prices, 82.83) == pytest.approx(50.0)

    def test_extremes(self) -> None:
        prices = np.array([10.0, 20.0, 30.0])
        assert _percentile_rank(prices, 5.0) == pytest.approx(0.0)
        assert _percentile_rank(prices, 35.0) == pytest.approx(100.0)

    def test_continuous_case_unchanged(self) -> None:
        # No ties → identical to the old side='right' count.
        prices = np.array([10.0, 20.0, 30.0, 40.0])
        assert _percentile_rank(prices, 25.0) == pytest.approx(50.0)

    def test_degenerate_run_reads_fifty_end_to_end(self) -> None:
        # All stds → 0 collapses the distribution onto calculate_dcf's price;
        # a current price equal to it (at the published 2-decimal precision)
        # must read "50th percentile", not 0/100 by rounding skew.
        inputs = _inputs()
        point = round(calculate_dcf(inputs).implied_price, 2)
        result = run_monte_carlo(
            inputs,
            current_price=point,
            n_simulations=200,
            revenue_growth_std=0.0,
            ebitda_margin_std=0.0,
            wacc_std=0.0,
            terminal_growth_std=0.0,
            seed=42,
        )
        assert result.current_price_percentile == pytest.approx(50.0)


def test_non_positive_terminal_fcf_paths_are_dropped() -> None:
    """calculate_dcf raises when the steady-state terminal FCF is <= 0
    (BUG-074: a trough must not be capitalized into a perpetual negative).
    The vectorized analogue drops those paths as invalid simulations instead
    of shipping a nonsense distribution."""
    sick = _inputs().model_copy(update={"ebitda_margin": 0.04})

    with pytest.raises(ValueError, match="positive simulations"):
        run_monte_carlo(sick, current_price=160.0, n_simulations=200, seed=7)


def test_same_seed_reproduces_bit_identical_result() -> None:
    """Reproducibility contract: production call sites pass a deterministic
    seed (crc32 of ticker + UTC day), so rerunning the same report the same
    day must reproduce the distribution bit for bit — every percentile, every
    histogram count, every price."""
    a = run_monte_carlo(_inputs(), current_price=160.0, n_simulations=2_000, seed=12345)
    b = run_monte_carlo(_inputs(), current_price=160.0, n_simulations=2_000, seed=12345)

    assert a.implied_prices == b.implied_prices
    assert a.percentiles == b.percentiles
    assert a.histogram_bins == b.histogram_bins
    assert a.histogram_counts == b.histogram_counts
    assert a.mean == b.mean
    assert a.std == b.std
    assert a.current_price_percentile == b.current_price_percentile


def test_assumptions_used_records_seed_for_provenance() -> None:
    seeded = run_monte_carlo(_inputs(), current_price=160.0, n_simulations=200, seed=99)
    unseeded = run_monte_carlo(_inputs(), current_price=160.0, n_simulations=200)

    assert seeded.assumptions_used["seed"] == 99
    assert unseeded.assumptions_used["seed"] is None


def test_deterministic_seed_is_stable_per_ticker_and_day() -> None:
    assert deterministic_seed("AAPL", as_of="2026-06-10") == deterministic_seed(
        "AAPL", as_of="2026-06-10"
    )
    assert deterministic_seed("AAPL", as_of="2026-06-10") != deterministic_seed(
        "MSFT", as_of="2026-06-10"
    )
    assert deterministic_seed("AAPL", as_of="2026-06-10") != deterministic_seed(
        "AAPL", as_of="2026-06-11"
    )


def test_monte_carlo_request_accepts_seed_field() -> None:
    request = MonteCarloRequest(inputs=_inputs(), current_price=160.0, seed=7)
    assert request.seed == 7
    assert MonteCarloRequest(inputs=_inputs(), current_price=160.0).seed is None
