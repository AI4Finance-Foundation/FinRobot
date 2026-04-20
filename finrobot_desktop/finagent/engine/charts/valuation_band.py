"""Valuation range band chart — EV/EBITDA historical band with mean ± 1σ.

**What this code does that raw LLM cannot**: Renders a deterministic time-series
chart with a valuation multiple line, horizontal mean line, and a shaded ±1σ
standard-deviation band using matplotlib fill_between. The last data point is
annotated with its numeric value. This statistical visual encoding (mean, std,
fill_between) cannot be produced by text-only LLM output.
"""

from __future__ import annotations

import io
import statistics

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from finagent.engine.charts.base import ChartConfig, ChartDataPoint, _num  # noqa: E402


def _create_figure(
    data: ChartDataPoint,
    config: ChartConfig | None = None,
) -> Figure:
    """Build the matplotlib Figure for valuation band chart.

    Exposed for testing so callers can inspect lines, collections, and
    annotations without serialising to PNG.

    Parameters
    ----------
    data : ChartDataPoint
        Chart data with rows containing ``date`` and ``ev_ebitda`` keys.
    config : ChartConfig | None
        Styling config; uses defaults if None.
    """
    cfg = config or ChartConfig()
    rows = data.data

    dates = [str(r.get("date", "")) for r in rows]
    values = [_num(r.get("ev_ebitda")) for r in rows]

    mean_val = statistics.mean(values) if values else 0.0
    std_val = statistics.pstdev(values) if len(values) >= 2 else 0.0

    upper_band = [mean_val + std_val] * len(values)
    lower_band = [mean_val - std_val] * len(values)

    x_indices = list(range(len(dates)))

    fig, ax = plt.subplots(figsize=(cfg.width, cfg.height))
    fig.patch.set_facecolor(cfg.background_color)
    ax.set_facecolor(cfg.background_color)

    # Shaded ±1σ band
    ax.fill_between(
        x_indices,
        lower_band,
        upper_band,
        alpha=0.15,
        color=cfg.primary_color,
        label="±1σ Band",
    )

    # Value line
    ax.plot(
        x_indices,
        values,
        color=cfg.primary_color,
        marker="o",
        linewidth=2,
        label="EV/EBITDA",
    )

    # Mean line (dashed)
    ax.axhline(
        mean_val,
        color=cfg.accent_color,
        linestyle="--",
        linewidth=1.5,
        label=f"Mean ({mean_val:.1f}x)",
    )

    # Annotate last data point
    if values:
        last_val = values[-1]
        ax.annotate(
            f"{last_val:.1f}x",
            xy=(x_indices[-1], last_val),
            xytext=(5, 8),
            textcoords="offset points",
            fontsize=9,
            fontweight="bold",
            color=cfg.primary_color,
        )

    ax.set_xticks(x_indices)
    ax.set_xticklabels(dates, rotation=45, ha="right")
    y_label = data.y_label if data.y_label else "EV/EBITDA"
    ax.set_ylabel(y_label)
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
    """Render valuation band chart to PNG bytes.

    Returns raw PNG bytes (not base64). Use ``render_to_base64`` from
    ``charts.base`` if a data URI is needed.
    """
    cfg = config or ChartConfig()
    fig = _create_figure(data, cfg)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=cfg.dpi, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()
