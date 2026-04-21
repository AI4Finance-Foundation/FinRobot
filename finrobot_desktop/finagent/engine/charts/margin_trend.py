"""Margin trend multi-line chart — gross, EBITDA, and operating margins.

**What this code does that raw LLM cannot**: Renders a deterministic
multi-line chart with configurable margin series over time, converting decimal
fractions (0.38) to human-readable percentage labels (38%). Each line has
distinct colour and marker styling from ChartConfig, with a proper legend.
Supports single-metric variants (gross_margin, sga_ratio, ltm_ebitda_margin)
and an EBITDA-detail variant with horizontal mean line and value annotation.
This visual encoding cannot be produced by text-only LLM output.
"""

from __future__ import annotations

from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from finagent.engine.charts.base import ChartConfig, ChartDataPoint, _num, figure_to_png  # noqa: E402


@dataclass
class MetricLine:
    """Specification for a single line in the margin trend chart."""

    key: str  # dict key in data, e.g. "gross_margin"
    label: str  # legend label, e.g. "Gross Margin"
    color_attr: str  # ChartConfig attribute, e.g. "primary_color"
    marker: str  # matplotlib marker, e.g. "o"


_DEFAULT_METRICS = [
    MetricLine("gross_margin", "Gross Margin", "primary_color", "o"),
    MetricLine("ebitda_margin", "EBITDA Margin", "accent_color", "s"),
    MetricLine("operating_margin", "Operating Margin", "neutral_color", "^"),
]


def _create_figure(
    data: ChartDataPoint,
    config: ChartConfig | None = None,
    metrics: list[MetricLine] | None = None,
    *,
    show_mean_line: bool = False,
) -> Figure:
    """Build the matplotlib Figure for margin trend line chart.

    Exposed for testing so callers can inspect lines, labels, and legend
    without serialising to PNG.

    Parameters
    ----------
    data : ChartDataPoint
        Chart data with rows containing year + metric columns.
    config : ChartConfig | None
        Styling config; uses defaults if None.
    metrics : list[MetricLine] | None
        Which lines to draw. None → _DEFAULT_METRICS (3 lines).
    show_mean_line : bool
        If True, add a horizontal dashed line at the mean of the first metric
        and annotate the last data point value. Used by ebitda_margin_detail.
    """
    cfg = config or ChartConfig()
    lines = metrics if metrics is not None else _DEFAULT_METRICS
    rows = data.data

    years = [int(_num(r.get("year"))) for r in rows]

    fig, ax = plt.subplots(figsize=(cfg.width, cfg.height))
    fig.patch.set_facecolor(cfg.background_color)
    ax.set_facecolor(cfg.background_color)

    last_values: list[float] = []
    for ml in lines:
        values = [_num(r.get(ml.key)) * 100 for r in rows]
        color = getattr(cfg, ml.color_attr)
        ax.plot(
            years,
            values,
            color=color,
            marker=ml.marker,
            linewidth=2,
            label=ml.label,
        )
        last_values.append(values[-1] if values else 0.0)

    if show_mean_line and lines:
        first_values = [_num(r.get(lines[0].key)) * 100 for r in rows]
        mean_val = sum(first_values) / len(first_values) if first_values else 0.0
        ax.axhline(
            mean_val,
            color=cfg.neutral_color,
            linestyle="--",
            linewidth=1,
            label=f"Mean ({mean_val:.1f}%)",
        )
        # Annotate last data point
        if first_values and years:
            ax.annotate(
                f"{first_values[-1]:.1f}%",
                xy=(years[-1], first_values[-1]),
                xytext=(5, 5),
                textcoords="offset points",
                fontsize=9,
                color=getattr(cfg, lines[0].color_attr),
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
    metrics: list[MetricLine] | None = None,
    *,
    show_mean_line: bool = False,
) -> bytes:
    """Render margin trend line chart to PNG bytes.

    Returns raw PNG bytes (not base64). Use ``render_to_base64`` from
    ``charts.base`` if a data URI is needed.
    """
    cfg = config or ChartConfig()
    fig = _create_figure(data, cfg, metrics=metrics, show_mean_line=show_mean_line)
    return figure_to_png(fig, cfg)


# ---------------------------------------------------------------------------
# Factory functions for P6 chart_type variants
# ---------------------------------------------------------------------------


def render_gross_margin(
    data: ChartDataPoint, config: ChartConfig | None = None
) -> bytes:
    """Render single gross-margin line chart."""
    return render(
        data,
        config,
        metrics=[MetricLine("gross_margin", "Gross Margin", "primary_color", "o")],
    )


def render_ebitda_margin_detail(
    data: ChartDataPoint, config: ChartConfig | None = None
) -> bytes:
    """Render EBITDA margin with horizontal mean line and value annotation."""
    return render(
        data,
        config,
        metrics=[MetricLine("ebitda_margin", "EBITDA Margin", "accent_color", "s")],
        show_mean_line=True,
    )


def render_sga_ratio(
    data: ChartDataPoint, config: ChartConfig | None = None
) -> bytes:
    """Render single SG&A / Revenue ratio line chart."""
    return render(
        data,
        config,
        metrics=[MetricLine("sga_ratio", "SG&A / Revenue", "primary_color", "o")],
    )


def render_ltm_ebitda_margin(
    data: ChartDataPoint, config: ChartConfig | None = None
) -> bytes:
    """Render single LTM EBITDA Margin line chart."""
    return render(
        data,
        config,
        metrics=[
            MetricLine("ltm_ebitda_margin", "LTM EBITDA Margin", "primary_color", "o")
        ],
    )
