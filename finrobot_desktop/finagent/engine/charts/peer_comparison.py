"""Peer comparison bar chart — EV/EBITDA multiples across peer group.

**What this code does that raw LLM cannot**: Renders a deterministic bar
chart comparing EV/EBITDA multiples across a peer group, with the target
company visually highlighted via accent colour. This colour-coded distinction
between target and peers, combined with typed data validation, cannot be
replicated by free-text LLM output.
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
    """Build the matplotlib Figure for peer comparison bar chart.

    Exposed for testing so callers can inspect bar colours and labels
    without serialising to PNG.
    """
    cfg = config or ChartConfig()
    rows = data.data

    tickers: list[str] = [str(r["ticker"]) for r in rows]
    ev_ebitdas: list[float] = [_num(r.get("ev_ebitda")) for r in rows]
    is_targets: list[bool] = [bool(r.get("is_target", False)) for r in rows]

    colors = [cfg.accent_color if is_t else cfg.primary_color for is_t in is_targets]

    fig, ax = plt.subplots(figsize=(cfg.width, cfg.height))
    fig.patch.set_facecolor(cfg.background_color)
    ax.set_facecolor(cfg.background_color)

    x_positions = list(range(len(tickers)))
    ax.bar(x_positions, ev_ebitdas, color=colors, edgecolor=colors)

    ax.set_xticks(x_positions)
    ax.set_xticklabels(tickers)
    ax.set_ylabel("EV/EBITDA")
    ax.set_title(data.title)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.tight_layout()
    return fig


def render(
    data: ChartDataPoint,
    config: ChartConfig | None = None,
) -> bytes:
    """Render peer comparison bar chart to PNG bytes.

    Returns raw PNG bytes (not base64). Use ``render_to_base64`` from
    ``charts.base`` if a data URI is needed.
    """
    cfg = config or ChartConfig()
    fig = _create_figure(data, cfg)
    return figure_to_png(fig, cfg)
