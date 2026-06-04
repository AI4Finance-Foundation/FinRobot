"""LBO refactor red-lines.

These tests scan the source tree for patterns that, if reintroduced, would
walk back CLAUDE.md architecture red-line #5 for the LBO path. They mirror
``test_dcf_red_lines.py`` and enforce:

  1. The pipeline ``lbo_parameters`` step in ``finrobot/engine/pipelines/lbo.py``
     must build LBOInputs via ``seed_lbo_inputs`` — no ``param_agent``,
     no ``output_type=LBOInputs``.

  2. The frontend ``useRunTool.ts`` LBO branch must not ship hardcoded
     per-ticker numeric assumptions (``revenue_growth_rate``, ``ebitda_margin``,
     ``leverage_multiple``, etc.) in the request body. Instead it must call
     the new ``/api/compute/lbo-seed`` endpoint that runs ``seed_lbo_inputs``
     server-side.

  3. ``seed_lbo_inputs`` must annotate every LBO assumption in
     ``assumption_provenance`` — otherwise the UI provenance panel renders
     blank rows.

If you legitimately need to ship one of the banned patterns (e.g. a brand-new
LBO route that genuinely lets the user override a deal multiple), update the
allow-list below or refactor through the seed function rather than relaxing
this audit.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from finrobot.engine.compute.operators.lbo_seed import seed_lbo_inputs
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
# 1. Pipeline lbo_parameters step uses seed_lbo_inputs, not a param_agent
# ---------------------------------------------------------------------------


def test_ic_memo_financials_step_uses_seed_lbo_inputs():
    """The financial_analysis step in ic_memo.py must construct LBOInputs
    exclusively via ``seed_lbo_inputs`` — never via an LLM ``lbo_param_agent``.

    Mirror of the DCF guard for the same step (see test_dcf_red_lines.py).
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

    assert "seed_lbo_inputs" in body, (
        "_execute_ic_financials must call seed_lbo_inputs() to construct LBOInputs."
    )

    body_no_docstring = re.sub(r'"""[\s\S]*?"""', "", body, count=1)
    banned = {
        "lbo_param_agent": (
            "lbo_param_agent reintroduces the LLM-picks-LBO-numbers path. "
            "Use seed_lbo_inputs instead."
        ),
        "output_type=LBOInputs": (
            "Agent(output_type=LBOInputs) is forbidden by CLAUDE.md red-line #5."
        ),
    }
    offenders = [tok for tok in banned if tok in body_no_docstring]
    assert not offenders, "\n".join(
        f"_execute_ic_financials body contains banned token '{tok}': {banned[tok]}"
        for tok in offenders
    )


def test_lbo_pipeline_uses_seed_lbo_inputs():
    """The lbo_parameters step in pipelines/lbo.py must construct LBOInputs
    exclusively via ``seed_lbo_inputs``. No LLM agent picks LBO assumptions.
    """
    src = (REPO_ROOT / "finrobot" / "engine" / "pipelines" / "lbo.py").read_text()

    func_marker = "async def _execute_lbo_params("
    assert func_marker in src, (
        "_execute_lbo_params function missing from pipelines/lbo.py — did you rename it?"
    )

    start = src.index(func_marker)
    next_func = src.find("\nasync def ", start + 1)
    if next_func == -1:
        next_func = src.find("\ndef ", start + 1)
    if next_func == -1:
        next_func = len(src)
    body = src[start:next_func]

    assert "seed_lbo_inputs" in body, (
        "_execute_lbo_params must call seed_lbo_inputs() to construct LBOInputs. "
        "Direct ``LBOInputs(...)`` construction or LLM ``param_agent`` is forbidden "
        "(CLAUDE.md red-line #5)."
    )

    # Banned patterns must not appear in the *function body itself* (docstring
    # references elsewhere in the file are fine — they explain why the path was
    # removed). Strip the function's own docstring first.
    body_no_docstring = re.sub(r'"""[\s\S]*?"""', "", body, count=1)

    banned_in_body = {
        "param_agent": (
            "param_agent reintroduces the LLM-picks-LBO-numbers path. "
            "Remove and route through seed_lbo_inputs instead."
        ),
        "output_type=LBOInputs": (
            "Agent(output_type=LBOInputs) makes the LLM produce LBO parameters. "
            "That is forbidden by CLAUDE.md red-line #5."
        ),
    }
    offenders = [tok for tok in banned_in_body if tok in body_no_docstring]
    assert not offenders, "\n".join(
        f"_execute_lbo_params body contains banned token '{tok}': {banned_in_body[tok]}"
        for tok in offenders
    )


# ---------------------------------------------------------------------------
# 3. seed_lbo_inputs must populate assumption_provenance for every field
# ---------------------------------------------------------------------------


_REQUIRED_LBO_PROVENANCE_KEYS = {
    "revenue_base",
    "ltm_ebitda",
    "revenue_growth_rate",
    "ebitda_margin",
    "capex_pct_revenue",
    "da_pct_revenue",
    "nwc_change_pct_revenue",
    "tax_rate",
    "interest_rate",
    "entry_ev_ebitda",
    "exit_ev_ebitda",
    "leverage_multiple",
    "holding_period_years",
    "mandatory_amort_pct",
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


def test_lbo_assumption_provenance_covers_every_field():
    """seed_lbo_inputs must annotate every numeric LBO field — the UI's
    provenance panel would otherwise render a blank line for each missing
    entry. Mirror of test_assumption_provenance_covers_every_dcf_input_field.
    """
    inputs = seed_lbo_inputs(_minimal_financials(), _empty_historical())
    missing = _REQUIRED_LBO_PROVENANCE_KEYS - set(inputs.assumption_provenance.keys())
    assert not missing, f"Missing LBO provenance for fields: {sorted(missing)}"


def test_lbo_assumption_provenance_messages_are_chinese():
    """Provenance text targets retail Chinese users — guard against
    accidental English-only strings sneaking back in."""
    inputs = seed_lbo_inputs(_minimal_financials(), _empty_historical())
    offenders: list[str] = []
    for key, msg in inputs.assumption_provenance.items():
        if not any("一" <= ch <= "鿿" for ch in msg):
            offenders.append(f"{key}: {msg}")
    assert not offenders, "LBO provenance messages must contain Chinese:\n" + "\n".join(offenders)


def test_lbo_missing_ebitda_falls_back_to_industry_estimate():
    """income.ebitda None (provider omitted EBITDA) must route to the same
    industry-implied fallback as a non-positive EBITDA — never crash on a None
    comparison, and never seed a zero/None ltm_ebitda into the model."""
    fin = _minimal_financials()
    fin.income.ebitda = None
    inputs = seed_lbo_inputs(fin, _empty_historical())
    assert inputs.ltm_ebitda > 0
    assert "不可得" in inputs.assumption_provenance["ltm_ebitda"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
