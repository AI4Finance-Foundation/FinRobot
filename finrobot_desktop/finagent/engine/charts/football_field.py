"""Football field valuation chart — horizontal range bars by method.

**What this code does that raw LLM cannot**: Renders a structured horizontal
bar chart where each valuation method (DCF, EV/EBITDA, P/E, etc.) is
displayed as a range bar from low to high with a mid-value marker. The
bar geometry (left offset + width), y-axis ordering, and dual-element
overlay (range bar + midpoint marker) require deterministic coordinate
computation that cannot be replicated by free-text LLM output.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

from finagent.engine.charts.base import ChartConfig, ChartDataPoint, _num, render_chart


def _create_figure(
    data: ChartDataPoint,
    config: ChartConfig | None = None,
) -> Figure:
    """Build the matplotlib Figure for the football field valuation chart.

    Each row is a valuation method. A horizontal bar spans from low to high,
    with a vertical marker at mid. Methods are listed top-to-bottom in the
    order provided.

    Exposed for testing so callers can inspect axes, patches, and layout
    without serialising to PNG.
    """
    cfg = config or ChartConfig()
    rows = data.data

    methods: list[str] = [str(r["method"]) for r in rows]
    lows: list[float] = [_num(r.get("low")) for r in rows]
    mids: list[float] = [_num(r.get("mid")) for r in rows]
    highs: list[float] = [_num(r.get("high")) for r in rows]

    widths = [h - lo for h, lo in zip(highs, lows)]

    fig, ax = plt.subplots(figsize=(cfg.width, cfg.height))
    fig.patch.set_facecolor(cfg.background_color)
    ax.set_facecolor(cfg.background_color)

    y_positions = list(range(len(methods)))
    bar_height = 0.5

    # Horizontal range bars (low → high)
    ax.barh(
        y_positions,
        widths,
        left=lows,
        height=bar_height,
        color=cfg.primary_color,
        alpha=0.8,
        edgecolor=cfg.primary_color,
        label="Valuation Range",
    )

    # Mid-value markers
    ax.scatter(
        mids,
        y_positions,
        color=cfg.accent_color,
        s=100,
        zorder=5,
        marker="|",
        linewidths=3,
        label="Mid Estimate",
    )

    # Annotate low, mid, high values
    for i, (lo, mid, hi) in enumerate(zip(lows, mids, highs)):
        ax.text(
            lo - 1,
            i,
            f"${lo:,.0f}",
            ha="right",
            va="center",
            fontsize=8,
            color=cfg.neutral_color,
        )
        ax.text(
            mid,
            i + bar_height * 0.6,
            f"${mid:,.0f}",
            ha="center",
            va="bottom",
            fontsize=8,
            fontweight="bold",
            color=cfg.accent_color,
        )
        ax.text(
            hi + 1,
            i,
            f"${hi:,.0f}",
            ha="left",
            va="center",
            fontsize=8,
            color=cfg.neutral_color,
        )

    ax.set_yticks(y_positions)
    ax.set_yticklabels(methods)
    ax.set_xlabel("Implied Share Price ($)")
    ax.set_title(data.title)
    ax.legend(loc="lower right")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Add some x-axis padding so annotations aren't clipped
    x_min = min(lows) - 15
    x_max = max(highs) + 15
    ax.set_xlim(x_min, x_max)

    fig.tight_layout()
    return fig


def render(
    data: ChartDataPoint,
    config: ChartConfig | None = None,
) -> bytes:
    """Render football field valuation chart to PNG bytes.

    Returns raw PNG bytes (not base64). Use ``render_to_base64`` from
    ``charts.base`` if a data URI is needed.
    """
    return render_chart(_create_figure, data, config)
