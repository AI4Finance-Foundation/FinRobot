"""``_summary_text`` surfaces a single-method artifact's OWN deterministic
calc-step narrative ("DDM implies $X per share … cost of equity Y% …") as the
summary — every number traced to the compute layer.

``summary_steps`` is a PRIORITY list (first non-empty wins), NOT a concatenation:
the LLM ``*_narrative`` step is only a fallback, because it balloons into a full
report that restates financial figures (a contract-① drift surface) and
editorialises a single-method recommendation. ``format_summary`` (the generic
"# FinRobot Analysis Report" that concatenates every step — for valuation
pipelines it led with the historical_data table and truncated the model result
away) is the last resort, kept for pipelines that declare no summary_steps
(equity_research).
"""

from __future__ import annotations

from typing import Any, cast

from finrobot.artifact.builders import _summary_text
from finrobot.engine.pipelines.base import PipelineResult

_CALC = (
    "DDM implies $319.89 per share (10.3% upside vs $290.00). "
    "Cost of equity: 8.7%. Terminal growth: 3.0%. Sensitivity range: $280–$360."
)
# Mimics the real ddm_narrative step: a verbose full report that restates
# financials and editorialises a call — exactly what must NOT become the summary.
_NARRATIVE = (
    "# Equity Research Report\n\n**Recommendation:** SELL\n\n"
    "JPM's dividend trajectory supports the model; revenue was $186.94B."
)
_STEPS = ("ddm_calc", "ddm_narrative")


def _result(*, with_calc: bool = True) -> PipelineResult:
    steps = {
        # The big generic financials dump format_summary would lead with.
        "historical_data": "## Financial Summary\n- Revenue: $186.94B (USD, TTM)",
        "ddm_narrative": _NARRATIVE,
    }
    if with_calc:
        steps["ddm_calc"] = _CALC
    return PipelineResult(steps=steps)


def test_summary_is_the_deterministic_calc_line() -> None:
    summary = _summary_text(_result(), {}, cast(Any, None), summary_steps=_STEPS)
    assert summary.startswith("DDM implies $319.89 per share")
    assert "Cost of equity: 8.7%" in summary
    # The generic report scaffolding and the financials dump must NOT leak in.
    assert "# FinRobot Analysis Report" not in summary
    assert "Financial Summary" not in summary


def test_calc_step_wins_llm_narrative_not_surfaced() -> None:
    # Priority list, not concatenation: with the calc step present the verbose
    # LLM narrative (restated financials + a SELL call) must NOT appear.
    summary = _summary_text(_result(), {}, cast(Any, None), summary_steps=_STEPS)
    assert summary == _CALC
    assert "Recommendation:" not in summary
    assert "Equity Research Report" not in summary


def test_narrative_is_fallback_when_calc_step_missing() -> None:
    # If the deterministic calc step is empty/missing, fall back to the next
    # priority step (the LLM narrative) rather than the generic report dump.
    summary = _summary_text(_result(with_calc=False), {}, cast(Any, None), summary_steps=_STEPS)
    assert "Equity Research Report" in summary
    assert "# FinRobot Analysis Report" not in summary


def test_no_summary_steps_falls_back_to_full_report() -> None:
    # equity_research declares no summary_steps → keeps the legacy full report.
    summary = _summary_text(_result(), {}, cast(Any, None))
    assert "# FinRobot Analysis Report" in summary


def test_unknown_step_names_fall_back_to_full_report() -> None:
    summary = _summary_text(_result(), {}, cast(Any, None), summary_steps=("nope", "x"))
    assert "# FinRobot Analysis Report" in summary


def test_withheld_overrides_steps() -> None:
    summary = _summary_text(
        _result(), {"valuation_withheld": True}, cast(Any, None), summary_steps=_STEPS
    )
    assert "withheld" in summary.lower()
    assert "DDM implies" not in summary


def test_equity_research_fairly_valued_keeps_full_summary_not_numeric_audit_stub() -> None:
    """⑤ JPM dial-withhold: an in-band bank (basis leads "FAIRLY VALUED") must NOT
    collapse to a 68-char stub misattributed to "numeric audit". It keeps the full
    data-collection summary (parity with a published bank like BAC) and prefixes a
    correctly-attributed "fairly valued" note."""
    structured = {
        "valuation_withheld": True,
        "withheld_reason": "valuation_synthesis_dial",
        "thesis": {
            "price_target_basis": "FAIRLY VALUED: price $334.60 sits within the band [$272, $369]."
        },
    }
    # equity_research declares NO summary_steps.
    summary = _summary_text(_result(), structured, cast(Any, None))
    assert "numeric audit" not in summary.lower()  # the misattribution is gone
    assert "fairly valued" in summary.lower()
    assert "# FinRobot Analysis Report" in summary  # full data summary retained (BAC parity)


def test_equity_research_dial_withhold_attributes_to_synthesis_not_audit() -> None:
    """A genuine dial withhold (single method far from market / divergence, no FAIRLY
    VALUED basis) attributes to the valuation synthesis, never the numeric audit."""
    structured = {
        "valuation_withheld": True,
        "withheld_reason": "valuation_synthesis_dial",
        "thesis": {"price_target_basis": "POINT TARGET WITHHELD: single method 3.2x market."},
    }
    summary = _summary_text(_result(), structured, cast(Any, None))
    assert "numeric audit" not in summary.lower()
    assert "valuation synthesis" in summary.lower()
    assert "# FinRobot Analysis Report" in summary


def test_numeric_audit_blocked_still_reads_numeric_audit() -> None:
    """The numeric-audit-blocked path keeps its correct "numeric audit" attribution."""
    structured = {"valuation_withheld": True, "withheld_reason": "numeric_audit_blocked_field"}
    summary = _summary_text(_result(), structured, cast(Any, None), summary_steps=_STEPS)
    assert "Valuation withheld by numeric audit" in summary
    assert "DDM implies" not in summary  # standalone still suppresses the withheld number


def test_build_ddm_artifact_summary_is_calc_line_not_generic_report() -> None:
    """End-to-end through the real builder: build_ddm_artifact wires
    summary_steps=("ddm_calc", "ddm_narrative") so the persisted artifact summary
    is the deterministic DDM calc line — never the generic report, never the
    verbose LLM narrative.
    """
    from datetime import datetime, timezone

    from finrobot.artifact.builders import build_ddm_artifact
    from finrobot.engine.models.financial import (
        BalanceSheet,
        FinancialData,
        IncomeStatement,
        MarketData,
        ValuationMetrics,
    )

    fd = FinancialData(
        ticker="JPM",
        timestamp=datetime(2026, 6, 24, tzinfo=timezone.utc),
        income=IncomeStatement(revenue=186_940_000_000, ebitda=83_820_000_000),
        balance=BalanceSheet(total_debt=1_233_000_000_000, total_cash=1_864_000_000_000),
        market=MarketData(
            market_cap=895_000_000_000,
            shares_outstanding=2_680_000_000,
            current_price=290.0,
        ),
        valuation=ValuationMetrics(),
        data_source="fake",
    )
    result = PipelineResult(
        steps={
            "historical_data": "## Financial Summary\n- Revenue: $186.94B (USD, TTM)",
            "ddm_calc": _CALC,
            "ddm_narrative": _NARRATIVE,
        },
        structured_data={"historical_data": fd},
    )

    art = build_ddm_artifact(result, "JPM", cast(Any, None))

    assert art.outputs.summary_text == _CALC
    assert "# FinRobot Analysis Report" not in art.outputs.summary_text
    assert "Recommendation:" not in art.outputs.summary_text
