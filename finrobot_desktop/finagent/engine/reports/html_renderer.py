"""HTML report renderer using Jinja2.

What this code does that raw LLM cannot: generates structured multi-page
HTML reports with embedded base64 chart images, consistent formatting,
and typed data rendering. Not a text dump — deterministic layout with
inline CSS for print/PDF compatibility, color-coded recommendations,
and formatted financial numbers.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _format_number(value: float | int | None, decimals: int = 1) -> str:
    """Format a number with magnitude suffix (B/M/K) for display."""
    if value is None:
        return "N/A"
    abs_val = abs(value)
    sign = "-" if value < 0 else ""
    if abs_val >= 1e12:
        return f"{sign}${abs_val / 1e12:,.{decimals}f}T"
    if abs_val >= 1e9:
        return f"{sign}${abs_val / 1e9:,.{decimals}f}B"
    if abs_val >= 1e6:
        return f"{sign}${abs_val / 1e6:,.{decimals}f}M"
    if abs_val >= 1e3:
        return f"{sign}${abs_val / 1e3:,.{decimals}f}K"
    return f"{sign}${abs_val:,.{decimals}f}"


def _format_percent(value: float | None, decimals: int = 1) -> str:
    """Format a decimal (0.25) as a percentage string (25.0%)."""
    if value is None:
        return "N/A"
    return f"{value * 100:.{decimals}f}%"


def _format_multiple(value: float | None, decimals: int = 1) -> str:
    """Format a valuation multiple (e.g. 25.3x)."""
    if value is None:
        return "N/A"
    return f"{value:.{decimals}f}x"


def _get_env() -> Environment:
    """Create Jinja2 environment with financial formatting filters."""
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
    )
    env.filters["fmtnum"] = _format_number
    env.filters["fmtpct"] = _format_percent
    env.filters["fmtmult"] = _format_multiple
    return env


def render_equity_report(context: dict) -> str:
    """Render full equity research HTML report.

    context keys: ticker, company_name, current_price, market_cap,
    recommendation, price_target, charts (dict of base64 strings),
    historical_metrics, forecast, dcf_result, peer_comps,
    catalyst_analysis, valuation_synthesis
    """
    env = _get_env()
    template = env.get_template("equity_research.html")
    return template.render(**context)


def render_comps_report(context: dict) -> str:
    """Render comparable company analysis HTML report.

    context keys: ticker, charts (dict of base64 strings), peer_comps
    """
    env = _get_env()
    template = env.get_template("comps.html")
    return template.render(**context)


def render_dcf_report(context: dict) -> str:
    """Render DCF valuation HTML report.

    context keys: ticker, charts (dict of base64 strings), dcf_result
    """
    env = _get_env()
    template = env.get_template("dcf.html")
    return template.render(**context)
