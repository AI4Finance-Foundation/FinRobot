"""Technical analysis chart — Bollinger Bands, RSI, and MACD subplots.

**What this code does that raw LLM cannot**: Computes three distinct
technical indicators (Bollinger Bands, Wilder's RSI, MACD) from raw
OHLC price data using deterministic rolling-window arithmetic, then
renders a synchronized 3-subplot figure with proper height ratios.
The indicator math (exponential moving averages, rolling standard
deviations, Wilder smoothing) requires exact numeric computation
that a text-only LLM cannot perform reliably.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

from finagent.engine.charts.base import ChartConfig, ChartDataPoint, _num, figure_to_png


# ---------------------------------------------------------------------------
# Indicator computation (pure functions, no external library)
# ---------------------------------------------------------------------------


def _bollinger(
    closes: list[float], window: int = 20, num_std: int = 2
) -> tuple[list[float], list[float], list[float]]:
    """Return (upper, middle, lower) Bollinger Bands.

    Uses a running sum/sum-of-squares approach for O(n) performance.
    Points before the window is full are filled with NaN.
    """
    n = len(closes)
    upper: list[float] = [float("nan")] * n
    middle: list[float] = [float("nan")] * n
    lower: list[float] = [float("nan")] * n
    if n < window:
        return upper, middle, lower

    window_sum = sum(closes[:window])
    window_sq_sum = sum(x * x for x in closes[:window])

    for i in range(window - 1, n):
        if i > window - 1:
            outgoing = closes[i - window]
            incoming = closes[i]
            window_sum += incoming - outgoing
            window_sq_sum += incoming * incoming - outgoing * outgoing
        mean = window_sum / window
        variance = window_sq_sum / window - mean * mean
        std = variance**0.5 if variance > 0 else 0.0
        middle[i] = mean
        upper[i] = mean + num_std * std
        lower[i] = mean - num_std * std

    return upper, middle, lower


def _rsi(closes: list[float], period: int = 14) -> list[float]:
    """Compute Wilder's RSI.

    Uses the smoothed (exponential) moving average method for gains/losses.
    Returns a list the same length as *closes*; values before *period* are NaN.
    """
    n = len(closes)
    result: list[float] = [float("nan")] * n

    if n < period + 1:
        return result

    # Compute price changes
    deltas = [closes[i] - closes[i - 1] for i in range(1, n)]

    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]

    # Initial average over first *period* changes
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100.0 - 100.0 / (1.0 + rs)

    # Wilder smoothing for subsequent values
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i + 1] = 100.0 - 100.0 / (1.0 + rs)

    return result


def _ema(values: list[float], span: int) -> list[float]:
    """Exponential moving average with the standard multiplier 2/(span+1)."""
    result: list[float] = [float("nan")] * len(values)
    if not values:
        return result
    multiplier = 2.0 / (span + 1)
    result[0] = values[0]
    for i in range(1, len(values)):
        result[i] = (values[i] - result[i - 1]) * multiplier + result[i - 1]
    return result


def _macd(
    closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[list[float], list[float], list[float]]:
    """Return (macd_line, signal_line, histogram).

    MACD = EMA(fast) - EMA(slow).
    Signal = EMA(MACD, signal).
    Histogram = MACD - Signal.
    """
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)

    n = len(closes)
    macd_line: list[float] = [float("nan")] * n
    for i in range(n):
        if not (_is_nan(ema_fast[i]) or _is_nan(ema_slow[i])):
            macd_line[i] = ema_fast[i] - ema_slow[i]

    # Signal line: EMA of the non-NaN portion of macd_line
    valid_macd = [v for v in macd_line if not _is_nan(v)]
    signal_ema = _ema(valid_macd, signal) if valid_macd else []

    signal_line: list[float] = [float("nan")] * n
    j = 0
    for i in range(n):
        if not _is_nan(macd_line[i]):
            if j < len(signal_ema):
                signal_line[i] = signal_ema[j]
            j += 1

    histogram: list[float] = [float("nan")] * n
    for i in range(n):
        if not (_is_nan(macd_line[i]) or _is_nan(signal_line[i])):
            histogram[i] = macd_line[i] - signal_line[i]

    return macd_line, signal_line, histogram


def _is_nan(v: float) -> bool:
    """Check if a float is NaN (avoids math import)."""
    return v != v  # noqa: PLR0124


# ---------------------------------------------------------------------------
# Chart rendering
# ---------------------------------------------------------------------------


def _create_figure(data: ChartDataPoint, config: ChartConfig | None = None) -> Figure:
    """Build the matplotlib Figure with 3 technical analysis subplots.

    Exposed for testing so callers can inspect axes, lines, and patches
    without serialising to PNG.
    """
    cfg = config or ChartConfig()
    rows = data.data

    dates = [str(r.get("date", "")) for r in rows]
    closes = [_num(r.get("close")) for r in rows]
    # high/low used for reference but indicators use close
    # (kept for potential future candlestick extension)

    # Compute indicators
    bb_upper, bb_middle, bb_lower = _bollinger(closes)
    rsi_values = _rsi(closes)
    macd_line, signal_line, histogram = _macd(closes)

    fig, (ax1, ax2, ax3) = plt.subplots(
        3,
        1,
        sharex=True,
        figsize=(cfg.width, cfg.height * 1.5),
        gridspec_kw={"height_ratios": [3, 1, 1]},
    )
    fig.patch.set_facecolor(cfg.background_color)
    for ax in (ax1, ax2, ax3):
        ax.set_facecolor(cfg.background_color)

    x = list(range(len(dates)))

    # --- Top subplot: Price + Bollinger Bands ---
    ax1.plot(x, closes, color=cfg.primary_color, linewidth=1.5, label="Close")
    ax1.plot(x, bb_middle, color=cfg.accent_color, linewidth=1, linestyle="--", label="BB Mid")
    ax1.plot(x, bb_upper, color=cfg.neutral_color, linewidth=0.8, label="BB Upper")
    ax1.plot(x, bb_lower, color=cfg.neutral_color, linewidth=0.8, label="BB Lower")
    ax1.fill_between(
        x,
        bb_lower,
        bb_upper,
        alpha=0.1,
        color=cfg.neutral_color,
    )
    ax1.set_ylabel("Price")
    ax1.set_title(data.title)
    ax1.legend(loc="upper left", fontsize=7)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)

    # --- Middle subplot: RSI ---
    ax2.plot(x, rsi_values, color=cfg.primary_color, linewidth=1.2, label="RSI(14)")
    ax2.axhline(70, color=cfg.accent_color, linestyle="--", linewidth=0.8, label="Overbought (70)")
    ax2.axhline(30, color=cfg.accent_color, linestyle="--", linewidth=0.8, label="Oversold (30)")
    ax2.set_ylabel("RSI")
    ax2.set_ylim(0, 100)
    ax2.legend(loc="upper left", fontsize=7)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)

    # --- Bottom subplot: MACD ---
    ax3.plot(x, macd_line, color=cfg.primary_color, linewidth=1.2, label="MACD")
    ax3.plot(x, signal_line, color=cfg.accent_color, linewidth=1, label="Signal")
    # Histogram as bars — only draw where not NaN
    hist_colors = ["#4caf50" if not _is_nan(h) and h >= 0 else "#f44336" for h in histogram]
    hist_vals = [h if not _is_nan(h) else 0.0 for h in histogram]
    ax3.bar(x, hist_vals, color=hist_colors, alpha=0.6, width=0.8, label="Histogram")
    ax3.set_ylabel("MACD")
    ax3.legend(loc="upper left", fontsize=7)
    ax3.spines["top"].set_visible(False)
    ax3.spines["right"].set_visible(False)

    # X-axis tick labels — show a subset to avoid clutter
    tick_step = max(1, len(dates) // 10)
    tick_positions = list(range(0, len(dates), tick_step))
    ax3.set_xticks(tick_positions)
    ax3.set_xticklabels([dates[i] for i in tick_positions], rotation=45, ha="right", fontsize=7)

    fig.tight_layout()
    return fig


def render(data: ChartDataPoint, config: ChartConfig | None = None) -> bytes:
    """Render technical analysis chart to PNG bytes.

    Returns raw PNG bytes (not base64). Use ``render_to_base64`` from
    ``charts.base`` if a data URI is needed.
    """
    cfg = config or ChartConfig()
    fig = _create_figure(data, cfg)
    return figure_to_png(fig, cfg)
