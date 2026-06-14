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

from pydantic_ai import Agent

from finrobot.config import FinRobotSettings
from finrobot.engine.compute.coordinators.extractor import (
    extract_company_financials,
    normalize_peer_to_usd,
)
from finrobot.engine.compute.operators.multiples import (
    calculate_multiples,
    compute_ttm_fcf,
    fcf_yield,
)
from finrobot.engine.compute.operators.cyclical_peers import screen_peers_with_cyclical
from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.data.normalize.contracts import NormalizedFinancials
from finrobot.engine.data.ticker import validate_ticker
from finrobot.engine.models.financial import CompanyFinancials
from finrobot.engine.data.types import DataType

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


def _build_financials_table(fin: NormalizedFinancials) -> str:
    """Format NormalizedFinancials into a readable table for the prompt.

    ADR-0006 Step 6: consumes the canonical typed model instead of raw dict so
    field resolution is deterministic and provenance is visible.

    Computes EV and EV/EBITDA from components when all are present.
    Does NOT default missing total_debt or total_cash to 0 — skips EV and
    tells the LLM which component is missing (N15 contract).
    Adds data quality notes when D&A is unavailable (N18 contract).
    """
    market_cap: float | None = fin.market_cap if fin.market_cap else None
    total_debt = fin.total_debt
    total_cash = fin.total_cash
    ebitda = fin.ebitda

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

    # Real, traceable TTM FCF (= OCF − CapEx) computed by the compute layer —
    # the LLM must NOT hand-compute FCF (CLAUDE.md red-line 3). None when the
    # provider didn't supply the cash-flow statement.
    ttm_fcf = compute_ttm_fcf(fin.operating_cash_flow, fin.capital_expenditure)
    ttm_fcf_yield = fcf_yield(ttm_fcf, market_cap)

    rows = [
        ("Revenue", _fmt_num(fin.revenue)),
        ("EBITDA", _fmt_num(ebitda)),
        ("Net Income", _fmt_num(fin.net_income)),
        ("Gross Margin", _fmt_pct(fin.gross_margin)),
        ("Operating Margin", _fmt_pct(fin.operating_margin)),
        ("Market Cap", _fmt_num(market_cap)),
        ("P/E Ratio", f"{fin.pe_ratio:.1f}x" if fin.pe_ratio else "N/A"),
        ("Enterprise Value", ev_str),
        ("EV/EBITDA", ev_ebitda_str),
        ("Total Debt", _fmt_num(total_debt)),
        ("Total Cash", _fmt_num(total_cash)),
        ("Operating Cash Flow (TTM)", _fmt_num(fin.operating_cash_flow)),
        ("CapEx (TTM)", _fmt_num(fin.capital_expenditure)),
        ("Free Cash Flow (TTM)", _fmt_num(ttm_fcf)),
        ("FCF Yield", _fmt_pct(ttm_fcf_yield)),
        ("D&A", _fmt_num(fin.depreciation_amortization)),
        ("R&D Expense", _fmt_num(fin.rd_expense)),
        ("SG&A Expense", _fmt_num(fin.sga_expense)),
        ("Interest Expense", _fmt_num(fin.interest_expense)),
    ]
    lines = ["| Metric | Value |", "|--------|-------|"]
    for label, val in rows:
        lines.append(f"| {label} | {val} |")

    # --- Data quality notes ---
    notes: list[str] = []
    if ev_note:
        notes.append(ev_note)
    if ttm_fcf is None:
        missing = []
        if fin.operating_cash_flow is None:
            missing.append("operating cash flow")
        if fin.capital_expenditure is None:
            missing.append("CapEx")
        notes.append(
            f"Free Cash Flow unavailable — provider did not supply {', '.join(missing)}. "
            "Do NOT estimate FCF; state that it could not be computed from reported data."
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
1. **Operating Cash Flow Quality**: Accrual ratio (Net Income vs Operating Cash Flow), earnings quality
2. **Free Cash Flow**: Interpret the pre-computed **Free Cash Flow (TTM)** and **FCF Yield** \
rows in the data above (FCF = Operating Cash Flow − CapEx, the actual reported figure). \
Do NOT recompute FCF yourself — cite the provided number and explain what it implies. If \
Free Cash Flow is listed as N/A, state that it could not be computed from reported data and \
do NOT estimate it.
3. **Capital Intensity**: CapEx/Revenue and D&A/Revenue ratios, reinvestment requirements
4. **Cash Conversion**: How efficiently earnings convert to cash (FCF vs Net Income)
5. **Shareholder Returns Capacity**: FCF available for buybacks + dividends

CRITICAL: Every dollar figure you cite must come from a row in the data table above. Do not \
invent or recompute CapEx, ΔNWC, tax rates, or FCF — the FCF row is already computed for you.

Compare FCF margin (FCF/Revenue) to operating margin using the provided numbers.
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
    fin: NormalizedFinancials,
    peer_table: str = "",
) -> str:
    """Build a complete analysis prompt from NormalizedFinancials + template.

    ADR-0006 Step 6: accepts the canonical typed model (not raw dict) so every
    field read is provenance-stamped and deterministic.

    Raises ValueError if analysis_type is not recognized.
    """
    if analysis_type not in _PROMPTS:
        raise ValueError(
            f"Unknown analysis type '{analysis_type}'. Valid types: {sorted(ANALYSIS_TYPES)}"
        )
    table = _build_financials_table(fin)
    return _PROMPTS[analysis_type].format(
        ticker=ticker,
        table=table,
        peer_table=peer_table,
    )


# ------------------------------------------------------------------ #
# Data validation                                                    #
# ------------------------------------------------------------------ #


def _validate_analysis_data(fin: NormalizedFinancials) -> None:
    """Reject unusable canonical data before it reaches the LLM.

    ADR-0006 Step 6: validates NormalizedFinancials typed fields instead of
    raw dict keys — no silent misses on renamed provider keys.

    Raises ValueError with a user-facing message explaining what went wrong.
    """
    # Revenue present but zero/None — data is unusable
    if not fin.revenue or fin.revenue <= 0:
        raise ValueError(
            f"Revenue is {fin.revenue!r} for {fin.ticker} "
            f"(provider: {fin.provenance.provider}). "
            "Cannot run analysis on zero or missing revenue."
        )


# ------------------------------------------------------------------ #
# Runner                                                             #
# ------------------------------------------------------------------ #


async def run_analysis(
    data_layer: DataLayer,
    settings: FinRobotSettings,
    ticker: str,
    analysis_type: str,
) -> str:
    """Fetch canonical data, build prompt, call LLM, return analysis text.

    ADR-0006 Step 6: fetches NormalizedFinancials via fetch_canonical so all
    field resolution is deterministic, provenance-stamped, and validated before
    reaching the LLM prompt table. The LLM receives pre-validated financial
    data formatted into tables, not free-form text it would have to hallucinate.

    For 'competitors' type, fetches peer financial data using the same
    provider chain as the comps pipeline.
    """
    try:
        _fin = await data_layer.fetch_canonical(DataType.FINANCIALS, ticker)
    except (ProviderError, ValueError) as e:
        raise ValueError(f"Data fetch failed for {ticker} (fetch_canonical): {e}") from e

    _validate_analysis_data(_fin)

    peer_table = ""
    if analysis_type == "competitors":
        peer_table = await _fetch_peer_table(data_layer, settings, ticker)

    prompt = build_analysis_prompt(
        analysis_type,
        ticker.upper(),
        _fin,
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
    settings: FinRobotSettings,
    ticker: str,
) -> str:
    """Deterministic peer selection + canonical financials for comparison.

    Peers come from the same ADR-0014 recipe as the comps pipeline
    (``DataType.PEER_CANDIDATES`` fetch + pure ``screen_peers``), NOT an LLM
    pick. The retired LLM selector violated the core contract twice over: its
    output became fetch parameters without ``validate_ticker``, and its
    run-to-run nondeterminism made the peer table untraceable (the same class
    of swing that moved comps_pe ±30% in one day before ADR-0014). Each
    screened symbol is still passed through ``validate_ticker`` as a syntax
    gate before it becomes a cache key / provider fan-out parameter.

    ADR-0006 Step 6: peer financials come from fetch_canonical(FINANCIALS)
    so peer rows use the same typed fields as the target — no raw dict parse.
    """
    try:
        candidates = await data_layer.fetch(DataType.PEER_CANDIDATES, ticker)
    except ProviderError as e:
        logger.warning("Peer candidates unavailable for %s: %s", ticker, e)
        return "No peers identified."
    if candidates.data.get("error"):
        logger.warning("Peer candidates unavailable for %s: %s", ticker, candidates.data["error"])
        return "No peers identified."
    try:
        screen = screen_peers_with_cyclical(candidates.data, ticker)
    except ValueError as e:
        logger.warning("Peer screen degraded for %s: %s", ticker, e)
        return "No peers identified."

    peer_tickers: list[str] = []
    for raw in screen.tickers:
        try:
            norm = validate_ticker(raw)
        except ValueError:
            logger.warning("Dropping invalid peer symbol %r from screen for %s", raw, ticker)
            continue
        if norm != ticker.upper():
            peer_tickers.append(norm)
    peer_tickers = peer_tickers[:5]

    if not peer_tickers:
        return "No peers identified."

    fmp_api_key = getattr(settings, "fmp_api_key", None)

    async def _fetch_one(t: str) -> tuple[str, CompanyFinancials] | None:
        # Identical recipe to the hardened comps pipeline (execute_peer_analysis):
        # extract → FX-normalize to USD → compute multiples. Without this the
        # peer table fed to the LLM mixed currencies (e.g. TSM EBITDA in TWD vs a
        # USD market cap → the 0.158x failure mode) and showed un-sanity-gated raw
        # provider P/E. There is now ONE comps normalization path, not two (BUG-016).
        try:
            _peer = await data_layer.fetch_canonical(DataType.FINANCIALS, t)
            if not isinstance(_peer, NormalizedFinancials):
                return None
            company = extract_company_financials(_peer)
            company = await normalize_peer_to_usd(company, fmp_api_key=fmp_api_key)
            company = calculate_multiples(company)
            return (t, company)
        except (ProviderError, ValueError, RuntimeError, AttributeError, KeyError):
            logger.warning("Failed to fetch peer %s", t, exc_info=True)
            return None

    results = await asyncio.gather(*[_fetch_one(t) for t in peer_tickers])
    peers: list[tuple[str, CompanyFinancials]] = [r for r in results if r is not None]

    if not peers:
        return "Peer data unavailable."

    # Figures are USD-normalized; P/E is sanity-gated (out-of-range → N/A) so a
    # mixed-unit collapse can never reach the LLM as a real multiple.
    lines = [
        "| Ticker | Revenue (USD) | EBITDA (USD) | Gross Margin | Op. Margin | P/E |",
        "|--------|---------------|--------------|--------------|------------|-----|",
    ]
    for pticker, pcomp in peers:
        pe = f"{pcomp.pe_ratio:.1f}x" if pcomp.pe_ratio else "N/A"
        lines.append(
            f"| {pticker} | {_fmt_num(pcomp.revenue)} "
            f"| {_fmt_num(pcomp.ebitda)} "
            f"| {_fmt_pct(pcomp.gross_margin)} "
            f"| {_fmt_pct(pcomp.operating_margin)} "
            f"| {pe} |"
        )
    return "\n".join(lines)
