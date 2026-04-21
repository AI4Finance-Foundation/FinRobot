"""HTML report renderer using Jinja2.

What this code does that raw LLM cannot: generates structured multi-page
HTML reports with embedded base64 chart images, consistent formatting,
and typed data rendering. Not a text dump — deterministic layout with
inline CSS for print/PDF compatibility, color-coded recommendations,
and formatted financial numbers.
"""

from __future__ import annotations

import re
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


def _auto_bold(text: str) -> str:
    """Auto-bold dollar amounts, percentages, and multiples in text."""
    if not text or "<strong>" in text:
        return text
    # Dollar amounts with magnitude suffix
    text = re.sub(
        r"(\$[\d,.]+\s*(?:billion|million|trillion|bn|mn|B|M|K|T))",
        r"<strong>\1</strong>",
        text,
        flags=re.IGNORECASE,
    )
    # Percentages (e.g. 25.3%, -10%, +5%)
    text = re.sub(r"(?<!\d)([\-+]?\d+\.?\d*%)", r"<strong>\1</strong>", text)
    # Multiples (e.g. 12.5x)
    text = re.sub(r"\b(\d+\.?\d*x)\b", r"<strong>\1</strong>", text)
    return text


def _markdown_to_html(text: str) -> str:
    """Convert markdown text to HTML. Handles headings, bold, lists."""
    if not text:
        return ""
    lines = text.split("\n")
    html_lines: list[str] = []
    in_list = False
    for line in lines:
        s = line.strip()
        if not s:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            continue
        if s.startswith("### "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            c = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s[4:])
            html_lines.append(
                f'<h4 style="font-size:0.9rem;font-weight:600;color:#334155;'
                f'margin:0.75rem 0 0.4rem;">{_auto_bold(c)}</h4>'
            )
            continue
        if s.startswith("## "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            c = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s[3:])
            html_lines.append(
                f'<h3 style="font-size:1rem;font-weight:600;color:#0f172a;'
                f"margin:1rem 0 0.5rem;border-left:3px solid #6366f1;"
                f'padding-left:0.6rem;">{_auto_bold(c)}</h3>'
            )
            continue
        if s.startswith("- "):
            if not in_list:
                html_lines.append(
                    '<ul style="list-style:none;padding-left:0;margin:0.35rem 0;">'
                )
                in_list = True
            item = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s[2:])
            html_lines.append(
                f'<li style="padding:0.3rem 0 0.3rem 1.2rem;position:relative;'
                f'font-size:0.875rem;color:#334155;line-height:1.6;">'
                f'<span style="position:absolute;left:0;color:#6366f1;">&#8227;</span>'
                f" {_auto_bold(item)}</li>"
            )
            continue
        if in_list:
            html_lines.append("</ul>")
            in_list = False
        c = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        html_lines.append(
            f'<p style="margin-bottom:0.4rem;font-size:0.875rem;color:#334155;'
            f'line-height:1.7;">{_auto_bold(c)}</p>'
        )
    if in_list:
        html_lines.append("</ul>")
    return "\n".join(html_lines)


def _get_env() -> Environment:
    """Create Jinja2 environment with financial formatting filters."""
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
    )
    env.filters["fmtnum"] = _format_number
    env.filters["fmtpct"] = _format_percent
    env.filters["fmtmult"] = _format_multiple
    env.filters["autobold"] = _auto_bold
    env.filters["md2html"] = _markdown_to_html
    return env


def render_equity_report(context: dict[str, object]) -> str:
    """Render full equity research HTML report.

    context keys: ticker, company_name, current_price, market_cap,
    recommendation, price_target, charts (dict of base64 strings),
    historical_metrics, forecast, dcf_result, peer_comps,
    catalyst_analysis, valuation_synthesis
    """
    env = _get_env()
    template = env.get_template("equity_research.html")
    return template.render(**context)


def render_comps_report(context: dict[str, object]) -> str:
    """Render comparable company analysis HTML report.

    context keys: ticker, charts (dict of base64 strings), peer_comps
    """
    env = _get_env()
    template = env.get_template("comps.html")
    return template.render(**context)


def render_dcf_report(context: dict[str, object]) -> str:
    """Render DCF valuation HTML report.

    context keys: ticker, charts (dict of base64 strings), dcf_result
    """
    env = _get_env()
    template = env.get_template("dcf.html")
    return template.render(**context)


def render_lbo_report(context: dict[str, object]) -> str:
    """Render LBO analysis HTML report.

    context keys: ticker, lbo_result
    """
    env = _get_env()
    template = env.get_template("lbo.html")
    return template.render(**context)


def render_earnings_report(context: dict[str, object]) -> str:
    """Render earnings analysis HTML report.

    context keys: ticker, earnings_result
    """
    env = _get_env()
    template = env.get_template("earnings.html")
    return template.render(**context)


def render_ic_memo_report(context: dict[str, object]) -> str:
    """Render IC memo HTML report.

    context keys: ticker, ic_financials, steps
    """
    env = _get_env()
    template = env.get_template("ic_memo.html")
    return template.render(**context)
