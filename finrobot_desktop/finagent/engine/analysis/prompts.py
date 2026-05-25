"""Analysis prompt templates and runner for standalone financial analysis.

What this code does that raw LLM cannot: encodes domain-specific financial
analysis frameworks (DuPont decomposition, Altman Z-score thresholds,
FCF quality metrics) as structured prompts with the company's actual data
pre-formatted into tables. The LLM receives both the numbers AND the
analytical framework, producing analyses grounded in real financials
rather than generic advice.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pydantic_ai import Agent

from finagent.config import FinAgentSettings
from finagent.engine.data.interface import DataResult
from finagent.engine.data.layer import DataLayer
from finagent.engine.data.types import DataType
logger = logging.getLogger(__name__)


def _fmt_num(value: float | int | None, decimals: int = 1) -> str:
    """Format a number with magnitude suffix (B/M/K) for prompt tables."""
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


def _fmt_pct(value: float | None, decimals: int = 1) -> str:
    """Format a decimal (0.25) as a percentage string (25.0%)."""
    if value is None:
        return "N/A"
    return f"{value * 100:.{decimals}f}%"


def _build_financials_table(data: dict[str, Any]) -> str:
    """Format raw financials dict into a readable table for the prompt.

    Fix 3.2: Computes EV and EV/EBITDA from components when all are present.
    Does NOT default missing total_debt or total_cash to 0 — skips EV and
    tells the user which component is missing.

    Fix 3.3: Adds data quality notes when D&A is unavailable so the LLM
    includes approximation warnings in user-visible output.
    """
    # --- Fix 3.2: compute EV and EV/EBITDA ---
    market_cap = data.get("market_cap")
    total_debt = data.get("total_debt")
    total_cash = data.get("total_cash")
    ebitda = data.get("ebitda")

    ev: float | None = None
    ev_ebitda: float | None = None
    ev_note = ""

    if market_cap is not None and total_debt is not None and total_cash is not None:
        ev = market_cap + total_debt - total_cash
        if ebitda and ebitda > 0:
            ev_ebitda = ev / ebitda
    else:
        missing_parts = []
        if total_debt is None:
            missing_parts.append("total_debt")
        if total_cash is None:
            missing_parts.append("total_cash")
        if market_cap is None:
            missing_parts.append("market_cap")
        ev_note = f"EV unavailable — missing: {', '.join(missing_parts)}"

    ev_str = _fmt_num(ev) if ev is not None else "N/A"
    # N16: explain why EV/EBITDA is N/A
    if ev_ebitda is not None:
        ev_ebitda_str = f"{ev_ebitda:.1f}x"
    elif ev is not None and ebitda is not None and ebitda <= 0:
        ev_ebitda_str = "N/A (negative EBITDA)"
    elif ev is None:
        ev_ebitda_str = "N/A (EV unavailable)"
    else:
        ev_ebitda_str = "N/A"

    rows = [
        ("Revenue", _fmt_num(data.get("revenue"))),
        ("EBITDA", _fmt_num(ebitda)),
        ("Net Income", _fmt_num(data.get("net_income"))),
        ("Gross Margin", _fmt_pct(data.get("gross_margin"))),
        ("Operating Margin", _fmt_pct(data.get("operating_margin"))),
        ("Market Cap", _fmt_num(market_cap)),
        ("P/E Ratio", f"{data['pe_ratio']:.1f}x" if data.get("pe_ratio") else "N/A"),
        ("Enterprise Value", ev_str),
        ("EV/EBITDA", ev_ebitda_str),
        ("Total Debt", _fmt_num(total_debt)),
        ("Total Cash", _fmt_num(total_cash)),
        ("D&A", _fmt_num(data.get("depreciation_amortization"))),
        ("R&D Expense", _fmt_num(data.get("rd_expense"))),
        ("SG&A Expense", _fmt_num(data.get("sga_expense"))),
        ("Interest Expense", _fmt_num(data.get("interest_expense"))),
    ]
    # Include yearly historical data if available
    yearly = data.get("yearly_data", [])
    lines = ["| Metric | Value |", "|--------|-------|"]
    for label, val in rows:
        lines.append(f"| {label} | {val} |")
    if yearly:
        lines.append("")
        lines.append("### Historical Annual Data")
        years = [str(y.get("fiscal_year", "?")) for y in yearly]
        lines.append("| Metric | " + " | ".join(years) + " |")
        lines.append("|--------" + "|-------" * len(years) + "|")
        for metric in ("revenue", "ebitda", "net_income", "gross_margin", "operating_margin"):
            label = metric.replace("_", " ").title()
            fmt = _fmt_pct if "margin" in metric else _fmt_num
            vals = [fmt(y.get(metric)) for y in yearly]
            lines.append(f"| {label} | " + " | ".join(vals) + " |")

    # --- Data quality notes (Fix 3.2 + Fix 3.3) ---
    notes: list[str] = []
    if ev_note:
        notes.append(ev_note)
    if data.get("depreciation_amortization") is None:
        notes.append(
            "D&A data unavailable — FCF estimates use simplified formula "
            "(EBITDA × (1-T) − CapEx − ΔNWC) which may overstate FCF by 10-20% "
            "for capital-intensive companies"
        )
    if notes:
        lines.append("")
        lines.append("### Data Quality Notes")
        for note in notes:
            lines.append(f"- **WARNING**: {note}")

    return "\n".join(lines)


# ------------------------------------------------------------------ #
# Prompt templates                                                   #
# ------------------------------------------------------------------ #

_INCOME_PROMPT = """You are a senior equity analyst. Analyze the income statement for {ticker}.

## Financial Data
{table}

## Analysis Framework
Provide a structured analysis covering:
1. **Revenue Analysis**: Growth trajectory, YoY trends, revenue quality
2. **Profitability Breakdown**: Gross margin → operating margin → net margin cascade
3. **Operating Leverage**: How costs scale with revenue (fixed vs variable cost structure)
4. **Expense Analysis**: R&D intensity, SG&A efficiency, interest burden
5. **Key Risks**: Margin compression signals, revenue concentration concerns

Use concrete numbers from the data. Compare margins to typical ranges for the sector.
Output in Markdown format."""

_BALANCE_PROMPT = """You are a senior equity analyst. Analyze the balance sheet for {ticker}.

## Financial Data
{table}

## Analysis Framework
Provide a structured analysis covering:
1. **Liquidity Assessment**: Cash position, current ratio implications, cash runway
2. **Capital Structure**: Debt/equity mix, net debt position, leverage ratios
3. **Debt Sustainability**: Interest coverage (EBITDA/interest expense), debt/EBITDA
4. **Asset Quality**: Cash as % of market cap, intangible asset concerns
5. **Financial Flexibility**: Capacity for buybacks, dividends, M&A

Use concrete numbers. Flag any Altman Z-score warning signals if debt is elevated.
Output in Markdown format."""

_CASHFLOW_PROMPT = """You are a senior equity analyst. Analyze the cash flow profile for {ticker}.

## Financial Data
{table}

## Analysis Framework
Provide a structured analysis covering:
1. **Operating Cash Flow Quality**: Accrual ratio (net income vs OCF), earnings quality
2. **Free Cash Flow**: If D&A data is available, use FCF = EBIT(1-T) + D&A - CapEx - ΔNWC. \
If D&A is listed as N/A, use the simplified formula FCF ≈ EBITDA(1-T) - CapEx - ΔNWC. \
Report FCF yield vs market cap.
3. **Capital Intensity**: D&A/Revenue ratio (if D&A available), reinvestment requirements
4. **Cash Conversion**: How efficiently earnings convert to cash
5. **Shareholder Returns Capacity**: FCF available for buybacks + dividends

IMPORTANT: If D&A is listed as N/A in the data above, you MUST include a clearly labeled \
"⚠ Data Limitation" note in your Free Cash Flow section stating that the FCF estimate uses \
a simplified formula without separate D&A, which may overstate FCF by 10-20% for \
capital-intensive companies. Do NOT omit this warning.

Use concrete numbers. Estimate FCF margin and compare to operating margin.
Output in Markdown format."""

_RISK_PROMPT = """You are a senior risk analyst. Assess the financial risk profile for {ticker}.

## Financial Data
{table}

## Analysis Framework
Categorize and analyze risks across four dimensions:
1. **Operational Risk**: Margin volatility, revenue concentration, cost structure rigidity
2. **Financial Risk**: Leverage, interest coverage, refinancing exposure, liquidity gap
3. **Market Risk**: Valuation (P/E) vs growth, sector cyclicality, multiple compression risk
4. **Strategic Risk**: R&D adequacy, competitive positioning signals from the financials

For each risk:
- Rate severity: Low / Medium / High
- Provide the specific data point driving the assessment
- Suggest what to monitor

Output in Markdown format with clear section headers."""

_COMPETITORS_PROMPT = """You are a senior equity analyst. Provide a competitive analysis for {ticker}.

## Target Company Data
{table}

## Peer Data
{peer_table}

## Analysis Framework
1. **Relative Valuation**: How does {ticker}'s P/E and EV/EBITDA compare to peers?
2. **Margin Comparison**: Gross and operating margins vs peer median — premium or discount?
3. **Scale & Growth**: Revenue position relative to peer group
4. **Competitive Advantages**: What the financial data suggests about moat (margin premium = pricing power)
5. **Valuation Verdict**: Is {ticker} cheap/fair/expensive relative to its operational quality?

Use specific numbers from both target and peers. Identify the closest comparable.
Output in Markdown format."""

_OVERVIEW_PROMPT = """You are a senior equity analyst. Provide a company overview for {ticker}.

## Financial Data
{table}

## Analysis Framework
Write a concise company overview covering:
1. **Financial Profile**: Revenue scale, profitability, market position (inferred from market cap)
2. **Business Quality Indicators**: Margin levels, R&D intensity, capital efficiency
3. **Valuation Snapshot**: P/E, implied EV/EBITDA, what the market is pricing in
4. **Key Strengths**: Top 3 financial strengths from the data
5. **Key Concerns**: Top 3 financial concerns or watch items

Keep it factual and data-driven. Avoid speculation beyond what the numbers support.
Output in Markdown format."""

_PROMPTS: dict[str, str] = {
    "income": _INCOME_PROMPT,
    "balance": _BALANCE_PROMPT,
    "cashflow": _CASHFLOW_PROMPT,
    "risk": _RISK_PROMPT,
    "competitors": _COMPETITORS_PROMPT,
    "overview": _OVERVIEW_PROMPT,
}

# Fix 4.6: Single source of truth — derived from _PROMPTS keys.
ANALYSIS_TYPES: frozenset[str] = frozenset(_PROMPTS)


def build_analysis_prompt(
    analysis_type: str,
    ticker: str,
    financials_data: dict[str, Any],
    peer_table: str = "",
) -> str:
    """Build a complete analysis prompt from data + template.

    Raises ValueError if analysis_type is not recognized.
    """
    if analysis_type not in _PROMPTS:
        raise ValueError(
            f"Unknown analysis type '{analysis_type}'. Valid types: {sorted(ANALYSIS_TYPES)}"
        )
    table = _build_financials_table(financials_data)
    return _PROMPTS[analysis_type].format(
        ticker=ticker,
        table=table,
        peer_table=peer_table,
    )


# ------------------------------------------------------------------ #
# Data validation                                                    #
# ------------------------------------------------------------------ #

# Minimum fields required for any analysis to be meaningful
_CRITICAL_FIELDS = {"revenue"}


def _validate_analysis_data(fin_result: DataResult) -> None:
    """Reject error/empty/insufficient data before it reaches the LLM.

    Raises ValueError with a user-facing message explaining what went wrong.
    """
    data = fin_result.data

    # Provider returned an explicit error payload
    if "error" in data:
        raise ValueError(
            f"Data fetch failed for {fin_result.ticker} "
            f"(provider: {fin_result.provider}): {data['error']}"
        )

    # Completely empty response
    if not data:
        raise ValueError(
            f"No financial data returned for {fin_result.ticker} "
            f"from {fin_result.provider}. Cannot run analysis on empty data."
        )

    # Missing critical fields
    missing = _CRITICAL_FIELDS - set(data.keys())
    if missing:
        raise ValueError(
            f"Incomplete financial data for {fin_result.ticker} "
            f"(provider: {fin_result.provider}): missing {sorted(missing)}. "
            "Analysis requires at least revenue data."
        )

    # Revenue present but zero/None — data is unusable
    rev = data.get("revenue")
    if not rev or (isinstance(rev, (int, float)) and rev <= 0):
        raise ValueError(
            f"Revenue is {rev!r} for {fin_result.ticker} "
            f"(provider: {fin_result.provider}). "
            "Cannot run analysis on zero or missing revenue."
        )


# ------------------------------------------------------------------ #
# Runner                                                             #
# ------------------------------------------------------------------ #


async def run_analysis(
    data_layer: DataLayer,
    settings: FinAgentSettings,
    ticker: str,
    analysis_type: str,
) -> str:
    """Fetch data, build prompt, call LLM, return analysis text.

    What this code does that raw LLM cannot: deterministic data fetching +
    structured prompt construction + LLM call orchestration. The LLM
    receives pre-validated financial data formatted into tables, not
    free-form text it would have to hallucinate.

    For 'competitors' type, fetches peer financial data using the same
    provider chain as the comps pipeline.
    """
    # Fetch financials for the target (build_analysis_prompt validates the type)
    fin_result: DataResult = await data_layer.fetch(DataType.FINANCIALS, ticker)

    # --- Fix 3.1: validate data before passing to LLM ---
    _validate_analysis_data(fin_result)

    peer_table = ""
    if analysis_type == "competitors":
        peer_table = await _fetch_peer_table(data_layer, settings, ticker, fin_result)

    prompt = build_analysis_prompt(
        analysis_type,
        ticker.upper(),
        fin_result.data,
        peer_table=peer_table,
    )

    agent: Agent[None, str] = Agent(
        settings.create_model(),
        instructions="You are a senior financial analyst. Be precise and data-driven.",
    )
    result = await agent.run(prompt)
    return result.output


async def _fetch_peer_table(
    data_layer: DataLayer,
    settings: FinAgentSettings,
    ticker: str,
    fin_result: DataResult,
) -> str:
    """Use LLM to select peers, then fetch their financials for comparison.

    Reuses the same peer-selection pattern as the comps pipeline but
    lighter-weight: no full PeerComps model, just formatted text.
    """
    # Ask LLM to pick 3-5 peers
    selector: Agent[None, str] = Agent(
        settings.create_model(),
        instructions=(
            "You are a financial analyst. Given a company ticker and its financials, "
            "return ONLY a comma-separated list of 3-5 peer company tickers "
            "(e.g. 'MSFT,GOOGL,META'). No explanation, just tickers."
        ),
    )
    context = f"Company: {ticker.upper()}\nRevenue: {_fmt_num(fin_result.data.get('revenue'))}"
    sel_result = await selector.run(context)
    raw_tickers = sel_result.output.strip().replace(" ", "")
    peer_tickers = [
        t.strip().upper()
        for t in raw_tickers.split(",")
        if t.strip() and t.strip().upper() != ticker.upper()
    ][:5]

    if not peer_tickers:
        return "No peers identified."

    # Fetch peer financials in parallel
    async def _fetch_one(t: str) -> tuple[str, dict[str, Any]] | None:
        try:
            r = await data_layer.fetch(DataType.FINANCIALS, t)
            return (t, r.data)
        except (ValueError, RuntimeError, AttributeError, KeyError):
            logger.warning("Failed to fetch peer %s", t, exc_info=True)
            return None

    results = await asyncio.gather(*[_fetch_one(t) for t in peer_tickers])
    peers = [r for r in results if r is not None]

    if not peers:
        return "Peer data unavailable."

    # Format peer table
    lines = [
        "| Ticker | Revenue | EBITDA | Gross Margin | Op. Margin | P/E |",
        "|--------|---------|--------|--------------|------------|-----|",
    ]
    for pticker, pdata in peers:
        pe = f"{pdata['pe_ratio']:.1f}x" if pdata.get("pe_ratio") else "N/A"
        lines.append(
            f"| {pticker} | {_fmt_num(pdata.get('revenue'))} "
            f"| {_fmt_num(pdata.get('ebitda'))} "
            f"| {_fmt_pct(pdata.get('gross_margin'))} "
            f"| {_fmt_pct(pdata.get('operating_margin'))} "
            f"| {pe} |"
        )
    return "\n".join(lines)
