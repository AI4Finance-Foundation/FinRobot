"""Relative performance multi-line chart — rebased indexed return comparison.

**What this code does that raw LLM cannot**: Renders a deterministic multi-line
chart comparing a ticker against one or more benchmarks, with all series rebased
to 100 at the start date. Dynamically discovers any key ending with ``_return``
and plots each as a distinctly styled line. A horizontal reference line at 100
marks the base index. This visual encoding of relative performance with automatic
series discovery cannot be produced by text-only LLM output.
"""

from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from finagent.engine.charts.base import ChartConfig, ChartDataPoint, _num  # noqa: E402

# Styling palette for up to 6 series; cycles if more are needed.
_LINE_STYLES: list[tuple[str, str]] = [
    ("primary_color", "o"),
    ("accent_color", "s"),
    ("neutral_color", "^"),
    ("primary_color", "D"),
    ("accent_color", "v"),
    ("neutral_color", "P"),
]


def _create_figure(
    data: ChartDataPoint,
    config: ChartConfig | None = None,
) -> Figure:
    """Build the matplotlib Figure for relative performance chart.

    Exposed for testing so callers can inspect lines, labels, and legend
    without serialising to PNG.

    Parameters
    ----------
    data : ChartDataPoint
        Chart data with rows containing ``date`` and one or more keys
        ending with ``_return`` (e.g. ``ticker_return``, ``benchmark_return``).
        Values are expected to be already rebased to 100 at start.
    config : ChartConfig | None
        Styling config; uses defaults if None.
    """
    cfg = config or ChartConfig()
    rows = data.data

    dates = [str(r.get("date", "")) for r in rows]
    x_indices = list(range(len(dates)))

    # Discover all series: keys ending with "_return"
    series_keys: list[str] = []
    if rows:
        series_keys = sorted(k for k in rows[0] if isinstance(k, str) and k.endswith("_return"))

    fig, ax = plt.subplots(figsize=(cfg.width, cfg.height))
    fig.patch.set_facecolor(cfg.background_color)
    ax.set_facecolor(cfg.background_color)

    for idx, key in enumerate(series_keys):
        values = [_num(r.get(key)) for r in rows]
        style = _LINE_STYLES[idx % len(_LINE_STYLES)]
        color = getattr(cfg, style[0])
        marker = style[1]
        label = key.replace("_return", "").replace("_", " ").title()
        ax.plot(
            x_indices,
            values,
            color=color,
            marker=marker,
            linewidth=2,
            label=label,
        )

    # Reference line at 100
    ax.axhline(100, color=cfg.neutral_color, linestyle="--", linewidth=1, label="Base (100)")

    ax.set_xticks(x_indices)
    ax.set_xticklabels(dates, rotation=45, ha="right")
    ax.set_ylabel("Indexed Return (Base=100)")
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
    """Render relative performance chart to PNG bytes.

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
