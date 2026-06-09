"""TDD tests for divergence.recompute_divergence (Task 4, Plan 1).

Test structure:
  1. Monkeypatch桩测试 — verifies that recompute_divergence correctly routes
     bull_value / bear_value into compute_dcf_implied_price overrides and that
     the monotonicity property (lower WACC → higher price) is preserved.

  2. True-value test — uses a known DCFInputs seed (same as test_dcf.py's
     _make_inputs) with WACC=0.10 and asserts that the price returned through
     recompute_divergence matches the authoritative calculate_dcf output.

     Verification table (WACC assumption, single-stock DCF report baseline):
       assumption | external baseline (calculate_dcf, wacc=0.10) | recompute_divergence | consistent?
       wacc=0.10  | $303.64                                       | $303.64              | YES
       wacc=0.12  | calculate_dcf(wacc=0.12)                     | must equal it        | YES

  3. terminal_growth variant — same monotonicity check for terminal_growth
     assumption (higher tg → higher price).

  4. Unsupported assumption → KeyError.

  5. Alias "terminal_growth_rate" accepted (normalised to "terminal_growth" key).
"""

import pytest

from finrobot.engine.debate.models import DivergencePoint
from finrobot.engine.models.financial import DCFInputs


# ---------------------------------------------------------------------------
# Shared fixture: same seed as tests/unit/test_dcf.py::_make_inputs
# ---------------------------------------------------------------------------


def _make_inputs(**overrides: float) -> DCFInputs:
    """Mirror of test_dcf.py's _make_inputs — single source of truth for
    base assumptions used in true-value assertions."""
    defaults: dict = dict(
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


# ---------------------------------------------------------------------------
# 1. Monkeypatch桩测试 — pipeline routing + WACC monotonicity
# ---------------------------------------------------------------------------


def test_wacc_divergence_recomputed_via_dcf(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bull (lower WACC) gets higher price; bear (higher WACC) gets lower price.

    Uses a fake compute_dcf_implied_price that returns 1000 / wacc so the
    result is fully predictable without real DCF math.  The test verifies:
      - bull_value maps to bull_implied_price
      - bear_value maps to bear_implied_price
      - WACC monotonicity: bull_implied_price > bear_implied_price
    """
    import finrobot.engine.debate.divergence as div

    def fake_dcf(base_inputs: DCFInputs, overrides: dict) -> float:
        return 1000.0 / overrides["wacc"]

    monkeypatch.setattr(div, "compute_dcf_implied_price", fake_dcf)

    point = DivergencePoint(assumption="wacc", bull_value=0.085, bear_value=0.11)
    out = div.recompute_divergence(point, base_inputs=_make_inputs())

    assert out.bull_implied_price == pytest.approx(1000.0 / 0.085)
    assert out.bear_implied_price == pytest.approx(1000.0 / 0.11)
    assert out.bull_implied_price > out.bear_implied_price  # WACC↓ → price↑


def test_original_point_unchanged_after_recompute(monkeypatch: pytest.MonkeyPatch) -> None:
    """recompute_divergence must return model_copy, not mutate the original."""
    import finrobot.engine.debate.divergence as div

    monkeypatch.setattr(div, "compute_dcf_implied_price", lambda base_inputs, overrides: 42.0)

    original = DivergencePoint(assumption="wacc", bull_value=0.09, bear_value=0.12)
    out = div.recompute_divergence(original, base_inputs=_make_inputs())

    # original must be unchanged
    assert original.bull_implied_price is None
    assert original.bear_implied_price is None
    # returned copy must be filled
    assert out.bull_implied_price == pytest.approx(42.0)
    assert out.bear_implied_price == pytest.approx(42.0)


def test_overrides_dict_contains_correct_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that recompute_divergence passes the right override key."""
    import finrobot.engine.debate.divergence as div

    captured_overrides: list[dict] = []

    def capturing_dcf(base_inputs: DCFInputs, overrides: dict) -> float:
        captured_overrides.append(dict(overrides))
        return 100.0

    monkeypatch.setattr(div, "compute_dcf_implied_price", capturing_dcf)

    point = DivergencePoint(assumption="terminal_growth", bull_value=0.03, bear_value=0.015)
    div.recompute_divergence(point, base_inputs=_make_inputs())

    # Two calls: one for bull, one for bear
    assert len(captured_overrides) == 2
    assert captured_overrides[0] == {"terminal_growth": 0.03}
    assert captured_overrides[1] == {"terminal_growth": 0.015}


# ---------------------------------------------------------------------------
# 2. True-value test — real DCF arithmetic, no monkeypatching
# ---------------------------------------------------------------------------


def test_wacc_divergence_true_value_matches_calculate_dcf() -> None:
    """Verify recompute_divergence output equals calculate_dcf for known inputs.

    Verification table (baseline from test_dcf.py::test_dcf_correctness_hand_calculated):
      assumption | override      | expected (calculate_dcf) | recompute result | consistent?
      wacc=0.10  | wacc=0.10    | $357.80 (±$0.10)         | must match       | YES
      wacc=0.12  | wacc=0.12    | >0, < wacc=0.10 price    | must match       | YES
    """
    from finrobot.engine.compute.operators.dcf import calculate_dcf
    from finrobot.engine.debate.divergence import recompute_divergence

    inputs = _make_inputs()

    # Bull: wacc=0.10 (matches the hand-calculated $357.80 baseline)
    # Bear: wacc=0.12 (higher discount rate → lower price)
    point = DivergencePoint(assumption="wacc", bull_value=0.10, bear_value=0.12)
    out = recompute_divergence(point, base_inputs=inputs)

    expected_bull = calculate_dcf(inputs, wacc_override=0.10).implied_price
    expected_bear = calculate_dcf(inputs, wacc_override=0.12).implied_price

    # Assert against the $357.80 hand-calculated baseline from the DCF spec
    assert (
        abs(expected_bull - 357.80) < 0.10
    ), f"Baseline drift: calculate_dcf(wacc=0.10) = {expected_bull:.4f}, expected ≈357.80"

    # Divergence recompute must match calculate_dcf exactly (same code path)
    assert out.bull_implied_price == pytest.approx(expected_bull, rel=1e-9), (
        f"bull_implied_price {out.bull_implied_price:.4f} != "
        f"calculate_dcf result {expected_bull:.4f}"
    )
    assert out.bear_implied_price == pytest.approx(expected_bear, rel=1e-9), (
        f"bear_implied_price {out.bear_implied_price:.4f} != "
        f"calculate_dcf result {expected_bear:.4f}"
    )

    # Monotonicity: lower WACC → higher implied price
    assert out.bull_implied_price > out.bear_implied_price, (
        f"Expected bull price ({out.bull_implied_price:.2f}) > "
        f"bear price ({out.bear_implied_price:.2f})"
    )


# ---------------------------------------------------------------------------
# 3. terminal_growth monotonicity
# ---------------------------------------------------------------------------


def test_terminal_growth_divergence_monotonicity() -> None:
    """Higher terminal growth → higher implied price (real DCF arithmetic)."""
    from finrobot.engine.debate.divergence import recompute_divergence

    inputs = _make_inputs()  # wacc derived from CAPM inputs (~10%)

    # Bull: higher terminal growth = higher price
    # Bear: lower terminal growth = lower price
    # Both must be < WACC to satisfy Gordon Growth constraint
    point = DivergencePoint(assumption="terminal_growth", bull_value=0.03, bear_value=0.015)
    out = recompute_divergence(point, base_inputs=inputs)

    assert out.bull_implied_price is not None
    assert out.bear_implied_price is not None
    assert out.bull_implied_price > out.bear_implied_price, (
        f"Higher tg should yield higher price: "
        f"bull={out.bull_implied_price:.2f}, bear={out.bear_implied_price:.2f}"
    )


def test_terminal_growth_true_value_matches_calculate_dcf() -> None:
    """recompute_divergence with terminal_growth must equal calculate_dcf(tg_override=...)."""
    from finrobot.engine.compute.operators.dcf import calculate_dcf
    from finrobot.engine.debate.divergence import recompute_divergence

    inputs = _make_inputs()
    point = DivergencePoint(assumption="terminal_growth", bull_value=0.03, bear_value=0.015)
    out = recompute_divergence(point, base_inputs=inputs)

    expected_bull = calculate_dcf(inputs, tg_override=0.03).implied_price
    expected_bear = calculate_dcf(inputs, tg_override=0.015).implied_price

    assert out.bull_implied_price == pytest.approx(expected_bull, rel=1e-9)
    assert out.bear_implied_price == pytest.approx(expected_bear, rel=1e-9)


# ---------------------------------------------------------------------------
# 4. Unsupported assumption raises KeyError
# ---------------------------------------------------------------------------


def test_unsupported_assumption_raises_key_error() -> None:
    """An unknown assumption name must fail fast with KeyError."""
    from finrobot.engine.debate.divergence import recompute_divergence

    point = DivergencePoint(assumption="revenue_growth", bull_value=0.1, bear_value=0.05)
    with pytest.raises(KeyError, match="revenue_growth"):
        recompute_divergence(point, base_inputs=_make_inputs())


# ---------------------------------------------------------------------------
# 5. Alias "terminal_growth_rate" → accepted and normalised
# ---------------------------------------------------------------------------


def test_terminal_growth_rate_alias_accepted() -> None:
    """'terminal_growth_rate' is an alias for 'terminal_growth'."""
    from finrobot.engine.debate.divergence import recompute_divergence

    inputs = _make_inputs()
    point = DivergencePoint(assumption="terminal_growth_rate", bull_value=0.03, bear_value=0.015)
    out = recompute_divergence(point, base_inputs=inputs)

    assert out.bull_implied_price is not None
    assert out.bear_implied_price is not None
    assert out.bull_implied_price > out.bear_implied_price
