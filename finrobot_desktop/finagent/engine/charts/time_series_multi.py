"""Multi-axis time series chart — dual Y-axis for absolute values and ratios.

**What this code does that raw LLM cannot**: Renders a deterministic dual-axis
time series chart that auto-classifies metrics into absolute values (left axis)
and ratios/margins (right axis) based on key naming conventions. Left-axis
series use primary styling while right-axis series are formatted as percentages
with accent styling. Both axes share a synchronized x-axis and produce a
combined legend. This visual encoding with heterogeneous scales on a single
figure cannot be produced by text-only LLM output.
"""

from __future__ import annotations

import re

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

from finagent.engine.charts.base import ChartConfig, ChartDataPoint, _num, new_axes, render_chart

# Pattern for keys that represent percentage/ratio metrics
_RATIO_PATTERN = re.compile(r"(margin|ratio|pct)", re.IGNORECASE)

# Styling cycles for left and right axis lines
_LEFT_MARKERS = ["o", "s", "D", "^"]
_RIGHT_MARKERS = ["x", "+", "v", "p"]


def _is_ratio_key(key: str) -> bool:
    """Return True if the metric key represents a percentage/ratio."""
    return bool(_RATIO_PATTERN.search(key))


def _create_figure(
    data: ChartDataPoint,
    config: ChartConfig | None = None,
) -> Figure:
    """Build the matplotlib Figure for dual-axis time series chart.

    Exposed for testing so callers can inspect axes, lines, and labels
    without serialising to PNG.

    Parameters
    ----------
    data : ChartDataPoint
        Chart data with rows containing a time key (``year`` or ``date``)
        plus numeric metric columns. Keys containing "margin", "ratio", or
        "pct" are placed on the right Y-axis (formatted as %); all others
        go on the left Y-axis.
    config : ChartConfig | None
        Styling config; uses defaults if None.
    """
    cfg = config or ChartConfig()
    rows = data.data

    if not rows:
        fig, ax = new_axes(cfg)
        ax.set_title(data.title)
        return fig

    # Determine x-axis values (year or date)
    time_key = "year" if "year" in rows[0] else "date"
    x_labels = [str(r.get(time_key, "")) for r in rows]

    # Discover all numeric metric keys (exclude the time key)
    all_keys = {k for row in rows for k in row if k != time_key}
    left_keys: list[str] = sorted(k for k in all_keys if not _is_ratio_key(k))
    right_keys: list[str] = sorted(k for k in all_keys if _is_ratio_key(k))

    fig, ax_left = new_axes(cfg)

    x = list(range(len(x_labels)))
    lines_all = []
    labels_all = []

    # --- Left axis: absolute values ---
    left_colors = [cfg.primary_color, cfg.neutral_color, "#2563eb", "#7c3aed"]
    for i, key in enumerate(left_keys):
        values = [_num(r.get(key)) for r in rows]
        color = left_colors[i % len(left_colors)]
        marker = _LEFT_MARKERS[i % len(_LEFT_MARKERS)]
        label = key.replace("_", " ").title()
        (line,) = ax_left.plot(x, values, color=color, marker=marker, linewidth=2, label=label)
        lines_all.append(line)
        labels_all.append(label)

    ax_left.set_ylabel(data.x_label or "Value")
    ax_left.set_xticks(x)
    ax_left.set_xticklabels(x_labels)

    # --- Right axis: ratio/margin metrics (percentage) ---
    ax_right: plt.Axes | None = None
    if right_keys:
        ax_right = ax_left.twinx()
        right_colors = [cfg.accent_color, "#ef4444", "#f59e0b", "#10b981"]
        for i, key in enumerate(right_keys):
            values = [_num(r.get(key)) * 100 for r in rows]
            color = right_colors[i % len(right_colors)]
            marker = _RIGHT_MARKERS[i % len(_RIGHT_MARKERS)]
            label = key.replace("_", " ").title()
            (line,) = ax_right.plot(
                x,
                values,
                color=color,
                marker=marker,
                linewidth=2,
                linestyle="--",
                label=label,
            )
            lines_all.append(line)
            labels_all.append(label)

        ax_right.set_ylabel(data.y_label or "Percentage (%)")

    # Combined legend
    ax_left.legend(lines_all, labels_all, loc="upper left", fontsize=8)

    ax_left.set_title(data.title)
    ax_left.spines["top"].set_visible(False)
    if ax_right is None:
        ax_left.spines["right"].set_visible(False)

    fig.tight_layout()
    return fig


def render(
    data: ChartDataPoint,
    config: ChartConfig | None = None,
) -> bytes:
    """Render dual-axis time series chart to PNG bytes.

    Returns raw PNG bytes (not base64). Use ``render_to_base64`` from
    ``charts.base`` if a data URI is needed.
    """
    return render_chart(_create_figure, data, config)
