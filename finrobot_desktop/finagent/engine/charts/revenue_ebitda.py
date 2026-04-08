"""Revenue & EBITDA grouped bar chart with historical/forecast distinction.

**What this code does that raw LLM cannot**: Deterministic matplotlib rendering
of side-by-side revenue/EBITDA bars with visual encoding — solid bars for
historical data, hatched semi-transparent bars for forecast periods. Values are
normalised to billions for axis labels; x-axis distinguishes actuals from
estimates via "E" suffix. This structural guarantee cannot be replicated by
free-text LLM output.
"""

from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from finagent.engine.charts.base import ChartConfig, ChartDataPoint, _num  # noqa: E402


def _create_figure(
    data: ChartDataPoint,
    config: ChartConfig | None = None,
) -> Figure:
    """Build the matplotlib Figure for revenue & EBITDA grouped bar chart.

    Exposed for testing so callers can inspect axes, titles, and bar
    properties without serialising to PNG.
    """
    cfg = config or ChartConfig()
    rows = data.data

    years: list[int] = [int(_num(r.get("year"))) for r in rows]
    revenues: list[float] = [_num(r.get("revenue")) / 1e9 for r in rows]
    ebitdas: list[float] = [_num(r.get("ebitda")) / 1e9 for r in rows]
    forecasts: list[bool] = [bool(r.get("is_forecast", False)) for r in rows]

    x_labels = [f"{y}E" if fc else str(y) for y, fc in zip(years, forecasts)]

    fig, ax = plt.subplots(figsize=(cfg.width, cfg.height))
    fig.patch.set_facecolor(cfg.background_color)
    ax.set_facecolor(cfg.background_color)

    bar_width = 0.35
    x_positions = list(range(len(years)))

    # Revenue bars
    for i, (xp, rev, fc) in enumerate(zip(x_positions, revenues, forecasts)):
        ax.bar(
            xp - bar_width / 2,
            rev,
            width=bar_width,
            color=cfg.primary_color,
            alpha=0.7 if fc else 1.0,
            hatch="//" if fc else None,
            label="Revenue" if i == 0 else None,
            edgecolor=cfg.primary_color,
        )

    # EBITDA bars
    for i, (xp, ebd, fc) in enumerate(zip(x_positions, ebitdas, forecasts)):
        ax.bar(
            xp + bar_width / 2,
            ebd,
            width=bar_width,
            color=cfg.accent_color,
            alpha=0.7 if fc else 1.0,
            hatch="//" if fc else None,
            label="EBITDA" if i == 0 else None,
            edgecolor=cfg.accent_color,
        )

    ax.set_xticks(x_positions)
    ax.set_xticklabels(x_labels)
    ax.set_ylabel("USD (Billions)")
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
    """Render revenue & EBITDA grouped bar chart to PNG bytes.

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
