"""Revenue segment donut chart — pie with center cutout for segment breakdown.

**What this code does that raw LLM cannot**: Renders a deterministic donut
(ring) chart via matplotlib showing revenue distribution across business
segments or geographies. Segments are sorted descending by revenue so the
largest wedge always starts first, percentage labels are computed from actual
values (not LLM hallucination), and the color palette cycles deterministically
through ChartConfig colours plus generated shades.
"""

from __future__ import annotations

import io
from itertools import cycle

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from finagent.engine.charts.base import ChartConfig, ChartDataPoint, _num  # noqa: E402


def _build_palette(cfg: ChartConfig) -> list[str]:
    """Build a colour palette from ChartConfig colours plus generated shades."""
    base = [cfg.primary_color, cfg.accent_color, cfg.neutral_color]
    # Generate lighter/darker variants for more segments
    extras = ["#2563eb", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899"]
    return base + extras


def _create_figure(
    data: ChartDataPoint,
    config: ChartConfig | None = None,
) -> Figure:
    """Build the matplotlib Figure for a revenue segment donut chart.

    Exposed for testing so callers can inspect wedges, labels, and legend
    without serialising to PNG.
    """
    cfg = config or ChartConfig()
    rows = data.data

    # Extract and sort segments descending by revenue
    parsed = [
        (str(r.get("segment", "")), _num(r.get("revenue")))
        for r in rows
    ]
    parsed.sort(key=lambda x: x[1], reverse=True)

    labels = [p[0] for p in parsed]
    sizes = [p[1] for p in parsed]

    palette = _build_palette(cfg)
    colors = [c for _, c in zip(range(len(labels)), cycle(palette))]

    fig, ax = plt.subplots(figsize=(cfg.width, cfg.height))
    fig.patch.set_facecolor(cfg.background_color)
    ax.set_facecolor(cfg.background_color)

    ax.pie(
        sizes,
        labels=None,
        autopct="%1.1f%%",
        colors=colors,
        wedgeprops=dict(width=0.4),
        startangle=90,
        counterclock=False,
    )

    ax.legend(
        labels,
        loc="center left",
        bbox_to_anchor=(1.0, 0.5),
        frameon=False,
    )

    ax.set_title(data.title)
    fig.tight_layout()
    return fig


def render(
    data: ChartDataPoint,
    config: ChartConfig | None = None,
) -> bytes:
    """Render revenue segment donut chart to PNG bytes.

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
