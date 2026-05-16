"""EPS & PE Ratio dual-axis chart — bars for EPS, line for PE.

**What this code does that raw LLM cannot**: Deterministic dual-axis matplotlib
rendering with EPS as bars on the left y-axis and PE ratio as a line on the
right y-axis (twinx). Null PE ratio values are filtered out so the line only
connects years with valid data. This structural guarantee of aligned financial
metrics with proper null handling cannot be replicated by free-text LLM output.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

from finagent.engine.charts.base import ChartConfig, ChartDataPoint, _num, figure_to_png


def _create_figure(
    data: ChartDataPoint,
    config: ChartConfig | None = None,
) -> Figure:
    """Build the matplotlib Figure for an EPS & PE dual-axis chart.

    Exposed for testing so callers can inspect axes and properties
    without serialising to PNG.
    """
    cfg = config or ChartConfig()
    rows = data.data

    years: list[int] = [int(_num(r.get("year"))) for r in rows]
    eps_values: list[float] = [_num(r.get("eps")) for r in rows]

    # PE ratio can be None — collect only valid points for the line
    pe_years: list[int] = []
    pe_values: list[float] = []
    for r in rows:
        pe = r.get("pe_ratio")
        if pe is not None:
            pe_years.append(int(_num(r.get("year"))))
            pe_values.append(_num(pe))

    fig, ax_eps = plt.subplots(figsize=(cfg.width, cfg.height))
    fig.patch.set_facecolor(cfg.background_color)
    ax_eps.set_facecolor(cfg.background_color)

    # EPS bars — left y-axis
    x_positions = list(range(len(years)))
    ax_eps.bar(
        x_positions,
        eps_values,
        color=cfg.primary_color,
        alpha=0.85,
        label="EPS",
        edgecolor=cfg.primary_color,
        width=0.6,
    )
    ax_eps.set_ylabel("EPS (USD)", color=cfg.primary_color)
    ax_eps.tick_params(axis="y", labelcolor=cfg.primary_color)

    # PE ratio line — right y-axis (twinx)
    ax_pe = ax_eps.twinx()
    if pe_values:
        # Map pe_years back to x_positions
        year_to_x = {y: x for x, y in zip(x_positions, years)}
        pe_x = [year_to_x[y] for y in pe_years]
        ax_pe.plot(
            pe_x,
            pe_values,
            color=cfg.accent_color,
            linewidth=2,
            marker="o",
            markersize=6,
            label="PE Ratio",
        )
    ax_pe.set_ylabel("PE Ratio", color=cfg.accent_color)
    ax_pe.tick_params(axis="y", labelcolor=cfg.accent_color)

    # X-axis labels
    ax_eps.set_xticks(x_positions)
    ax_eps.set_xticklabels([str(y) for y in years])
    ax_eps.set_xlabel(data.x_label or "Year")
    ax_eps.set_title(data.title)

    # Combined legend
    lines_eps, labels_eps = ax_eps.get_legend_handles_labels()
    lines_pe, labels_pe = ax_pe.get_legend_handles_labels()
    ax_eps.legend(lines_eps + lines_pe, labels_eps + labels_pe, loc="upper left")

    ax_eps.spines["top"].set_visible(False)
    ax_pe.spines["top"].set_visible(False)

    fig.tight_layout()
    return fig


def render(
    data: ChartDataPoint,
    config: ChartConfig | None = None,
) -> bytes:
    """Render EPS & PE dual-axis chart to PNG bytes.

    Returns raw PNG bytes (not base64). Use ``render_to_base64`` from
    ``charts.base`` if a data URI is needed.
    """
    cfg = config or ChartConfig()
    fig = _create_figure(data, cfg)
    return figure_to_png(fig, cfg)
