"""HTML to PDF conversion.

What this code does that raw LLM cannot: converts structured HTML
with embedded charts into a printable PDF document.
"""
from __future__ import annotations


def render_pdf(html: str) -> bytes:
    """Convert HTML string to PDF bytes.

    Uses weasyprint if available, raises RuntimeError if not installed.

    Args:
        html: Full HTML document string (e.g., output of render_equity_report()).

    Returns:
        PDF document as raw bytes (starts with b"%PDF-").

    Raises:
        RuntimeError: If weasyprint is not installed.
    """
    try:
        from weasyprint import HTML
    except ImportError:
        raise RuntimeError(
            "PDF rendering requires weasyprint. "
            "Install: pip install weasyprint (requires pango/cairo system libraries)"
        )

    doc = HTML(string=html)
    return doc.write_pdf()
