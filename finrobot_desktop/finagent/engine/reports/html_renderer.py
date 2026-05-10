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
    """Convert markdown text to HTML. Handles headings, bold, lists, tables, hr."""
    if not text:
        return ""
    lines = text.split("\n")
    html_lines: list[str] = []
    in_list = False
    in_table = False
    table_header_done = False

    def _close_list() -> None:
        nonlocal in_list
        if in_list:
            html_lines.append("</ul>")
            in_list = False

    def _close_table() -> None:
        nonlocal in_table, table_header_done
        if in_table:
            html_lines.append("</tbody></table></div>")
            in_table = False
            table_header_done = False

    def _inline(s: str) -> str:
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        return _auto_bold(s)

    def _is_table_separator(s: str) -> bool:
        return bool(re.match(r"^\|[\s\-:|]+\|$", s))

    def _parse_table_row(s: str) -> list[str]:
        cells = s.strip("|").split("|")
        return [c.strip() for c in cells]

    for line in lines:
        s = line.strip()

        if not s:
            _close_list()
            _close_table()
            continue

        # Horizontal rule
        if re.match(r"^-{3,}$", s) or re.match(r"^\*{3,}$", s):
            _close_list()
            _close_table()
            html_lines.append('<hr style="border:none;border-top:1px solid #e2e8f0;margin:0.75rem 0;">')
            continue

        # Table row
        if s.startswith("|") and s.endswith("|"):
            _close_list()
            if _is_table_separator(s):
                continue  # skip separator row (---|---|---)
            cells = _parse_table_row(s)
            if not in_table:
                # Start table with header
                in_table = True
                table_header_done = False
                html_lines.append(
                    '<div style="overflow-x:auto;margin:0.5rem 0;">'
                    '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;">'
                    "<thead><tr>"
                )
                for cell in cells:
                    html_lines.append(
                        f'<th style="text-align:left;padding:0.45rem 0.6rem;font-weight:600;'
                        f'font-size:0.75rem;color:#64748b;border-bottom:2px solid #e2e8f0;'
                        f'background:#f8fafc;">{_inline(cell)}</th>'
                    )
                html_lines.append("</tr></thead><tbody>")
                table_header_done = True
                continue
            # Data row
            html_lines.append("<tr>")
            for cell in cells:
                html_lines.append(
                    f'<td style="padding:0.4rem 0.6rem;border-bottom:1px solid #f1f5f9;'
                    f'color:#334155;">{_inline(cell)}</td>'
                )
            html_lines.append("</tr>")
            continue

        _close_table()

        # Headings
        if s.startswith("### "):
            _close_list()
            c = _inline(s[4:])
            html_lines.append(
                f'<h4 style="font-size:0.9rem;font-weight:600;color:#334155;'
                f'margin:0.75rem 0 0.4rem;">{c}</h4>'
            )
            continue
        if s.startswith("## "):
            _close_list()
            c = _inline(s[3:])
            html_lines.append(
                f'<h3 style="font-size:1rem;font-weight:600;color:#0f172a;'
                f"margin:1rem 0 0.5rem;border-left:3px solid #6366f1;"
                f'padding-left:0.6rem;">{c}</h3>'
            )
            continue

        # List items
        if s.startswith("- "):
            _close_table()
            if not in_list:
                html_lines.append(
                    '<ul style="list-style:none;padding-left:0;margin:0.35rem 0;">'
                )
                in_list = True
            item = _inline(s[2:])
            html_lines.append(
                f'<li style="padding:0.3rem 0 0.3rem 1.2rem;position:relative;'
                f'font-size:0.875rem;color:#334155;line-height:1.6;">'
                f'<span style="position:absolute;left:0;color:#6366f1;">&#8227;</span>'
                f" {item}</li>"
            )
            continue

        _close_list()
        # Paragraph
        c = _inline(s)
        html_lines.append(
            f'<p style="margin-bottom:0.4rem;font-size:0.875rem;color:#334155;'
            f'line-height:1.7;">{c}</p>'
        )

    _close_list()
    _close_table()
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
