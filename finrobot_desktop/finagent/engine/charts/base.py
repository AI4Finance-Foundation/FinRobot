"""Chart base module — Pydantic models and rendering utilities for financial charts.

**What this code does that raw LLM cannot**: Provides deterministic PNG rendering
via matplotlib with typed data contracts (ChartConfig, ChartDataPoint, StepChartData)
that enforce schema validation at the boundary between pipeline computation and
frontend display. The render_to_base64 function converts matplotlib figures to
data URIs suitable for SSE streaming to the Electron frontend.
"""

from __future__ import annotations

import base64
import io
from typing import Literal

import matplotlib

matplotlib.use("Agg")

from matplotlib.figure import Figure  # noqa: E402
from pydantic import BaseModel  # noqa: E402


class ChartConfig(BaseModel):
    """Professional financial report styling defaults."""

    primary_color: str = "#1a365d"
    accent_color: str = "#d4a843"
    neutral_color: str = "#6b7280"
    background_color: str = "#ffffff"
    font_family: str = "sans-serif"
    width: float = 10
    height: float = 6
    dpi: int = 150


class ChartDataPoint(BaseModel):
    """Data contract for SSE chart payload to frontend.

    Each instance represents one chart with its typed data rows,
    chart_type discriminator, and axis labels.
    """

    chart_type: Literal[
        "revenue_ebitda",
        "margin_trend",
        "peer_comparison",
        "sensitivity",
        "football_field",
        "price",
        "eps_pe",
        "waterfall",
        "radar",
    ]
    data: list[dict[str, float | str | None | bool]]
    title: str
    x_label: str = ""
    y_label: str = ""


class StepChartData(BaseModel):
    """All charts produced by a single pipeline step."""

    charts: list[ChartDataPoint] = []


def render_to_base64(fig: Figure, dpi: int = 150) -> str:
    """Render a matplotlib Figure to a base64-encoded PNG data URI.

    Returns a string like ``data:image/png;base64,iVBOR...`` suitable for
    embedding in HTML or streaming via SSE to the frontend.

    The figure is closed after rendering to free memory.
    """
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    import matplotlib.pyplot as plt

    plt.close(fig)
    buf.seek(0)
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def validate_png(data: bytes) -> bool:
    """Check whether *data* starts with the PNG magic bytes (``\\x89PNG``)."""
    return data[:4] == b"\x89PNG"


def _num(v: float | str | None | bool) -> float:
    """Safely coerce any chart data value to float.

    ChartDataPoint.data uses ``dict[str, float | str | None | bool]`` to
    accommodate any chart schema. Individual chart renderers call ``_num``
    instead of bare ``float()`` so the conversion is null-safe and mypy-clean.

    Returns 0.0 for None; delegates to float() for all other inputs.
    """
    if v is None:
        return 0.0
    return float(v)
