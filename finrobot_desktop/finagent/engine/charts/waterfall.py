"""Valuation bridge waterfall chart — floating bars for incremental values.

**What this code does that raw LLM cannot**: Deterministic waterfall rendering
where non-total bars float from a running cumulative base and total bars start
from zero. Positive, negative, and total segments are colour-coded differently.
The running-total arithmetic (base offsets, bar bottoms) is a structural
guarantee that free-text LLM output cannot replicate.
"""

from __future__ import annotations

from matplotlib.figure import Figure

from finagent.engine.charts.base import ChartConfig, ChartDataPoint, _num, new_axes, render_chart

# Colours for positive / negative / total bars
_COLOR_POSITIVE = "#2e7d32"
_COLOR_NEGATIVE = "#c62828"
_COLOR_TOTAL = "#1a365d"


def _create_figure(
    data: ChartDataPoint,
    config: ChartConfig | None = None,
) -> Figure:
    """Build the matplotlib Figure for a valuation bridge waterfall.

    Exposed for testing so callers can inspect axes and bar properties
    without serialising to PNG.
    """
    cfg = config or ChartConfig()
    rows = data.data

    labels: list[str] = [str(r["label"]) for r in rows]
    values: list[float] = [_num(r.get("value")) for r in rows]
    is_totals: list[bool] = [bool(r.get("is_total", False)) for r in rows]

    # Compute bottoms for each bar
    bottoms: list[float] = []
    bar_heights: list[float] = []
    colors: list[str] = []
    running = 0.0

    for val, is_total in zip(values, is_totals):
        if is_total:
            # Total bars start from 0 and go up to *val*
            bottoms.append(0.0)
            bar_heights.append(val)
            colors.append(_COLOR_TOTAL)
            running = val  # reset running to the total value
        else:
            if val >= 0:
                bottoms.append(running)
                bar_heights.append(val)
                colors.append(_COLOR_POSITIVE)
            else:
                # Negative: bar hangs down from running total
                bottoms.append(running + val)  # running + negative = lower edge
                bar_heights.append(abs(val))
                colors.append(_COLOR_NEGATIVE)
            running += val

    fig, ax = new_axes(cfg)

    x_positions = list(range(len(labels)))
    ax.bar(
        x_positions,
        bar_heights,
        bottom=bottoms,
        color=colors,
        edgecolor="white",
        width=0.6,
    )

    # Value labels on each bar
    for xp, bottom, height, val, is_total in zip(
        x_positions, bottoms, bar_heights, values, is_totals
    ):
        label_y = bottom + height + max(abs(v) for v in values) * 0.02
        ax.text(
            xp,
            label_y,
            f"${val:,.0f}B" if abs(val) >= 1 else f"${val:,.1f}B",
            ha="center",
            va="bottom",
            fontsize=9,
            fontweight="bold" if is_total else "normal",
        )

    # Connector lines between non-total bars
    for i in range(len(x_positions) - 1):
        if not is_totals[i]:
            top_of_current = bottoms[i] + bar_heights[i]
            ax.plot(
                [x_positions[i] + 0.3, x_positions[i + 1] - 0.3],
                [top_of_current, top_of_current],
                color=cfg.neutral_color,
                linewidth=0.8,
                linestyle="--",
            )

    ax.set_xticks(x_positions)
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_title(data.title)
    ax.set_ylabel(data.y_label or "USD (Billions)")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.tight_layout()
    return fig


def render(
    data: ChartDataPoint,
    config: ChartConfig | None = None,
) -> bytes:
    """Render valuation bridge waterfall to PNG bytes.

    Returns raw PNG bytes (not base64). Use ``render_to_base64`` from
    ``charts.base`` if a data URI is needed.
    """
    return render_chart(_create_figure, data, config)
