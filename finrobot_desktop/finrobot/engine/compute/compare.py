"""Multi-company valuation comparison.

What this code does that raw LLM cannot: runs the same deterministic DCF
pipeline for each ticker, then aligns the results into a side-by-side
comparison table. The LLM selects assumptions per company; code guarantees
every company is valued using identical methodology and the numbers are
arithmetically correct.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from finrobot.engine.models.financial import DCFResult


class CompanyValuation(BaseModel):
    """Summary valuation metrics for one company in a comparison."""

    ticker: str
    company_name: str = ""
    current_price: float | None = None
    implied_price: float | None = None
    upside_pct: float | None = None
    wacc: float | None = None
    terminal_growth: float | None = None
    ev_ebitda: float | None = None
    pe_ratio: float | None = None
    dcf_result: DCFResult | None = None
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class ComparisonResult(BaseModel):
    """Side-by-side comparison of multiple companies."""

    companies: list[CompanyValuation]
    generated_at: str = Field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())


def build_company_valuation(
    ticker: str,
    company_name: str,
    current_price: float | None,
    dcf_result: DCFResult,
    ev_ebitda: float | None = None,
    pe_ratio: float | None = None,
    warnings: list[str] | None = None,
) -> CompanyValuation:
    """Build a CompanyValuation from a completed DCF result.

    Pure function: no I/O, no side effects.
    """
    implied = dcf_result.implied_price
    upside: float | None = None
    if current_price and current_price > 0:
        upside = ((implied - current_price) / current_price) * 100

    return CompanyValuation(
        ticker=ticker,
        company_name=company_name,
        current_price=current_price,
        implied_price=implied,
        upside_pct=upside,
        wacc=dcf_result.wacc,
        terminal_growth=dcf_result.inputs.terminal_growth_rate,
        ev_ebitda=ev_ebitda,
        pe_ratio=pe_ratio,
        dcf_result=dcf_result,
        warnings=warnings or [],
    )


def format_comparison_table(result: ComparisonResult) -> str:
    """Format comparison as a Markdown table for CLI output.

    Columns: Ticker | Price | Implied | Upside% | WACC | TGR | EV/EBITDA | P/E
    """
    header = "| Ticker | Price | Implied | Upside | WACC | TGR | EV/EBITDA | P/E |"
    divider = "|--------|-------|---------|--------|------|-----|-----------|-----|"
    rows: list[str] = [header, divider]

    for c in result.companies:
        if c.error:
            rows.append(f"| {c.ticker:<6} | -- | -- | -- | -- | -- | -- | ERROR: {c.error[:30]} |")
            continue

        price = f"${c.current_price:.2f}" if c.current_price else "--"
        implied = f"${c.implied_price:.2f}" if c.implied_price else "--"
        upside = f"{c.upside_pct:+.1f}%" if c.upside_pct is not None else "--"
        wacc = f"{c.wacc * 100:.1f}%" if c.wacc else "--"
        tgr = f"{c.terminal_growth * 100:.1f}%" if c.terminal_growth else "--"
        ev_ebitda = f"{c.ev_ebitda:.1f}x" if c.ev_ebitda else "--"
        pe = f"{c.pe_ratio:.1f}x" if c.pe_ratio else "--"

        rows.append(
            f"| {c.ticker:<6} | {price:>7} | {implied:>7} | {upside:>6} "
            f"| {wacc:>5} | {tgr:>4} | {ev_ebitda:>9} | {pe:>5} |"
        )

    return "\n".join(rows)
