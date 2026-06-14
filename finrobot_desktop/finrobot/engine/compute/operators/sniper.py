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
import math

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
            if not math.isfinite(p) or p <= 0:
                raise ValueError("All historical prices must be finite and positive")
        return self


class SniperPoints(BaseModel):
    # ``ideal_buy`` / ``secondary_buy`` are entries; in SHORT mode they are
    # the *short-entry* levels (open the short here / add here on bounce).
    # Always interpret these together with ``direction`` — never assume LONG.
    #
    # NEUTRAL (levels-only) mode: when the upstream valuation synthesis honestly
    # withheld its POINT target (the only number available would be fabricated →
    # no publishable target), we MUST NOT anchor a directional trade to the
    # single non-defensible DCF leg. In that case every trade-level field below
    # is ``None`` and only ``support_level`` / ``resistance_level`` (pure price
    # facts, independent of the DCF) are populated. That's why the trade fields
    # are Optional — a directional LONG/SHORT always fills them, NEUTRAL never does.
    ideal_buy: float | None
    # Optional second entry level. ``None`` when no coherent secondary entry
    # exists — e.g. a LONG whose 20-day support sits below the stop_loss floor
    # (a recent crash low still in the trailing window): rendering a "buy" you
    # could only reach after being stopped out is incoherent, so we drop the
    # level and record the reason in ``invariant_warnings``.
    secondary_buy: float | None
    stop_loss: float | None
    take_profit: float | None
    position_size_pct: float | None  # suggested position as % of portfolio (1-5%)
    safety_margin: float | None  # the discount applied to DCF target
    support_level: float  # detected support (20-day rolling min)
    resistance_level: float  # detected resistance (20-day rolling max)
    risk_reward_ratio: float | None  # |take_profit - current| / |stop_loss - current|
    sell_mode: bool = False  # True when DCF intrinsic < current price
    # "LONG" | "SHORT" | "NEUTRAL" — drives the rendering layer's labels and the
    # invariant gate. For a SHORT, the fields invert (``stop_loss`` sits ABOVE
    # ``ideal_buy``, cover target below entry); making direction explicit lets the
    # UI swap labels (开空 / 止盈下方 / 止损上方) and keeps risk/reward meaningful
    # for a bear trade. NEUTRAL = no tradeable direction (point target withheld),
    # only support/resistance shown.
    direction: str = "LONG"
    invariant_warnings: list[str] = Field(default_factory=list)


def calculate_sniper_points(req: SniperRequest) -> SniperPoints:
    """Calculate entry/exit price levels from DCF target + historical prices.

    LONG mode (target >= current):
    1. ideal_buy = dcf_target * (1 - safety_margin)
       safety_margin: 15% if upside > 30%, 10% if upside > 15%, 5% otherwise
    2. secondary_buy = support_level (min of trailing 20-day window), or None
       when support sits at/below stop_loss (drop the incoherent second entry)
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

    # Reject a DCF target within one tick ($0.01) of the current price up front
    # (BUG-076). At sub-cent separation there is no directional thesis to trade:
    # every level rounds to current, R/R collapses to 0, and the SHORT branch
    # would emit a self-contradictory "DCF intrinsic $X < current $X" warning.
    # Mirror signal.py's "target == entry" rejection so _safe_sniper degrades to
    # None + warning instead of shipping a degenerate row.
    if abs(target - current) < 0.01:
        raise ValueError(
            f"DCF target ${target:.2f} within one tick of current ${current:.2f}: "
            "no directional thesis to snipe; refusing degenerate (R/R 0) levels."
        )

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
        bounce_entry = max(resistance, current)
        # Cover target = the DCF intrinsic value (the thesis): fair value sits at
        # ``target`` below the price, which is where the bear case plays out. Do NOT
        # clamp the cover up to the 20-day support — that throttles the short to the
        # nearest technical floor and, when support ≈ current (common for downtrending
        # SELLs), collapses to a degenerate "cover == entry, R/R 0" trade. ``support``
        # stays available as ``support_level`` for display context.
        take_profit = target
        # Trend-reversal stop ABOVE current: take whichever is higher of
        # resistance and a 10% cushion so the stop never sits inside the
        # 20-day range.
        stop_loss = max(resistance, current * 1.10)

        # Second short entry = add on a bounce toward resistance, and it must sit
        # strictly BELOW the trend-reversal stop. When resistance >= current*1.10
        # the stop pins to resistance too, so bounce_entry == stop_loss — an "add
        # at the very price that stops you out" (开仓即止损). Drop it to None +
        # record why, mirroring the LONG branch's support<=stop_loss guard (never
        # clamp onto the stop — that ships the degeneracy instead of disclosing it).
        secondary_buy: float | None
        if bounce_entry >= stop_loss:
            invariant_warnings.append(
                f"resistance ${resistance:.2f} at/above stop ${stop_loss:.2f}; "
                f"no secondary (bounce) entry."
            )
            secondary_buy = None
        else:
            secondary_buy = bounce_entry

        safety_margin = 0.0  # not applicable on a short

        upside_abs = current - take_profit  # positive when target < current
        downside = stop_loss - current  # positive by construction
        risk_reward = upside_abs / downside if downside > 0 else 0.0

        position_size = 1.0  # minimum sizing — high uncertainty trade

        # Build the diagnostic from the *shipped* (rounded) values so it never
        # contradicts the rendered levels (BUG-076): the gate below also operates
        # on the rounded values, so if any pair collapsed under rounding we raise
        # before this warning could mislead.
        invariant_warnings.append(
            f"DCF intrinsic ${round(target, 2):.2f} < current ${round(current, 2):.2f}: "
            f"SHORT trade. entry=${round(ideal_buy, 2):.2f}, "
            f"cover=${round(take_profit, 2):.2f}, stop=${round(stop_loss, 2):.2f}, "
            f"R/R={round(risk_reward, 2):.2f}."
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

        # 10-day expected downside move: daily_vol * sqrt(10) * current_price
        vol_buffer = daily_vol * (10**0.5) * current
        # Floor at 15% below current to prevent absurdly tight stops
        stop_loss = max(support - vol_buffer, current * 0.85)

        # Second entry = 20-day support. When a recent crash low still sits in
        # the trailing-20 window, support can fall BELOW the stop_loss floor —
        # a "buy" price you could only reach after already being stopped out.
        # Drop the secondary level rather than ship an incoherent ladder, and
        # record why. (Do NOT clamp secondary_buy=max(support, stop_loss): that
        # collapses the entry onto the stop — a degenerate entry==stop, the same
        # degeneracy the SHORT branch warns against.)
        if support <= stop_loss:
            secondary_buy = None
            invariant_warnings.append(
                f"20-day support ${support:.2f} below stop ${stop_loss:.2f}; no secondary entry."
            )
        else:
            secondary_buy = support

        take_profit = target

        upside_ratio = max(0.0, upside_pct)
        position_size = min(5.0, max(1.0, 2.0 * upside_ratio * 100 / 20))

        downside = current - stop_loss
        upside_abs = take_profit - current
        risk_reward = upside_abs / downside if downside > 0 else 0.0

    # --- Invariant guards (gate on the ROUNDED / shipped values) ------------
    # LONG  : stop_loss <  ideal_buy <  take_profit  (stop below, target above)
    # SHORT : take_profit <  ideal_buy <  stop_loss  (target below, stop above)
    # The SniperPoints we return round every level to 2 decimals. Comparing the
    # raw floats here but shipping the rounded ones (the pre-BUG-076 bug) let a
    # sub-cent gap pass the gate yet collapse under rounding — ideal_buy ==
    # take_profit, R/R 0, and a "$X < $X" warning. Gate on the rounded values so
    # any rounding-induced collapse (>= / <= now catches equality) raises here,
    # and _safe_sniper degrades to None + warning instead of shipping it.
    r_ideal_buy = round(ideal_buy, 2)
    r_stop_loss = round(stop_loss, 2)
    r_take_profit = round(take_profit, 2)
    r_secondary_buy = round(secondary_buy, 2) if secondary_buy is not None else None

    if sell_mode:
        if r_take_profit >= r_ideal_buy:
            raise ValueError(
                f"sniper invariant violated (SHORT): take_profit {r_take_profit:.2f} "
                f">= ideal_buy {r_ideal_buy:.2f} (degenerate after rounding)"
            )
        if r_stop_loss <= r_ideal_buy:
            raise ValueError(
                f"sniper invariant violated (SHORT): stop_loss {r_stop_loss:.2f} "
                f"<= ideal_buy {r_ideal_buy:.2f}"
            )
        # Secondary (bounce) entry must sit at/above the primary entry and
        # strictly BELOW the stop, or be absent. Mirror of the LONG check: the
        # SHORT branch drops the level to None when resistance breaches the stop,
        # so a present value here is always coherent (defense in depth).
        if r_secondary_buy is not None and not (r_ideal_buy <= r_secondary_buy < r_stop_loss):
            raise ValueError(
                f"sniper invariant violated (SHORT): secondary_buy {r_secondary_buy:.2f} "
                f"outside [ideal_buy {r_ideal_buy:.2f}, stop_loss {r_stop_loss:.2f})"
            )
    else:
        if r_take_profit <= r_ideal_buy:
            raise ValueError(
                f"sniper invariant violated (LONG): take_profit {r_take_profit:.2f} "
                f"<= ideal_buy {r_ideal_buy:.2f} (degenerate after rounding)"
            )
        if r_stop_loss >= r_ideal_buy:
            raise ValueError(
                f"sniper invariant violated (LONG): stop_loss {r_stop_loss:.2f} "
                f">= ideal_buy {r_ideal_buy:.2f}"
            )
        # Secondary entry must sit strictly above the stop and at/below the
        # target, or be absent. Guards against the incoherent "buy below stop"
        # ladder (BUG-042); the LONG branch drops the level to None when the
        # 20-day support breaches the stop floor, so a present value here is
        # always coherent.
        if r_secondary_buy is not None and not (r_stop_loss < r_secondary_buy <= r_take_profit):
            raise ValueError(
                f"sniper invariant violated (LONG): secondary_buy {r_secondary_buy:.2f} "
                f"outside (stop_loss {r_stop_loss:.2f}, take_profit {r_take_profit:.2f}]"
            )

    return SniperPoints(
        ideal_buy=r_ideal_buy,
        secondary_buy=r_secondary_buy,
        stop_loss=r_stop_loss,
        take_profit=r_take_profit,
        position_size_pct=round(position_size, 1),
        safety_margin=round(safety_margin, 2),
        support_level=round(support, 2),
        resistance_level=round(resistance, 2),
        risk_reward_ratio=round(risk_reward, 2),
        sell_mode=sell_mode,
        direction=direction,
        invariant_warnings=invariant_warnings,
    )


def calculate_sniper_levels_only(req: SniperRequest) -> SniperPoints:
    """Levels-only (NEUTRAL) sniper — support/resistance, NO directional trade.

    Used when the upstream valuation synthesis honestly withheld its POINT target
    (the only number available would be fabricated — methods agree far off-market,
    or a lone method way off-market), so there is no publishable target.
    Anchoring a LONG/SHORT to the single non-defensible DCF leg would directly
    contradict that withholding — exactly the internal inconsistency this gate
    exists to prevent.

    Support / resistance are pure price-history facts (20-day rolling min/max),
    independent of the DCF, so they remain honest to surface. Every trade-level
    field is ``None`` and ``direction='NEUTRAL'``; the rendering layer shows the
    two levels plus an explanatory note instead of a tradeable entry/stop/target.
    """
    prices = req.historical_prices
    window = min(20, len(prices))
    recent = prices[-window:]
    return SniperPoints(
        ideal_buy=None,
        secondary_buy=None,
        stop_loss=None,
        take_profit=None,
        position_size_pct=None,
        safety_margin=None,
        support_level=round(min(recent), 2),
        resistance_level=round(max(recent), 2),
        risk_reward_ratio=None,
        sell_mode=False,
        direction="NEUTRAL",
        invariant_warnings=[
            "方向性狙击位已隐去：点目标价已诚实暂缺（唯一可得的数会是编造的），"
            "无可锚定的目标，仅保留支撑/阻力。"
        ],
    )
