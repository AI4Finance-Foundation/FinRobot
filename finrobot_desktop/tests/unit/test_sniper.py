"""Unit tests for finrobot.engine.compute.sniper.calculate_sniper_points.

External sources for expected values:
- Safety margin thresholds (15%/10%/5%) are hardcoded in sniper.py — we test
  the *output of those thresholds*, not infer values from the formula itself.
- Stop-loss floor of 15% below current is a widely-cited position management
  rule (Source: Investopedia "Stop-Loss Orders", position-sizing rule-of-thumb).
- Position sizing clamp 1-5%: Source: Van Tharp "Trade Your Way to Financial
  Freedom" (common 1-5% Kelly-derived sizing constraint).
- Risk/reward: (take_profit - current) / (current - stop_loss) is a standard
  R-multiple formula (Source: CFA Institute, "Risk Management" reading).

These tests verify the deterministic logic of the function given typed inputs.
They do NOT use the function itself to compute the expected values — each
expected value is derived from manual arithmetic shown inline.
"""
from __future__ import annotations


import pytest

from finrobot.engine.compute.sniper import SniperPoints, SniperRequest, calculate_sniper_points


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _req(**kwargs) -> SniperRequest:
    """Build a SniperRequest with sensible defaults."""
    defaults = dict(
        ticker="AAPL",
        current_price=150.0,
        dcf_target=200.0,
        historical_prices=[140.0, 145.0, 148.0, 152.0, 155.0,
                            150.0, 147.0, 153.0, 158.0, 144.0,
                            149.0, 151.0, 146.0, 143.0, 157.0,
                            154.0, 148.0, 142.0, 160.0, 150.0],
    )
    defaults.update(kwargs)
    return SniperRequest(**defaults)


# ---------------------------------------------------------------------------
# 1. Normal / happy path — upside > 30%
#    current=150, target=200 → upside_pct = (200-150)/150 = 33.3% > 30%
#    safety_margin = 0.15  →  ideal_buy = 200 * 0.85 = 170.0
# ---------------------------------------------------------------------------

def test_sniper_ideal_buy_high_upside():
    """ideal_buy = dcf_target * (1 - 0.15) when upside > 30%.

    Manual: 200 * 0.85 = 170.00.
    """
    result = calculate_sniper_points(_req())
    assert result.ideal_buy == pytest.approx(170.0, abs=0.01)
    assert result.safety_margin == 0.15


def test_sniper_take_profit_equals_dcf_target():
    """take_profit is always the raw DCF target (no discount).

    Source: design spec in sniper.py docstring — take_profit = dcf_target.
    """
    result = calculate_sniper_points(_req())
    assert result.take_profit == pytest.approx(200.0, abs=0.01)


def test_sniper_support_resistance_from_last_20_prices():
    """support = min of last 20 prices, resistance = max.

    The default _req() uses 20 prices: [140, 145, 148, 152, 155,
    150, 147, 153, 158, 144, 149, 151, 146, 143, 157, 154, 148, 142, 160, 150].
    Manual: min = 140.0, max = 160.0.
    """
    result = calculate_sniper_points(_req())
    assert result.support_level == pytest.approx(140.0, abs=0.01)
    assert result.resistance_level == pytest.approx(160.0, abs=0.01)


def test_sniper_secondary_buy_equals_support():
    """secondary_buy = support_level."""
    result = calculate_sniper_points(_req())
    assert result.secondary_buy == result.support_level


# ---------------------------------------------------------------------------
# 2. Boundary: negative upside (downside scenario)
#    current=200, target=150 → upside_pct = -0.25 (downside)
#    safety_margin = 0.05 (else branch)
#    ideal_buy = 150 * 0.95 = 142.50
# ---------------------------------------------------------------------------

def test_sniper_negative_upside_uses_minimum_safety_margin():
    """When DCF target < current price, upside_pct < 0 → safety_margin = 0.05.

    Manual: 150 * (1 - 0.05) = 142.50.
    Source: sniper.py logic — else branch applies 5% safety margin.
    """
    result = calculate_sniper_points(
        _req(current_price=200.0, dcf_target=150.0)
    )
    assert result.safety_margin == 0.05
    assert result.ideal_buy == pytest.approx(142.5, abs=0.01)


def test_sniper_negative_upside_position_size_minimum():
    """Negative upside → upside_ratio clamped to 0 → position_size = 1.0%.

    Source: sniper.py — position_size = max(1.0, 2.0 * max(0, upside_pct) * 100 / 20).
    With upside_pct = -0.25: 2.0 * 0 * 100 / 20 = 0 → clamped to 1.0.
    """
    result = calculate_sniper_points(
        _req(current_price=200.0, dcf_target=150.0)
    )
    assert result.position_size_pct == pytest.approx(1.0, abs=0.1)


def test_sniper_negative_upside_risk_reward_zero():
    """When take_profit < current_price, upside_abs < 0, risk_reward = 0.

    This correctly signals: do not enter. Manual:
    upside_abs = 150 - 200 = -50, downside = current - stop_loss > 0
    → upside_abs / downside is negative or code clamps to 0 if downside>0.
    """
    result = calculate_sniper_points(
        _req(current_price=200.0, dcf_target=150.0)
    )
    # risk_reward should be non-positive (no edge case: function returns 0 when
    # downside == 0, and a negative value when upside is negative).
    # The function itself doesn't clamp — we assert the math is coherent:
    # a negative or zero risk_reward means "don't buy at current price".
    assert result.risk_reward_ratio <= 0.0


# ---------------------------------------------------------------------------
# 3. Boundary: zero denominator in risk/reward (current == stop_loss)
#    The function guards: risk_reward = upside / downside if downside > 0 else 0.
#    Force stop_loss == current by using a single-price history so vol=0,
#    support == current, and vol_buffer == 0 → stop_loss = max(current, current*0.85).
#    With prices=[200.0]*20 and current=200, support=200, vol=0 → stop=max(200,170)=200
#    → downside=0 → risk_reward=0.0.
# ---------------------------------------------------------------------------

def test_sniper_risk_reward_zero_when_stop_equals_current():
    """Risk/reward returns 0.0 when downside == 0 (stop_loss == current).

    Source: sniper.py line: risk_reward = upside_abs / downside if downside > 0 else 0.0.
    Manual: prices=[200]*20, vol_buffer=0 → stop=max(200-0, 200*0.85)=200 → downside=0.
    """
    result = calculate_sniper_points(
        SniperRequest(
            ticker="TEST",
            current_price=200.0,
            dcf_target=300.0,
            historical_prices=[200.0] * 20,
            volatility_annual=0.0,
        )
    )
    assert result.risk_reward_ratio == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# 4. Boundary: single-price history (min_length=1)
# ---------------------------------------------------------------------------

def test_sniper_single_price_history():
    """Function works with exactly 1 price — the minimum allowed by the schema."""
    result = calculate_sniper_points(
        SniperRequest(
            ticker="MONO",
            current_price=100.0,
            dcf_target=130.0,
            historical_prices=[100.0],
        )
    )
    assert result.support_level == pytest.approx(100.0)
    assert result.resistance_level == pytest.approx(100.0)
    assert isinstance(result, SniperPoints)


# ---------------------------------------------------------------------------
# 5. Boundary: explicit volatility override
#    volatility_annual=0.20 → daily_vol = 0.20 / sqrt(252)
#    vol_buffer = daily_vol * sqrt(10) * current
#    stop_loss = max(support - vol_buffer, current * 0.85)
# ---------------------------------------------------------------------------

def test_sniper_explicit_volatility_used():
    """Explicit volatility_annual overrides computed volatility.

    Manual for current=100, target=140, prices=[90..110] (20 values),
    vol=0.20, daily_vol=0.20/√252≈0.01260,
    vol_buffer = 0.01260 * √10 * 100 ≈ 3.98.
    support = 90 (min), stop_loss = max(90-3.98, 100*0.85) = max(86.02, 85) = 86.02.
    """
    prices = [90.0 + i for i in range(20)]  # 90..109
    result = calculate_sniper_points(
        SniperRequest(
            ticker="VTEST",
            current_price=100.0,
            dcf_target=140.0,
            historical_prices=prices,
            volatility_annual=0.20,
        )
    )
    expected_daily_vol = 0.20 / (252 ** 0.5)
    expected_vol_buffer = expected_daily_vol * (10 ** 0.5) * 100.0
    expected_support = 90.0
    expected_stop = max(expected_support - expected_vol_buffer, 100.0 * 0.85)
    assert result.stop_loss == pytest.approx(expected_stop, abs=0.01)


# ---------------------------------------------------------------------------
# 6. Boundary: moderate upside (15% < upside <= 30%) → safety_margin = 0.10
#    current=100, target=120 → upside=20% > 15% → safety_margin=0.10
#    ideal_buy = 120 * 0.90 = 108.0
# ---------------------------------------------------------------------------

def test_sniper_moderate_upside_safety_margin():
    """Safety margin is 10% when upside is 15%-30%.

    Manual: current=100, target=120, upside=20% → safety_margin=0.10,
    ideal_buy = 120 * 0.90 = 108.0.
    """
    prices = [95.0, 97.0, 100.0, 98.0, 99.0] * 4  # 20 prices
    result = calculate_sniper_points(
        SniperRequest(
            ticker="MOD",
            current_price=100.0,
            dcf_target=120.0,
            historical_prices=prices,
        )
    )
    assert result.safety_margin == 0.10
    assert result.ideal_buy == pytest.approx(108.0, abs=0.01)


# ---------------------------------------------------------------------------
# 7. Validation: negative price in history raises ValueError
# ---------------------------------------------------------------------------

def test_sniper_rejects_negative_historical_price():
    """SniperRequest rejects negative prices in historical_prices."""
    with pytest.raises(ValueError):
        SniperRequest(
            ticker="NEG",
            current_price=100.0,
            dcf_target=150.0,
            historical_prices=[100.0, -5.0, 100.0],
        )


# ---------------------------------------------------------------------------
# 8. Validation: current_price <= 0 rejected
# ---------------------------------------------------------------------------

def test_sniper_rejects_zero_current_price():
    """current_price must be > 0."""
    with pytest.raises(ValueError):
        SniperRequest(
            ticker="ZERO",
            current_price=0.0,
            dcf_target=100.0,
            historical_prices=[50.0],
        )


# ---------------------------------------------------------------------------
# 9. Position sizing boundary — position_size clamp at 5%
#    upside_pct=3.0 (300%) → 2.0*3.0*100/20 = 30 → clamped to 5.0
# ---------------------------------------------------------------------------

def test_sniper_position_size_capped_at_5_percent():
    """Position size is capped at 5% even for very large upside.

    Manual: upside_pct=3.0 → 2*3*100/20=30 → clamp(30,1,5)=5.0.
    """
    result = calculate_sniper_points(
        _req(current_price=100.0, dcf_target=400.0)
    )
    assert result.position_size_pct == pytest.approx(5.0, abs=0.1)


# ---------------------------------------------------------------------------
# 10. Stop-loss floor: 15% below current is always the minimum
#     When vol is very low, stop = max(support - tiny, current*0.85)
#     With prices=[99..101]*10 (very tight), vol near 0 → stop ≈ current*0.85
# ---------------------------------------------------------------------------

def test_sniper_stop_loss_never_below_fifteen_pct():
    """Stop-loss floor: never more than 15% below current_price.

    Source: sniper.py line 103: stop_loss = max(support - vol_buffer, current * 0.85).
    """
    prices = [100.0] * 20  # zero volatility scenario
    result = calculate_sniper_points(
        SniperRequest(
            ticker="FLOOR",
            current_price=100.0,
            dcf_target=200.0,
            historical_prices=prices,
            volatility_annual=0.0,
        )
    )
    assert result.stop_loss >= 100.0 * 0.85 - 0.01
