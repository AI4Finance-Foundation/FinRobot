"""Cash flow composition stacked bar chart with net cash flow line overlay.

**What this code does that raw LLM cannot**: Renders a deterministic stacked
bar chart decomposing total cash flow into operating, investing, and financing
components per year, with negative bars extending below the zero axis. A net
cash flow line (sum of three components) is overlaid so the viewer can
simultaneously see composition and aggregate trend. The Y-axis is auto-scaled
with an appropriate magnitude label (e.g., "$M", "$B"). This multi-layer
visual encoding cannot be produced by text-only LLM output.
"""

from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from finagent.engine.charts.base import ChartConfig, ChartDataPoint, _num  # noqa: E402


def _scale_label(values: list[float]) -> tuple[float, str]:
    """Determine a human-friendly divisor and unit suffix for the Y-axis.

    Returns (divisor, suffix) — e.g. (1e9, "$B") or (1e6, "$M").
    """
    max_abs = max((abs(v) for v in values), default=0)
    if max_abs >= 1e9:
        return 1e9, "$B"
    if max_abs >= 1e6:
        return 1e6, "$M"
    if max_abs >= 1e3:
        return 1e3, "$K"
    return 1.0, "$"


def _create_figure(
    data: ChartDataPoint,
    config: ChartConfig | None = None,
) -> Figure:
    """Build the matplotlib Figure for cash flow composition chart.

    Exposed for testing so callers can inspect bars, lines, and legend
    without serialising to PNG.

    Parameters
    ----------
    data : ChartDataPoint
        Chart data with rows containing ``year``, ``operating``,
        ``investing``, and ``financing`` keys.
    config : ChartConfig | None
        Styling config; uses defaults if None.
    """
    cfg = config or ChartConfig()
    rows = data.data

    years = [str(int(_num(r.get("year")))) for r in rows]
    operating = [_num(r.get("operating")) for r in rows]
    investing = [_num(r.get("investing")) for r in rows]
    financing = [_num(r.get("financing")) for r in rows]

    # Determine scale for readable Y-axis
    all_values = operating + investing + financing
    divisor, suffix = _scale_label(all_values)

    op_scaled = [v / divisor for v in operating]
    inv_scaled = [v / divisor for v in investing]
    fin_scaled = [v / divisor for v in financing]
    net_scaled = [o + i + f for o, i, f in zip(op_scaled, inv_scaled, fin_scaled)]

    fig, ax = plt.subplots(figsize=(cfg.width, cfg.height))
    fig.patch.set_facecolor(cfg.background_color)
    ax.set_facecolor(cfg.background_color)

    x = np.arange(len(years))
    width = 0.6

    # Stacked bar chart — each component stacked independently
    # We stack positives upward and negatives downward from zero
    ax.bar(
        x,
        op_scaled,
        width=width,
        color=cfg.primary_color,
        label="Operating",
    )
    ax.bar(
        x,
        inv_scaled,
        width=width,
        bottom=op_scaled,
        color=cfg.accent_color,
        label="Investing",
    )
    ax.bar(
        x,
        fin_scaled,
        width=width,
        bottom=[o + i for o, i in zip(op_scaled, inv_scaled)],
        color=cfg.neutral_color,
        label="Financing",
    )

    # Net cash flow line overlay
    ax.plot(
        x,
        net_scaled,
        color="#ef4444",
        marker="o",
        linewidth=2,
        markersize=5,
        label="Net Cash Flow",
        zorder=5,
    )

    ax.set_xticks(x)
    ax.set_xticklabels(years)
    ax.set_ylabel(f"Cash Flow ({suffix})")
    ax.set_title(data.title)
    ax.axhline(0, color=cfg.neutral_color, linewidth=0.8, linestyle="-")
    ax.legend()
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.tight_layout()
    return fig


def render(
    data: ChartDataPoint,
    config: ChartConfig | None = None,
) -> bytes:
    """Render cash flow composition chart to PNG bytes.

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
