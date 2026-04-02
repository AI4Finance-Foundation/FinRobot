"""Margin trend multi-line chart — gross, EBITDA, and operating margins.

**What this code does that raw LLM cannot**: Renders a deterministic
multi-line chart with three margin series over time, converting decimal
fractions (0.38) to human-readable percentage labels (38%). Each line has
distinct colour and marker styling from ChartConfig, with a proper legend.
This visual encoding cannot be produced by text-only LLM output.
"""

from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from finagent.engine.charts.base import ChartConfig, ChartDataPoint  # noqa: E402


def _create_figure(
    data: ChartDataPoint,
    config: ChartConfig | None = None,
) -> Figure:
    """Build the matplotlib Figure for margin trend line chart.

    Exposed for testing so callers can inspect lines, labels, and legend
    without serialising to PNG.
    """
    cfg = config or ChartConfig()
    rows = data.data

    years = [int(r["year"]) for r in rows]  # type: ignore[arg-type]
    gross = [float(r["gross_margin"]) * 100 for r in rows]  # type: ignore[arg-type]
    ebitda = [float(r["ebitda_margin"]) * 100 for r in rows]  # type: ignore[arg-type]
    operating = [float(r["operating_margin"]) * 100 for r in rows]  # type: ignore[arg-type]

    fig, ax = plt.subplots(figsize=(cfg.width, cfg.height))
    fig.patch.set_facecolor(cfg.background_color)
    ax.set_facecolor(cfg.background_color)

    ax.plot(
        years,
        gross,
        color=cfg.primary_color,
        marker="o",
        linewidth=2,
        label="Gross Margin",
    )
    ax.plot(
        years,
        ebitda,
        color=cfg.accent_color,
        marker="s",
        linewidth=2,
        label="EBITDA Margin",
    )
    ax.plot(
        years,
        operating,
        color=cfg.neutral_color,
        marker="^",
        linewidth=2,
        label="Operating Margin",
    )

    ax.set_xticks(years)
    ax.set_xticklabels([str(y) for y in years])
    ax.set_ylabel("Margin (%)")
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
    """Render margin trend line chart to PNG bytes.

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
