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
    dcf_as_of: str | None = Field(
        default=None,
        description=(
            "ISO-8601 timestamp the underlying DCF artifact was generated "
            "(provenance / vintage). implied_price, WACC and the DCF-derived "
            "upside are only as fresh as this. None when the DCF was computed "
            "live in this call (no stored artifact) or is unavailable."
        ),
    )
    dcf_artifact_id: str | None = Field(
        default=None,
        description="Source DCF artifact id, for deep-linking to the run that produced these numbers.",
    )
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
    dcf_as_of: str | None = None,
    dcf_artifact_id: str | None = None,
) -> CompanyValuation:
    """Build a CompanyValuation from a completed DCF result.

    Pure function: no I/O, no side effects.

    ``dcf_as_of`` / ``dcf_artifact_id`` stamp the vintage of the DCF the row's
    implied_price/WACC came from, so a comparison table can disclose that
    row A is today's run while row B is a three-week-old stored artifact.
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
        dcf_as_of=dcf_as_of,
        dcf_artifact_id=dcf_artifact_id,
        warnings=warnings or [],
    )


def format_comparison_table(result: ComparisonResult) -> str:
    """Format comparison as a Markdown table for CLI output.

    Columns: Ticker | Price | Implied | Upside% | WACC | TGR | EV/EBITDA | P/E | DCF Date

    The DCF-date column discloses each row's vintage — rows assembled from
    stored artifacts of different ages must not look equally fresh. When the
    rows span more than ``_VINTAGE_SPREAD_WARN_DAYS`` a warning line is appended
    so a side-by-side upside isn't read as apples-to-apples.
    """
    header = "| Ticker | Price | Implied | Upside | WACC | TGR | EV/EBITDA | P/E | DCF Date |"
    divider = "|--------|-------|---------|--------|------|-----|-----------|-----|----------|"
    rows: list[str] = [header, divider]

    for c in result.companies:
        if c.error:
            rows.append(
                f"| {c.ticker:<6} | -- | -- | -- | -- | -- | -- | -- | ERROR: {c.error[:30]} |"
            )
            continue

        price = f"${c.current_price:.2f}" if c.current_price else "--"
        implied = f"${c.implied_price:.2f}" if c.implied_price else "--"
        upside = f"{c.upside_pct:+.1f}%" if c.upside_pct is not None else "--"
        wacc = f"{c.wacc * 100:.1f}%" if c.wacc else "--"
        tgr = f"{c.terminal_growth * 100:.1f}%" if c.terminal_growth else "--"
        ev_ebitda = f"{c.ev_ebitda:.1f}x" if c.ev_ebitda else "--"
        pe = f"{c.pe_ratio:.1f}x" if c.pe_ratio else "--"
        vintage = _vintage_date(c.dcf_as_of)

        rows.append(
            f"| {c.ticker:<6} | {price:>7} | {implied:>7} | {upside:>6} "
            f"| {wacc:>5} | {tgr:>4} | {ev_ebitda:>9} | {pe:>5} | {vintage:>10} |"
        )

    spread = vintage_spread_days(result)
    if spread is not None and spread > _VINTAGE_SPREAD_WARN_DAYS:
        rows.append("")
        rows.append(
            f"⚠️  DCF vintages span {spread} days — these valuations were not "
            "computed at the same time; upside is not apples-to-apples. "
            "Re-run the stale tickers' DCF before comparing."
        )

    return "\n".join(rows)


# Rows whose DCF vintages differ by more than this many days are flagged: a
# side-by-side comparison of valuations computed weeks apart is misleading.
_VINTAGE_SPREAD_WARN_DAYS = 7


def _vintage_date(dcf_as_of: str | None) -> str:
    """``2026-05-01T...`` → ``2026-05-01``; live/unknown → ``live``."""
    if not dcf_as_of:
        return "live"
    return dcf_as_of[:10]


def vintage_spread_days(result: ComparisonResult) -> int | None:
    """Whole-day gap between the oldest and newest stamped DCF in the table.

    Considers only rows that carry a ``dcf_as_of`` (stored artifacts). Returns
    ``None`` when fewer than two rows are dated (nothing to compare). Pure.
    """
    stamps: list[datetime] = []
    for c in result.companies:
        if c.error or not c.dcf_as_of:
            continue
        try:
            stamps.append(datetime.fromisoformat(c.dcf_as_of))
        except ValueError:
            continue
    if len(stamps) < 2:
        return None
    return (max(stamps) - min(stamps)).days
