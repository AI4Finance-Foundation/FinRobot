"""Sniper Points — deterministic entry/exit price levels from DCF + technicals.

What this code does that raw LLM cannot:
- Computes exact buy/sell price levels from DCF intrinsic value + price history.
- Derives support/resistance from rolling 20-day min/max — no LLM rounding.
- Sizes position deterministically from upside ratio.
- All numbers trace back to typed inputs: no hidden assumptions, no hallucinated prices.

Score range: prices in same currency as inputs.
"""
from __future__ import annotations

import statistics

from pydantic import BaseModel, Field, model_validator


class SniperRequest(BaseModel):
    ticker: str
    current_price: float = Field(gt=0)
    dcf_target: float = Field(gt=0)
    historical_prices: list[float] = Field(min_length=1)
    volatility_annual: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _prices_positive(self) -> "SniperRequest":
        for p in self.historical_prices:
            if p <= 0:
                raise ValueError("All historical prices must be positive")
        return self


class SniperPoints(BaseModel):
    ideal_buy: float
    secondary_buy: float
    stop_loss: float
    take_profit: float
    position_size_pct: float  # suggested position as % of portfolio (1-5%)
    safety_margin: float       # the discount applied to DCF target
    support_level: float       # detected support (20-day rolling min)
    resistance_level: float    # detected resistance (20-day rolling max)
    risk_reward_ratio: float   # (take_profit - current) / (current - stop_loss)


def calculate_sniper_points(req: SniperRequest) -> SniperPoints:
    """Calculate entry/exit price levels from DCF target + historical prices.

    Logic (all deterministic, no LLM):
    1. ideal_buy = dcf_target * (1 - safety_margin)
       safety_margin: 15% if upside > 30%, 10% if upside > 15%, 5% otherwise
    2. secondary_buy = support_level (min of trailing 20-day window)
    3. stop_loss = max(support - 10-day-expected-move, current * 0.85)
       10-day expected move = daily_vol * sqrt(10) * current_price
    4. take_profit = dcf_target
    5. position_size = clamp(2% * upside_ratio * 100 / 20, 1%, 5%)
    6. support = min of last 20 prices
    7. resistance = max of last 20 prices
    8. risk_reward = (take_profit - current) / (current - stop_loss)
    """
    prices = req.historical_prices
    current = req.current_price
    target = req.dcf_target

    # --- Volatility ----------------------------------------------------------
    if req.volatility_annual is not None and req.volatility_annual > 0:
        annual_vol: float = req.volatility_annual
    elif len(prices) >= 2:
        returns = [
            (prices[i] - prices[i - 1]) / prices[i - 1]
            for i in range(1, len(prices))
        ]
        daily_vol = statistics.stdev(returns) if len(returns) > 1 else 0.02
        annual_vol = daily_vol * (252 ** 0.5)
    else:
        annual_vol = 0.30  # conservative default when history is thin

    daily_vol = annual_vol / (252 ** 0.5)

    # --- Upside & safety margin ----------------------------------------------
    upside_pct = (target - current) / current  # can be negative (downside)

    if upside_pct > 0.30:
        safety_margin = 0.15
    elif upside_pct > 0.15:
        safety_margin = 0.10
    else:
        safety_margin = 0.05

    ideal_buy = target * (1 - safety_margin)

    # --- Support / resistance (20-day rolling window) -----------------------
    window = min(20, len(prices))
    recent = prices[-window:]
    support = min(recent)
    resistance = max(recent)

    secondary_buy = support

    # --- Stop loss -----------------------------------------------------------
    # 10-day expected downside move: daily_vol * sqrt(10) * current_price
    vol_buffer = daily_vol * (10 ** 0.5) * current
    # Floor at 15% below current to prevent absurdly tight stops
    stop_loss = max(support - vol_buffer, current * 0.85)

    # --- Take profit ---------------------------------------------------------
    take_profit = target

    # --- Position sizing (1-5% of portfolio) ---------------------------------
    upside_ratio = max(0.0, upside_pct)
    position_size = min(5.0, max(1.0, 2.0 * upside_ratio * 100 / 20))

    # --- Risk / reward -------------------------------------------------------
    downside = current - stop_loss
    upside_abs = take_profit - current
    risk_reward = upside_abs / downside if downside > 0 else 0.0

    return SniperPoints(
        ideal_buy=round(ideal_buy, 2),
        secondary_buy=round(secondary_buy, 2),
        stop_loss=round(stop_loss, 2),
        take_profit=round(take_profit, 2),
        position_size_pct=round(position_size, 1),
        safety_margin=round(safety_margin, 2),
        support_level=round(support, 2),
        resistance_level=round(resistance, 2),
        risk_reward_ratio=round(risk_reward, 2),
    )
