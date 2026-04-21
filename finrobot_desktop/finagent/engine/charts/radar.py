"""Multi-dimensional financial radar chart — company vs benchmark polygons.

**What this code does that raw LLM cannot**: Deterministic polar-projection
matplotlib rendering with two closed polygons (company values vs benchmark)
plotted on N equidistant angular axes. The angular geometry (theta calculation,
polygon closure by appending the first point) is a structural guarantee that
free-text LLM output cannot replicate.
"""

from __future__ import annotations

import math

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from finagent.engine.charts.base import ChartConfig, ChartDataPoint, _num, figure_to_png  # noqa: E402


def _create_figure(
    data: ChartDataPoint,
    config: ChartConfig | None = None,
) -> Figure:
    """Build the matplotlib Figure for a financial radar chart.

    Exposed for testing so callers can inspect axes and projection type
    without serialising to PNG.
    """
    cfg = config or ChartConfig()
    rows = data.data

    dimensions: list[str] = [str(r["dimension"]) for r in rows]
    values: list[float] = [_num(r.get("value")) for r in rows]
    benchmarks: list[float] = [_num(r.get("benchmark")) for r in rows]

    n = len(dimensions)
    # Compute angle for each dimension — equally spaced
    angles = [i * 2 * math.pi / n for i in range(n)]

    # Close the polygon by appending the first point
    values_closed = values + [values[0]]
    benchmarks_closed = benchmarks + [benchmarks[0]]
    angles_closed = angles + [angles[0]]

    fig, ax = plt.subplots(
        figsize=(cfg.width, cfg.height),
        subplot_kw={"projection": "polar"},
    )
    fig.patch.set_facecolor(cfg.background_color)

    # Company polygon
    ax.plot(
        angles_closed,
        values_closed,
        color=cfg.primary_color,
        linewidth=2,
        label="Company",
    )
    ax.fill(angles_closed, values_closed, color=cfg.primary_color, alpha=0.15)

    # Benchmark polygon
    ax.plot(
        angles_closed,
        benchmarks_closed,
        color=cfg.neutral_color,
        linewidth=2,
        linestyle="--",
        label="Benchmark",
    )
    ax.fill(angles_closed, benchmarks_closed, color=cfg.neutral_color, alpha=0.08)

    # Axis labels
    ax.set_xticks(angles)
    ax.set_xticklabels(dimensions, fontsize=10)

    # Title — placed as figure suptitle so it doesn't collide with polar axis
    ax.set_title(data.title, pad=20)

    ax.legend(loc="upper right", bbox_to_anchor=(1.15, 1.1))

    fig.tight_layout()
    return fig


def render(
    data: ChartDataPoint,
    config: ChartConfig | None = None,
) -> bytes:
    """Render financial radar chart to PNG bytes.

    Returns raw PNG bytes (not base64). Use ``render_to_base64`` from
    ``charts.base`` if a data URI is needed.
    """
    cfg = config or ChartConfig()
    fig = _create_figure(data, cfg)
    return figure_to_png(fig, cfg)
