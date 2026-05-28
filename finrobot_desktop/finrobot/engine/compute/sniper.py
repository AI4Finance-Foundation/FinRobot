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
    # ``ideal_buy`` / ``secondary_buy`` are entries; in SHORT mode they are
    # the *short-entry* levels (open the short here / add here on bounce).
    # Always interpret these together with ``direction`` — never assume LONG.
    ideal_buy: float
    secondary_buy: float
    stop_loss: float
    take_profit: float
    position_size_pct: float  # suggested position as % of portfolio (1-5%)
    safety_margin: float  # the discount applied to DCF target
    support_level: float  # detected support (20-day rolling min)
    resistance_level: float  # detected resistance (20-day rolling max)
    risk_reward_ratio: float  # |take_profit - current| / |stop_loss - current|
    sell_mode: bool = False  # True when DCF intrinsic < current price
    # "LONG" | "SHORT" — drives the rendering layer's labels and the
    # invariant gate. SELL-rated artifacts used to ship LONG-flavoured
    # field semantics with ``stop_loss`` ($484.40) sitting ABOVE the
    # ``ideal_buy`` ($372.80), giving a risk/reward of 0.11 that read
    # as a nonsensical long trade. Direction makes the SHORT semantics
    # explicit and lets the UI swap labels (开空 / 止盈下方 / 止损上方).
    direction: str = "LONG"
    invariant_warnings: list[str] = Field(default_factory=list)


def calculate_sniper_points(req: SniperRequest) -> SniperPoints:
    """Calculate entry/exit price levels from DCF target + historical prices.

    LONG mode (target >= current):
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

    SELL mode (target < current — stock is overvalued vs DCF):
    - Anchors flip to technical levels rather than DCF intrinsic.
    - ideal_buy = support_level ("if it drops to support, consider entry")
    - take_profit = resistance_level (short-term bounce target from a long entry)
    - stop_loss = current * 1.10 (multi-trend stop above current for a long)
    - risk_reward = (take_profit - current) / (stop_loss - current)
    - invariant_warnings carries the diagnostic explaining the mode switch.
    """
    prices = req.historical_prices
    current = req.current_price
    target = req.dcf_target

    # --- Volatility ----------------------------------------------------------
    if req.volatility_annual is not None and req.volatility_annual > 0:
        annual_vol: float = req.volatility_annual
    elif len(prices) >= 2:
        returns = [(prices[i] - prices[i - 1]) / prices[i - 1] for i in range(1, len(prices))]
        daily_vol = statistics.stdev(returns) if len(returns) > 1 else 0.02
        annual_vol = daily_vol * (252**0.5)
    else:
        annual_vol = 0.30  # conservative default when history is thin

    daily_vol = annual_vol / (252**0.5)

    # --- Support / resistance (20-day rolling window) -----------------------
    window = min(20, len(prices))
    recent = prices[-window:]
    support = min(recent)
    resistance = max(recent)

    invariant_warnings: list[str] = []
    sell_mode = target < current

    if sell_mode:
        # ------------------------------------------------------------------ #
        # SHORT mode                                                          #
        # DCF intrinsic is below current → the trade thesis is a short.       #
        # Field semantics flip: ideal_buy / secondary_buy are SHORT entries,  #
        # take_profit sits BELOW current (cover at DCF or at support),        #
        # stop_loss sits ABOVE current (trend-reversal stop). Invariant:      #
        # take_profit < ideal_buy <= stop_loss. The pre-fix code anchored     #
        # all three levels around technical bounces of a hypothetical long,   #
        # producing displays like ``buy 372.80 / stop 484.40 / R/R 0.11`` —   #
        # incoherent against a SELL rating (sniper.py L94-120, audit          #
        # 2026-05-28).                                                        #
        # ------------------------------------------------------------------ #
        direction = "SHORT"
        # Short entry: current price (open now) and resistance (add on bounce).
        ideal_buy = current
        secondary_buy = max(resistance, current)
        # Cover target: prefer DCF (the thesis) over technical support so we
        # capture the full bear case; never go below support (avoids
        # over-projection past validated demand).
        take_profit = max(target, support)
        # Trend-reversal stop ABOVE current: take whichever is higher of
        # resistance and a 10% cushion so the stop never sits inside the
        # 20-day range.
        stop_loss = max(resistance, current * 1.10)
        safety_margin = 0.0  # not applicable on a short

        upside_abs = current - take_profit  # positive when target < current
        downside = stop_loss - current  # positive by construction
        risk_reward = upside_abs / downside if downside > 0 else 0.0

        position_size = 1.0  # minimum sizing — high uncertainty trade

        invariant_warnings.append(
            f"DCF intrinsic ${target:.2f} < current ${current:.2f}: SHORT trade. "
            f"entry=${ideal_buy:.2f}, cover=${take_profit:.2f}, "
            f"stop=${stop_loss:.2f}, R/R={risk_reward:.2f}."
        )

    else:
        # ------------------------------------------------------------------ #
        # LONG / undervalued mode                                             #
        # ------------------------------------------------------------------ #
        direction = "LONG"
        upside_pct = (target - current) / current  # positive

        if upside_pct > 0.30:
            safety_margin = 0.15
        elif upside_pct > 0.15:
            safety_margin = 0.10
        else:
            safety_margin = 0.05

        ideal_buy = target * (1 - safety_margin)
        secondary_buy = support

        # 10-day expected downside move: daily_vol * sqrt(10) * current_price
        vol_buffer = daily_vol * (10**0.5) * current
        # Floor at 15% below current to prevent absurdly tight stops
        stop_loss = max(support - vol_buffer, current * 0.85)

        take_profit = target

        upside_ratio = max(0.0, upside_pct)
        position_size = min(5.0, max(1.0, 2.0 * upside_ratio * 100 / 20))

        downside = current - stop_loss
        upside_abs = take_profit - current
        risk_reward = upside_abs / downside if downside > 0 else 0.0

    # --- Invariant guards ---------------------------------------------------
    # LONG  : stop_loss <  ideal_buy <  take_profit  (stop below, target above)
    # SHORT : take_profit <  ideal_buy <  stop_loss  (target below, stop above)
    # Anything else is incoherent and we refuse to ship the artifact rather
    # than let the UI render a phantom "buy at X / stop at Y where Y > X" row.
    if sell_mode:
        if take_profit > ideal_buy:
            raise ValueError(
                f"sniper invariant violated (SHORT): take_profit {take_profit:.2f} "
                f"> ideal_buy {ideal_buy:.2f}"
            )
        if stop_loss <= ideal_buy:
            raise ValueError(
                f"sniper invariant violated (SHORT): stop_loss {stop_loss:.2f} "
                f"<= ideal_buy {ideal_buy:.2f}"
            )
    else:
        if take_profit < ideal_buy:
            raise ValueError(
                f"sniper invariant violated (LONG): take_profit {take_profit:.2f} "
                f"< ideal_buy {ideal_buy:.2f}"
            )
        if stop_loss >= ideal_buy:
            raise ValueError(
                f"sniper invariant violated (LONG): stop_loss {stop_loss:.2f} "
                f">= ideal_buy {ideal_buy:.2f}"
            )

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
        sell_mode=sell_mode,
        direction=direction,
        invariant_warnings=invariant_warnings,
    )
