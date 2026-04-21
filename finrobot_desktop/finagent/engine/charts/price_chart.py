"""52-week price line chart with volume bars on a secondary y-axis.

**What this code does that raw LLM cannot**: Deterministic dual-axis matplotlib
rendering — price as a line on the left y-axis and volume as semi-transparent
bars on the right y-axis (twinx). Date strings are parsed for proper x-axis
formatting. Volume is normalised to millions for readability. This structural
guarantee of aligned dual-axis time-series data cannot be replicated by
free-text LLM output.
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
    """Build the matplotlib Figure for a 52-week price + volume chart.

    Exposed for testing so callers can inspect axes and properties
    without serialising to PNG.
    """
    cfg = config or ChartConfig()
    rows = data.data

    dates: list[str] = [str(r["date"]) for r in rows]
    closes: list[float] = [_num(r.get("close")) for r in rows]
    volumes: list[float] = [_num(r.get("volume")) / 1e6 for r in rows]

    fig, ax_price = plt.subplots(figsize=(cfg.width, cfg.height))
    fig.patch.set_facecolor(cfg.background_color)
    ax_price.set_facecolor(cfg.background_color)

    # Price line — left y-axis
    x_positions = list(range(len(dates)))
    ax_price.plot(
        x_positions,
        closes,
        color=cfg.primary_color,
        linewidth=2,
        label="Close Price",
    )
    ax_price.set_ylabel(data.y_label or "Price (USD)", color=cfg.primary_color)
    ax_price.tick_params(axis="y", labelcolor=cfg.primary_color)

    # Volume bars — right y-axis (twinx)
    ax_vol = ax_price.twinx()
    ax_vol.bar(
        x_positions,
        volumes,
        color=cfg.neutral_color,
        alpha=0.3,
        label="Volume",
    )
    ax_vol.set_ylabel("Volume (M)", color=cfg.neutral_color)
    ax_vol.tick_params(axis="y", labelcolor=cfg.neutral_color)

    # X-axis date labels — show a subset to avoid overlap
    max_labels = 12
    if len(dates) > max_labels:
        step = max(1, len(dates) // max_labels)
        tick_positions = list(range(0, len(dates), step))
        ax_price.set_xticks(tick_positions)
        ax_price.set_xticklabels([dates[i] for i in tick_positions], rotation=45, ha="right")
    else:
        ax_price.set_xticks(x_positions)
        ax_price.set_xticklabels(dates, rotation=45, ha="right")

    ax_price.set_xlabel(data.x_label or "Date")
    ax_price.set_title(data.title)

    # Combined legend
    lines_price, labels_price = ax_price.get_legend_handles_labels()
    lines_vol, labels_vol = ax_vol.get_legend_handles_labels()
    ax_price.legend(lines_price + lines_vol, labels_price + labels_vol, loc="upper left")

    ax_price.spines["top"].set_visible(False)
    ax_vol.spines["top"].set_visible(False)

    fig.tight_layout()
    return fig


def render(
    data: ChartDataPoint,
    config: ChartConfig | None = None,
) -> bytes:
    """Render 52-week price + volume chart to PNG bytes.

    Returns raw PNG bytes (not base64). Use ``render_to_base64`` from
    ``charts.base`` if a data URI is needed.
    """
    cfg = config or ChartConfig()
    fig = _create_figure(data, cfg)
    return figure_to_png(fig, cfg)
