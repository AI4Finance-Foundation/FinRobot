"""DCF sensitivity heatmap — WACC x Terminal Growth → Implied Share Price.

**What this code does that raw LLM cannot**: Reconstructs a 2D grid from a
flat list of {wacc, tg, implied_price} cells, renders a diverging-colormap
heatmap with per-cell price annotations, and handles null (impossible) cells
with masked arrays. The deterministic matrix reconstruction, colour mapping,
and annotation layout cannot be replicated by free-text LLM output.
"""

from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from finagent.engine.charts.base import ChartConfig, ChartDataPoint, _num  # noqa: E402


def _create_figure(
    data: ChartDataPoint,
    config: ChartConfig | None = None,
) -> Figure:
    """Build the matplotlib Figure for the DCF sensitivity heatmap.

    Reconstructs a 2D grid from the flat cell list. Rows = unique WACC values
    (ascending), columns = unique terminal growth values (ascending).
    Null implied_price cells are masked and rendered in grey.

    Exposed for testing so callers can inspect axes, annotations, and
    colourmap without serialising to PNG.
    """
    cfg = config or ChartConfig()
    rows = data.data

    # Extract unique axis values (sorted)
    wacc_vals = sorted({_num(r.get("wacc")) for r in rows})
    tg_vals = sorted({_num(r.get("tg")) for r in rows})

    # Build lookup: (wacc, tg) -> implied_price | None
    lookup: dict[tuple[float, float], float | None] = {}
    for r in rows:
        w = _num(r.get("wacc"))
        t = _num(r.get("tg"))
        price = r["implied_price"]
        lookup[(w, t)] = float(price) if price is not None else None

    # Build 2D array (rows=wacc, cols=tg)
    grid = np.full((len(wacc_vals), len(tg_vals)), np.nan)
    for i, w in enumerate(wacc_vals):
        for j, t in enumerate(tg_vals):
            val = lookup.get((w, t))
            if val is not None:
                grid[i, j] = val

    masked_grid = np.ma.masked_invalid(grid)  # type: ignore[no-untyped-call]

    fig, ax = plt.subplots(figsize=(cfg.width, cfg.height))
    fig.patch.set_facecolor(cfg.background_color)
    ax.set_facecolor("#e0e0e0")  # grey background for masked/null cells

    # Diverging colourmap — green=high price, red=low price
    cmap = plt.cm.RdYlGn  # type: ignore[attr-defined]
    cmap.set_bad(color="#e0e0e0")

    im = ax.imshow(masked_grid, cmap=cmap, aspect="auto")
    fig.colorbar(im, ax=ax, label="Implied Share Price ($)", shrink=0.8)

    # Axis labels
    ax.set_xticks(range(len(tg_vals)))
    ax.set_xticklabels([f"{t:.1%}" for t in tg_vals])
    ax.set_yticks(range(len(wacc_vals)))
    ax.set_yticklabels([f"{w:.1%}" for w in wacc_vals])

    ax.set_xlabel("Terminal Growth Rate")
    ax.set_ylabel("WACC")
    ax.set_title(data.title)

    # Annotate each cell with the price value
    for i in range(len(wacc_vals)):
        for j in range(len(tg_vals)):
            val = grid[i, j]
            if np.isnan(val):
                ax.text(j, i, "N/A", ha="center", va="center", fontsize=9, color="#999999")
            else:
                # Choose text colour based on background brightness
                norm_val = im.norm(val)
                rgba = cmap(norm_val)
                # Luminance-based contrast: dark text on light bg, white on dark
                luminance = 0.299 * rgba[0] + 0.587 * rgba[1] + 0.114 * rgba[2]
                text_color = "#000000" if luminance > 0.5 else "#ffffff"
                ax.text(
                    j,
                    i,
                    f"${val:,.0f}",
                    ha="center",
                    va="center",
                    fontsize=9,
                    fontweight="bold",
                    color=text_color,
                )

    fig.tight_layout()
    return fig


def render(
    data: ChartDataPoint,
    config: ChartConfig | None = None,
) -> bytes:
    """Render DCF sensitivity heatmap to PNG bytes.

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
