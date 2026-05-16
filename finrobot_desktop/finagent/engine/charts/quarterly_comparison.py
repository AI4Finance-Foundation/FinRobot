"""Quarterly comparison grouped bar chart — compare metrics across quarters by year.

**What this code does that raw LLM cannot**: Renders a deterministic grouped
bar chart with correct bar positioning (offset per year within each quarter),
distinct colour assignment per year from ChartConfig, and proper legend. The
grouping logic (quarters on X-axis, years as bar clusters) with computed bar
widths and offsets cannot be produced by text-only LLM output.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.figure import Figure

from finagent.engine.charts.base import ChartConfig, ChartDataPoint, _num, figure_to_png

# Colour palette for years — extends beyond ChartConfig's 3 named colours
# so charts with 4+ years still look distinct.
_YEAR_PALETTE = [
    "#1a365d",  # primary_color default
    "#d4a843",  # accent_color default
    "#22c55e",  # green
    "#ef4444",  # red
    "#8b5cf6",  # purple
    "#06b6d4",  # cyan
]


def _create_figure(
    data: ChartDataPoint,
    config: ChartConfig | None = None,
) -> Figure:
    """Build the matplotlib Figure for quarterly comparison grouped bar chart.

    Exposed for testing so callers can inspect bars, legend, and labels
    without serialising to PNG.

    Parameters
    ----------
    data : ChartDataPoint
        Chart data with rows containing ``quarter``, ``year``, and ``value``.
    config : ChartConfig | None
        Styling config; uses defaults if None.
    """
    cfg = config or ChartConfig()
    rows = data.data

    # Collect unique quarters in order of appearance, and unique years sorted
    seen_quarters: list[str] = []
    years_set: set[str] = set()
    for r in rows:
        q = str(r.get("quarter", ""))
        y = str(r.get("year", ""))
        if q and q not in seen_quarters:
            seen_quarters.append(q)
        if y:
            years_set.add(y)
    years = sorted(years_set)

    # Build lookup: (quarter, year) -> value
    lookup: dict[tuple[str, str], float] = {}
    for r in rows:
        q = str(r.get("quarter", ""))
        y = str(r.get("year", ""))
        lookup[(q, y)] = _num(r.get("value"))

    n_years = len(years)
    n_quarters = len(seen_quarters)
    x = np.arange(n_quarters)
    bar_width = 0.8 / max(n_years, 1)

    # Assign colours: use ChartConfig first two, then palette extras
    palette = [cfg.primary_color, cfg.accent_color] + _YEAR_PALETTE[2:]

    fig, ax = plt.subplots(figsize=(cfg.width, cfg.height))
    fig.patch.set_facecolor(cfg.background_color)
    ax.set_facecolor(cfg.background_color)

    for i, year in enumerate(years):
        values = [lookup.get((q, year), 0.0) for q in seen_quarters]
        offset = (i - (n_years - 1) / 2) * bar_width
        color = palette[i % len(palette)]
        ax.bar(
            x + offset,
            values,
            width=bar_width,
            label=year,
            color=color,
            edgecolor="none",
        )

    ax.set_xticks(x)
    ax.set_xticklabels(seen_quarters)
    ax.set_ylabel(data.y_label or data.title or "Value")
    ax.set_title(data.title)
    ax.legend()
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.tight_layout()
    return fig


def render(
    data: ChartDataPoint,
    config: ChartConfig | None = None,
) -> bytes:
    """Render quarterly comparison grouped bar chart to PNG bytes.

    Returns raw PNG bytes (not base64). Use ``render_to_base64`` from
    ``charts.base`` if a data URI is needed.
    """
    cfg = config or ChartConfig()
    fig = _create_figure(data, cfg)
    return figure_to_png(fig, cfg)
