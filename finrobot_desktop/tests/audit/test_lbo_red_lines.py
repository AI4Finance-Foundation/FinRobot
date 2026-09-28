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
    DataProvenance,
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


def test_lbo_assumption_provenance_messages_are_english():
    """Provenance text targets English-speaking analysts — guard against
    Chinese strings sneaking back in."""
    inputs = seed_lbo_inputs(_minimal_financials(), _empty_historical())
    offenders: list[str] = []
    for key, msg in inputs.assumption_provenance.items():
        if any("一" <= ch <= "鿿" for ch in msg) or not any(
            ch.isascii() and ch.isalpha() for ch in msg
        ):
            offenders.append(f"{key}: {msg}")
    assert not offenders, "LBO provenance messages must be readable English:\n" + "\n".join(
        offenders
    )


def _financials_with_basis(period_basis: str) -> FinancialData:
    fin = _minimal_financials()
    fin.provenance = DataProvenance(provider="test", period_basis=period_basis)
    return fin


def test_lbo_revenue_ebitda_basis_labelled_honestly():
    """revenue_base / ltm_ebitda read ``income.revenue`` / ``income.ebitda``,
    which are TTM by default. Hardcoding "latest annual …" mislabels TTM as a
    fiscal-year figure — exactly the口径 error CLAUDE.md forbids and the same
    bug dcf_seed already fixed (it reads ``provenance.period_basis``). Mirror
    that honesty here.
    """
    ttm = seed_lbo_inputs(_financials_with_basis("ttm"), _empty_historical())
    assert "annual" not in ttm.assumption_provenance["revenue_base"].lower()
    assert "annual" not in ttm.assumption_provenance["ltm_ebitda"].lower()
    assert "TTM" in ttm.assumption_provenance["revenue_base"]
    assert "TTM" in ttm.assumption_provenance["ltm_ebitda"]

    # An issuer that genuinely reports on an annual basis should still say so.
    annual = seed_lbo_inputs(_financials_with_basis("annual"), _empty_historical())
    assert "annual" in annual.assumption_provenance["revenue_base"].lower()
    assert "annual" in annual.assumption_provenance["ltm_ebitda"].lower()


def _out_of_band_industry(monkeypatch: pytest.MonkeyPatch, rate: float) -> None:
    """Force seed_lbo_inputs to see an industry effective tax rate of ``rate``.

    No production Damodaran default currently falls outside the [10%, 40%] LBO
    clamp band, so the clamp is silent today — but a future data refresh could
    make it bind. This patches the resolved IndustryDefault so the disclosure is
    verified regardless of current data.
    """
    import dataclasses

    from finrobot.engine.compute.operators import lbo_seed as _mod
    from finrobot.engine.data.industry_defaults import get_industry_default

    base = get_industry_default("Software (System & Application)")
    patched = dataclasses.replace(base, effective_tax_rate=rate)
    monkeypatch.setattr(_mod, "get_industry_default", lambda _industry: patched)


def test_lbo_tax_rate_clamp_cap_disclosed(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the industry rate exceeds the cap, the LBO uses the clamped value AND
    the provenance reports that SAME clamped value while disclosing the raw rate
    + the cap — never implying the displayed number is the raw industry figure.

    Audit-trail invariant: any clamped/transformed input must be disclosed at the
    value actually used, never the raw (BUG-023 honesty convention).
    """
    from finrobot.engine.compute.operators.lbo_seed import LBO_TAX_RATE_CAP

    raw = 0.52
    assert raw > LBO_TAX_RATE_CAP  # precondition: clamp binds
    _out_of_band_industry(monkeypatch, raw)

    inputs = seed_lbo_inputs(_minimal_financials(), _empty_historical())
    prov = inputs.assumption_provenance["tax_rate"]

    # (a) DCF/LBO uses the clamped cap, not the 52% raw rate
    assert inputs.tax_rate == pytest.approx(LBO_TAX_RATE_CAP)
    # (b) provenance reports the SAME clamped value (displayed == used)
    assert f"{LBO_TAX_RATE_CAP:.1%}" in prov
    # ...and discloses the dropped raw rate + the cap
    assert "52.0%" in prov
    assert "clamped to the" in prov
    assert "cap" in prov


def test_lbo_tax_rate_clamp_floor_disclosed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Symmetric floor case: a near-zero industry aggregate is clamped up and the
    provenance discloses the raw rate + the floor."""
    from finrobot.engine.compute.operators.lbo_seed import LBO_TAX_RATE_FLOOR

    raw = 0.04
    assert raw < LBO_TAX_RATE_FLOOR
    _out_of_band_industry(monkeypatch, raw)

    inputs = seed_lbo_inputs(_minimal_financials(), _empty_historical())
    prov = inputs.assumption_provenance["tax_rate"]

    assert inputs.tax_rate == pytest.approx(LBO_TAX_RATE_FLOOR)
    assert f"{LBO_TAX_RATE_FLOOR:.1%}" in prov
    assert "4.0%" in prov
    assert "clamped to the" in prov
    assert "floor" in prov


def test_lbo_tax_rate_in_band_no_clamp_note(monkeypatch: pytest.MonkeyPatch) -> None:
    """In-band industry rate is used as-is with no clamp disclosure."""
    _out_of_band_industry(monkeypatch, 0.21)

    inputs = seed_lbo_inputs(_minimal_financials(), _empty_historical())
    prov = inputs.assumption_provenance["tax_rate"]

    assert inputs.tax_rate == pytest.approx(0.21)
    assert "21.0%" in prov
    assert "clamped" not in prov


def _historical_with_nwc(cwc: list[float], revenue: list[float]) -> HistoricalMetrics:
    """Minimal history carrying only revenue + ΔNWC — every other series stays
    empty so the corresponding assumption falls through to industry, isolating
    the NWC clamp path."""
    hist = _empty_historical()
    hist.revenue = revenue
    hist.change_in_working_capital = cwc
    return hist


def test_lbo_nwc_clamp_no_growth_year_falls_back_to_clamped_median() -> None:
    """Batch-3 fallback path: FLAT revenue → no revenue-growth year → no marginal
    ratio is derivable, so a bound ±10% band keeps the clamped value AND discloses
    the pre-clamp trailing median (batch-0 BUG-023 disclosure, unchanged)."""
    # ΔNWC/revenue = -15% every year, revenue flat → -median = +15% → clamped to
    # +10%; Δrev = 0 blocks the marginal ratio → honest fallback.
    hist = _historical_with_nwc([-1.5e9, -1.5e9, -1.5e9], [1e10, 1e10, 1e10])
    inputs = seed_lbo_inputs(_minimal_financials(), hist)
    prov = inputs.assumption_provenance["nwc_change_pct_revenue"]
    assert inputs.nwc_change_pct_revenue == pytest.approx(0.10)
    # BACKLOG A6⑤: wording reads analyst prose, not dev jargon — every number
    # (10.0% used / 15.0% pre-clamp trailing average) is unchanged.
    assert prov.startswith("10.0% of revenue (capped from a trailing")
    assert "average of 15.0% of revenue" in prov
    assert "marginal NWC ratio" not in prov


def test_lbo_nwc_clamp_degrades_to_marginal_ratio() -> None:
    """Batch-3 mirror of the dcf_seed fix: when the ±10% band binds and revenue
    grew (a marginal ratio is derivable), the LBO degrades to marginal ratio × its
    single steady-state revenue growth instead of holding the clamped median flat.
    """
    # 3%/yr revenue with a NWC build ~13% of the LEVEL → per-year median 13.2%
    # (clamps band) and build/Δrev ≈ 4.67 (clamps marginal to 60%). LBO steady-
    # state growth = trailing CAGR 3% → degraded = 60% × 3% = 1.8%.
    hist = _historical_with_nwc([-14e9, -14e9, -14e9, -14e9], [100e9, 103e9, 106e9, 109e9])
    hist.cagr_revenue = 0.03
    inputs = seed_lbo_inputs(_minimal_financials(), hist)
    prov = inputs.assumption_provenance["nwc_change_pct_revenue"]
    assert inputs.nwc_change_pct_revenue == pytest.approx(0.60 * 0.03)
    # BACKLOG A6⑤: wording reads analyst prose, not dev jargon — every number
    # (13.2% pre-clamp trailing average / 60.0% marginal ratio used / raw
    # marginal it was capped down from / 3.0% steady-state growth) unchanged.
    assert "ran 13.2% of revenue" in prov
    assert "too high to be a sustainable, ongoing drag" in prov
    assert "marginal NWC ratio, 60.0% of each new revenue dollar (capped down from a raw" in prov
    assert "applied to the 3.0% steady-state revenue growth rate" in prov


def test_lbo_nwc_in_band_is_byte_identical() -> None:
    """In-band ΔNWC never carries a clamp/degradation disclosure (BACKLOG A6⑤
    reworded the prose to analyst language; this pins the invariant)."""
    hist = _historical_with_nwc([-5e8, -5e8, -5e8], [1e10, 1e10, 1e10])  # -5% → no clamp
    inputs = seed_lbo_inputs(_minimal_financials(), hist)
    prov = inputs.assumption_provenance["nwc_change_pct_revenue"]
    assert "capped" not in prov
    assert "marginal NWC ratio" not in prov
    assert prov.endswith(
        "average change in working capital as % of revenue; a positive figure means "
        "working capital is absorbing cash)"
    )


def test_lbo_interest_rate_cap_disclosed() -> None:
    """cost-of-debt + 2% above the 15% ceiling: the LBO uses 15% AND provenance
    discloses the pre-cap arithmetic, so 'cost + 2%' can never imply a rate above
    the ceiling the model uses (BUG-023)."""
    fin = _minimal_financials()
    fin.income.interest_expense = 1.4e8  # 14% cost of debt on 1e9 total debt
    inputs = seed_lbo_inputs(fin, _empty_historical())
    prov = inputs.assumption_provenance["interest_rate"]
    assert inputs.interest_rate == pytest.approx(0.15)
    assert prov.startswith("15.0%")
    assert "= 16.0%" in prov
    assert "capped at the 15% LBO-debt ceiling" in prov


def test_lbo_missing_ebitda_falls_back_to_industry_estimate():
    """income.ebitda None (provider omitted EBITDA) must route to the same
    industry-implied fallback as a non-positive EBITDA — never crash on a None
    comparison, and never seed a zero/None ltm_ebitda into the model."""
    fin = _minimal_financials()
    fin.income.ebitda = None
    inputs = seed_lbo_inputs(fin, _empty_historical())
    assert inputs.ltm_ebitda > 0
    assert "unavailable" in inputs.assumption_provenance["ltm_ebitda"]


def test_lbo_loss_maker_profitability_fallback_is_disclosed():
    fin = _minimal_financials()
    fin.income.ebitda = -100_000_000
    hist = _empty_historical().model_copy(
        update={
            "years": [2022, 2023, 2024],
            "ebitda_margin": [-0.30, -0.20, -0.10],
        }
    )

    inputs = seed_lbo_inputs(fin, hist)

    assert inputs.ltm_ebitda > 0
    assert "non-positive" in inputs.assumption_provenance["ltm_ebitda"]
    assert inputs.ebitda_margin > 0
    assert "-20.0%" in inputs.assumption_provenance["ebitda_margin"]
    assert "non-positive" in inputs.assumption_provenance["ebitda_margin"]


def test_all_standalone_valuation_seeders_fx_normalize_before_seeding():
    """Mechanical gate — flywheel escalation for the BUG-073 sibling-escape that
    recurred a 3rd time (equity_research fixed the leak via data_collection;
    standalone dcf / ddm / lbo were each found unfixed: Critical-1 / #3).

    Every standalone valuation pipeline executor that seeds a model from the
    fetched snapshot MUST FX-normalize a foreign issuer to USD *before* seeding —
    otherwise revenue/EBITDA/debt (reporting ccy) mix with the USD quote and the
    entry/target/exit land in different currencies on one axis. A NEW valuation
    pipeline that forgets this fails here instead of shipping a cross-currency
    target. (equity_research's _execute_financial_modeling is covered by its own
    BUG-073 currency tests.)
    """
    import inspect

    from finrobot.engine.pipelines import dcf, ddm, ic_memo, lbo

    cases = [
        (dcf._execute_dcf_calc, "normalize_financials_to_usd"),
        (ddm._execute_ddm_seed, "normalize_financialdata_to_usd"),
        (lbo._execute_lbo_params, "normalize_financials_to_usd"),
        (ic_memo._execute_ic_financials, "normalize_financials_to_usd"),
    ]
    for fn, token in cases:
        body = inspect.getsource(fn)
        assert token in body, (
            f"{fn.__module__}.{fn.__name__} must FX-normalize the snapshot before "
            f"seeding (missing '{token}') — a foreign issuer would otherwise mix "
            f"reporting-currency model inputs with a USD quote (BUG-073 family)."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
