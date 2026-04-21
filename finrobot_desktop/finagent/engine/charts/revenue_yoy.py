"""Revenue Year-over-Year growth bar chart.

**What this code does that raw LLM cannot**: Computes YoY growth rates from
raw revenue figures, renders conditional-colour bars (green for positive,
red for negative growth), and overlays a moving-average trend line when 4+
data points exist. This deterministic visual encoding with correct percentage
formatting cannot be produced by text-only LLM output.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from finagent.engine.charts.base import ChartConfig, ChartDataPoint, _num, figure_to_png  # noqa: E402


def _create_figure(
    data: ChartDataPoint,
    config: ChartConfig | None = None,
) -> Figure:
    """Build the matplotlib Figure for revenue YoY growth bar chart.

    Exposed for testing so callers can inspect bars, colours, and labels
    without serialising to PNG.

    Parameters
    ----------
    data : ChartDataPoint
        Chart data with rows containing ``year`` and ``revenue`` keys.
    config : ChartConfig | None
        Styling config; uses defaults if None.
    """
    cfg = config or ChartConfig()
    rows = data.data

    # Extract years and revenue values
    years = [str(int(_num(r.get("year")))) for r in rows]
    revenues = [_num(r.get("revenue")) for r in rows]

    # Compute YoY growth rates — first year has no prior, so skip it
    yoy_years: list[str] = []
    yoy_values: list[float] = []
    for i in range(1, len(revenues)):
        prev = abs(revenues[i - 1])
        if prev == 0:
            continue
        growth = (revenues[i] - revenues[i - 1]) / prev * 100
        yoy_years.append(years[i])
        yoy_values.append(growth)

    # Conditional bar colours: green for positive, red for negative
    positive_color = "#22c55e"  # green-500
    negative_color = "#ef4444"  # red-500
    colors = [positive_color if v >= 0 else negative_color for v in yoy_values]

    fig, ax = plt.subplots(figsize=(cfg.width, cfg.height))
    fig.patch.set_facecolor(cfg.background_color)
    ax.set_facecolor(cfg.background_color)

    ax.bar(yoy_years, yoy_values, color=colors, edgecolor="none", width=0.6)

    # Trend line (simple moving average) if 4+ data points
    if len(yoy_values) >= 4:
        window = 3
        ma: list[float] = []
        for i in range(len(yoy_values)):
            if i < window - 1:
                ma.append(sum(yoy_values[: i + 1]) / (i + 1))
            else:
                ma.append(sum(yoy_values[i - window + 1 : i + 1]) / window)
        ax.plot(
            yoy_years,
            ma,
            color=cfg.primary_color,
            linewidth=2,
            marker="o",
            markersize=4,
            label="3Y Moving Avg",
        )
        ax.legend()

    ax.set_ylabel("YoY Growth (%)")
    ax.set_title(data.title)
    ax.axhline(0, color=cfg.neutral_color, linewidth=0.8, linestyle="-")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.tight_layout()
    return fig


def render(
    data: ChartDataPoint,
    config: ChartConfig | None = None,
) -> bytes:
    """Render revenue YoY growth bar chart to PNG bytes.

    Returns raw PNG bytes (not base64). Use ``render_to_base64`` from
    ``charts.base`` if a data URI is needed.
    """
    cfg = config or ChartConfig()
    fig = _create_figure(data, cfg)
    return figure_to_png(fig, cfg)
