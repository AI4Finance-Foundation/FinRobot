"""DCF refactor red-lines.

These tests scan the source tree for patterns that, if reintroduced, would
walk back the Phase A-D rework:

  1. Frontend cannot ship hardcoded DEFAULT_COMPUTE_BODY / DEFAULT_INPUTS for
     DCF inputs. Every per-ticker assumption must come from /api/compute/dcf-seed.

  2. Charts must use fmtUsd / fmtPct etc. — no raw `$${v.toFixed(0)}` style
     tick / tooltip formatters that overflow at trillion-scale (the original
     screenshot's "000000000" Y-axis bug).

  3. DCFInputs.assumption_provenance must contain every field that flows
     through seed_dcf_inputs — otherwise the UI's provenance panel renders
     blank rows.

These are red-line guards. If you legitimately need to introduce one of the
banned patterns (e.g. a chart that genuinely renders share prices and needs
raw `$X`), update the allow-list in the corresponding test rather than the
production code.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from finrobot.engine.compute.operators.dcf_seed import seed_dcf_inputs
from finrobot.engine.models.financial import (
    BalanceSheet,
    FinancialData,
    HistoricalMetrics,
    IncomeStatement,
    MarketData,
    ValuationMetrics,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
UI_SRC = REPO_ROOT / "ui" / "src"


# ---------------------------------------------------------------------------
# 1. Frontend hardcoded defaults
# ---------------------------------------------------------------------------


_BANNED_TOKENS = ["DEFAULT_COMPUTE_BODY", "DEFAULT_INPUTS"]


def _iter_ui_sources() -> list[Path]:
    return [p for p in UI_SRC.rglob("*") if p.is_file() and p.suffix in {".ts", ".tsx"}]


def test_no_hardcoded_dcf_defaults_in_ui():
    """Removed in D1 — must not return.

    DEFAULT_COMPUTE_BODY shipped 14 DCF parameters identical for every
    ticker (the cause of the AAPL $106 screenshot). DEFAULT_INPUTS was the
    Playground-side equivalent. Both gone; both forbidden.
    """
    offenders: list[str] = []
    for path in _iter_ui_sources():
        text = path.read_text()
        for token in _BANNED_TOKENS:
            if token in text:
                # Allow mentions inside comments / commit-historian strings if they
                # are explicitly tagged "removed" — but only on a single line.
                hits = [
                    (i + 1, line)
                    for i, line in enumerate(text.splitlines())
                    if token in line and "removed" not in line.lower()
                ]
                if hits:
                    line_refs = ", ".join(f"L{n}" for n, _ in hits)
                    offenders.append(f"{path.relative_to(REPO_ROOT)} ({line_refs}): {token}")
    assert not offenders, (
        "DCF hardcoded defaults must come from /api/compute/dcf-seed:\n" + "\n".join(offenders)
    )


# ---------------------------------------------------------------------------
# 2. Chart raw-money formatter
# ---------------------------------------------------------------------------


# A `tickFormatter` that returns `\`$${...}\`` directly (no fmtUsd / no
# abbreviation helper) — this is the exact pattern that produced the original
# "300000000" Y-axis bug at trillion scale.
_RAW_DOLLAR_TICK_FMT = re.compile(
    r"tickFormatter\s*=\s*\{[^}]*\(\s*v\s*:\s*number\s*\)\s*=>\s*`\$\$\{",
    re.MULTILINE,
)


# Charts that are intentionally fine with `$X` (e.g. share-price charts under
# $1,000 always — no overflow risk). Add a new entry here only after confirming
# the chart will never render a trillion-scale value.
_RAW_TICK_ALLOWLIST = {
    "CandlestickChart.tsx",  # stock OHLC, always $-hundreds
    "MonteCarloChart.tsx",  # implied-price histogram, $-hundreds bins
    "EpsPeChart.tsx",  # EPS in $, single digits
    "EpsSurpriseChart.tsx",  # EPS surprise in $
    "EpsTrendChart.tsx",  # annual EPS bars in $, single digits (eps.toFixed(2))
    "FootballField.tsx",  # valuation range in $ per share
    "PriceTrendChart.tsx",  # 1Y share-price line, Y-axis = close prices ($-hundreds)
}


def test_charts_dont_use_raw_dollar_tick_formatter_for_aggregates():
    """Aggregate-value charts (waterfall, capex, etc.) must format with fmtUsd.

    The screenshot bug was a Recharts YAxis that rendered $1,194,284,335,403
    as a clipped run of zeros. Use desktop/src/utils/formatters.fmtUsd for
    anything with potential B/T magnitude.
    """
    charts_dir = UI_SRC / "components" / "charts"
    offenders: list[str] = []
    for path in charts_dir.glob("*.tsx"):
        if path.name.endswith(".test.tsx"):
            continue
        if path.name in _RAW_TICK_ALLOWLIST:
            continue
        text = path.read_text()
        if _RAW_DOLLAR_TICK_FMT.search(text):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        "Charts must use fmtUsd / similar helpers for $ ticks, not raw `$${v}`. "
        "If the chart only renders <$1000 stock prices, add it to "
        "_RAW_TICK_ALLOWLIST in this file.\n" + "\n".join(offenders)
    )


# ---------------------------------------------------------------------------
# 3. Provenance coverage
# ---------------------------------------------------------------------------


_REQUIRED_PROVENANCE_KEYS = {
    "revenue_base",
    "revenue_growth_rates",
    "ebitda_margin",
    "capex_pct_revenue",
    "da_pct_revenue",
    "nwc_pct_revenue",
    "tax_rate",
    "beta",
    "cost_of_debt",
    "debt_ratio",
    "risk_free_rate",
    "equity_risk_premium",
    "terminal_growth_rate",
    "shares_outstanding",
    "net_debt",
}


def _minimal_financials() -> FinancialData:
    return FinancialData(
        ticker="TEST",
        company_name="Test Co",
        timestamp=datetime.now(tz=timezone.utc),
        income=IncomeStatement(
            revenue=1e10,
            ebitda=2e9,
            net_income=1e9,
            gross_margin=0.5,
            operating_margin=0.2,
            interest_expense=1e8,
        ),
        balance=BalanceSheet(total_debt=1e9, total_cash=5e8),
        market=MarketData(
            market_cap=2e10,
            shares_outstanding=1e9,
            current_price=20.0,
            industry="Software (System & Application)",
            beta=1.2,
        ),
        valuation=ValuationMetrics(),
    )


def _empty_historical(ticker: str = "TEST") -> HistoricalMetrics:
    return HistoricalMetrics(
        years=[],
        revenue=[],
        revenue_growth_yoy=[],
        cogs=[],
        gross_profit=[],
        gross_margin=[],
        sga=[],
        sga_ratio=[],
        ebitda=[],
        ebitda_margin=[],
        operating_income=[],
        operating_margin=[],
        net_income=[],
        eps=[],
        pe_ratio=[],
        cagr_revenue=None,
        ticker=ticker,
    )


def test_assumption_provenance_covers_every_dcf_input_field():
    """seed_dcf_inputs must annotate every numeric field — the UI's
    AssumptionProvenance panel would otherwise render a blank line for
    each missing entry."""
    inputs = seed_dcf_inputs(_minimal_financials(), _empty_historical())
    missing = _REQUIRED_PROVENANCE_KEYS - set(inputs.assumption_provenance.keys())
    assert not missing, f"Missing provenance for fields: {sorted(missing)}"


def test_assumption_provenance_messages_are_english():
    """Provenance text targets English-speaking analysts — guard against
    Chinese strings sneaking back in."""
    inputs = seed_dcf_inputs(_minimal_financials(), _empty_historical())
    offenders: list[str] = []
    for key, msg in inputs.assumption_provenance.items():
        if any("一" <= ch <= "鿿" for ch in msg) or not any(
            ch.isascii() and ch.isalpha() for ch in msg
        ):
            offenders.append(f"{key}: {msg}")
    assert not offenders, "Provenance messages must be readable English:\n" + "\n".join(offenders)


# ---------------------------------------------------------------------------
# 4. fcf_formula field stays dead
# ---------------------------------------------------------------------------


def test_dcf_result_does_not_resurrect_fcf_formula_fields():
    """Phase B removed fcf_formula and fcf_formula_warning from DCFResult.

    The original screenshot showed a warning whose direction was reversed
    ("Implied price may be overstated 10-20%" — actually understated). The
    fix was to delete the warning, not to fix its copy. This guard makes
    sure the field doesn't sneak back via "add a small status flag".
    """
    from finrobot.engine.models.financial import DCFResult

    forbidden = {"fcf_formula", "fcf_formula_warning"}
    present = forbidden & set(DCFResult.model_fields)
    assert not present, (
        f"DCFResult has deleted fields back: {sorted(present)}. "
        "If you need this signal, add it to assumption_provenance instead "
        "and update tests/audit/test_dcf_red_lines.py."
    )


# ---------------------------------------------------------------------------
# 5. Pipeline financial_modeling step uses seed_dcf_inputs, not a param_agent
# ---------------------------------------------------------------------------


def test_ic_memo_financials_step_uses_seed_dcf_inputs():
    """The financial_analysis step in ic_memo.py must construct DCFInputs
    exclusively via ``seed_dcf_inputs`` — never via an LLM ``dcf_param_agent``.

    The IC memo pipeline runs DCF + LBO inline, so it is subject to the same
    architecture red-line #5 as the standalone DCF and equity-research
    pipelines.
    """
    src = (REPO_ROOT / "finrobot" / "engine" / "pipelines" / "ic_memo.py").read_text()

    func_marker = "async def _execute_ic_financials("
    assert func_marker in src, (
        "_execute_ic_financials function missing from ic_memo.py — did you rename it?"
    )
    start = src.index(func_marker)
    next_func = src.find("\nasync def ", start + 1)
    if next_func == -1:
        next_func = src.find("\ndef ", start + 1)
    if next_func == -1:
        next_func = len(src)
    body = src[start:next_func]

    assert "seed_dcf_inputs" in body, (
        "_execute_ic_financials must call seed_dcf_inputs() to construct DCFInputs."
    )

    body_no_docstring = re.sub(r'"""[\s\S]*?"""', "", body, count=1)
    banned = {
        "dcf_param_agent": (
            "dcf_param_agent reintroduces the LLM-picks-DCF-numbers path. "
            "Use seed_dcf_inputs instead."
        ),
        "output_type=DCFInputs": (
            "Agent(output_type=DCFInputs) is forbidden by CLAUDE.md red-line #5."
        ),
    }
    offenders = [tok for tok in banned if tok in body_no_docstring]
    assert not offenders, "\n".join(
        f"_execute_ic_financials body contains banned token '{tok}': {banned[tok]}"
        for tok in offenders
    )


def test_equity_research_financial_modeling_uses_seed_dcf_inputs():
    """The financial_modeling step in equity_research.py must construct
    DCFInputs exclusively via ``seed_dcf_inputs``.

    Previously this step ran a ``param_agent`` (LLM with ``output_type=DCFInputs``)
    that picked DCF numbers from a prompt. CLAUDE.md red-line #5 forbids that
    path; numbers must trace to real filings or Damodaran industry medians.

    This guard greps the source of ``_execute_financial_modeling`` for:
      • Required token: ``seed_dcf_inputs`` must be called inside the function.
      • Banned tokens: ``param_agent`` and ``output_type=DCFInputs`` must not
        appear anywhere in the file — both were the LLM-selects-numbers path.
    """
    src = (REPO_ROOT / "finrobot" / "engine" / "pipelines" / "equity_research.py").read_text()

    # Locate the function body via a coarse marker.
    func_marker = "async def _execute_financial_modeling("
    assert func_marker in src, (
        "_execute_financial_modeling function missing from equity_research.py — did you rename it?"
    )

    start = src.index(func_marker)
    # End at the next top-level async def or def, whichever comes first.
    next_func = src.find("\nasync def ", start + 1)
    if next_func == -1:
        next_func = len(src)
    body = src[start:next_func]

    assert "seed_dcf_inputs" in body, (
        "_execute_financial_modeling must call seed_dcf_inputs() to construct "
        "DCFInputs. Direct ``DCFInputs(...)`` construction or LLM ``param_agent`` "
        "is forbidden (CLAUDE.md red-line #5)."
    )

    # Banned patterns must not appear in the *function body itself* (docstring
    # references to the deleted path elsewhere in the file are fine — they
    # explain why we removed it). Strip the docstring then look for the LLM
    # pattern markers.
    body_no_docstring = re.sub(r'"""[\s\S]*?"""', "", body, count=1)

    banned_in_body = {
        "param_agent": (
            "param_agent reintroduces the LLM-picks-DCF-numbers path. "
            "Remove and route through seed_dcf_inputs instead."
        ),
        "output_type=DCFInputs": (
            "Agent(output_type=DCFInputs) makes the LLM produce DCF parameters. "
            "That is forbidden by CLAUDE.md red-line #5."
        ),
    }
    offenders = [tok for tok in banned_in_body if tok in body_no_docstring]
    assert not offenders, "\n".join(
        f"_execute_financial_modeling body contains banned token '{tok}': {banned_in_body[tok]}"
        for tok in offenders
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
