"""The equity_research artifact builder runs the numeric-audit gate (design §7, A):
findings surface into warnings + structured.numeric_audit; a blocked_field
(category-error / dimensionally-corrupt number) flags the report ``caveated`` and
withholds the price TARGET — the directional verdict is PRESERVED (corrupt data
withholds the value, never the judgment; no "REVIEW" verdict any more). A clean
report renders byte-identically.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest

from finrobot.artifact.builders import (
    build_comps_artifact,
    build_dcf_artifact,
    build_equity_research_artifact,
    build_ic_memo_artifact,
    build_lbo_artifact,
)
from finrobot.engine.models.financial import (
    CompanyFinancials,
    DCFInputs,
    DCFResult,
    FinancialData,
    ICFinancials,
    IncomeStatement,
    LBOResult,
    LBOYear,
    MarketData,
    PeerComps,
    ValuationMetrics,
)
from finrobot.engine.pipelines.base import PipelineResult

UTC = timezone.utc


def _fd(
    *,
    ticker: str = "X",
    industry: str | None = None,
    net_income: float | None = 20e9,
    ev_ebitda: float | None = None,
    reporting_currency: str = "USD",
    quote_currency: str = "USD",
    ttm_ends: list[date] | None = None,
) -> FinancialData:
    return FinancialData(
        ticker=ticker,
        timestamp=datetime(2026, 6, 6, 10, 0, 0, tzinfo=UTC),
        income=IncomeStatement(revenue=100e9, net_income=net_income),
        market=MarketData(
            market_cap=500e9, shares_outstanding=5e9, current_price=100.0, industry=industry
        ),
        valuation=ValuationMetrics(ev_ebitda=ev_ebitda),
        reporting_currency=reporting_currency,
        quote_currency=quote_currency,
        ttm_quarter_ends=ttm_ends or [],
        data_source="fake",
    )


# A genuinely-broken TTM (missing Dec quarter → 182-day gap → every ratio corrupt) is the
# canonical *real* blocked_field used to exercise the withhold mechanism, replacing the old
# "bank EV" shortcut: a bank EV is now only a ``review`` caveat (the cash-flow methods and
# DDM/P-B headline never consume it), whereas ttm_period (like currency_caliber) still emits
# ``blocked_field``, so the withhold mechanism is unchanged for real dimensional corruption.
_BROKEN_TTM = [date(2026, 3, 31), date(2025, 9, 30), date(2025, 6, 30), date(2025, 3, 31)]


def _result(fd: FinancialData, *, recommendation: str = "BUY", price_target: float | None = 100.0):
    return PipelineResult(
        steps={"data_collection": "ok", "thesis": "Price target $100"},
        structured_data={
            "data_collection": fd,
            "thesis": {
                "recommendation": recommendation,
                "price_target": price_target,
                "tagline": "t",
            },
        },
    )


def _dcf_result() -> DCFResult:
    inputs = DCFInputs(
        revenue_base=100e9,
        revenue_growth_rates=[0.03, 0.03, 0.02, 0.02, 0.02],
        ebitda_margin=0.30,
        capex_pct_revenue=0.04,
        nwc_pct_revenue=0.01,
        tax_rate=0.21,
        risk_free_rate=0.04,
        beta=1.0,
        equity_risk_premium=0.055,
        cost_of_debt=0.05,
        debt_ratio=0.20,
        terminal_growth_rate=0.025,
        shares_outstanding=5e9,
        net_debt=10e9,
        da_pct_revenue=0.03,
    )
    return DCFResult(
        cost_of_equity=0.095,
        wacc=0.082,
        projection_years=5,
        projected_revenue=[103e9, 106e9, 108e9, 110e9, 112e9],
        projected_ebitda=[30e9] * 5,
        projected_fcf=[10e9] * 5,
        terminal_value=200e9,
        pv_terminal=150e9,
        pv_fcf_total=40e9,
        enterprise_value=190e9,
        equity_value=180e9,
        implied_price=120.0,
        inputs=inputs,
    )


def _build(result, ticker="X"):
    return build_equity_research_artifact(result, ticker, cast(Any, None))


def test_clean_report_publishable_unchanged():
    art = _build(_result(_fd(industry="Software", ev_ebitda=18.0)))
    audit = art.outputs.structured["numeric_audit"]
    assert audit["artifact_status"] == "publishable"
    assert audit["withhold_valuation"] is False
    assert audit["findings"] == []
    # Rating / target untouched.
    assert art.outputs.structured["thesis"]["recommendation"] == "BUY"
    assert art.outputs.structured["thesis"]["price_target"] == 100.0
    assert art.outputs.llm_narrative["recommendation"] == "BUY"


def test_bank_ev_caveats_but_target_ships():
    # A bank's EV is a category error, but flagged ``review`` (caveat), NOT
    # ``blocked_field`` — the bank's published valuation never consumes EV (cash-flow
    # methods suppressed upstream, headline anchors on DDM/P-B), so the EV finding banners
    # the report (transparency) but the price target SHIPS. This is exactly what lets a
    # clean bank's DDM target publish instead of being nulled by the EV gate (slice-3 of
    # the bank-DDM change; previously this case withheld the target).
    art = _build(_result(_fd(ticker="JPM", industry="Banks - Diversified", ev_ebitda=8.0)), "JPM")
    audit = art.outputs.structured["numeric_audit"]
    assert audit["artifact_status"] == "caveated"
    assert audit["withhold_valuation"] is False
    ev = next(f for f in audit["findings"] if f["check"] == "financial_sector_ev_meaningless")
    assert ev["severity"] == "review"
    # Banner still surfaces (the EV-is-meaningless-for-a-bank disclosure is informative).
    assert any("financial_sector_ev_meaningless" in w for w in art.outputs.warnings)
    # Target + verdict both ship — nothing withheld.
    assert art.outputs.structured["thesis"]["recommendation"] == "BUY"
    assert art.outputs.structured["thesis"]["price_target"] == 100.0
    assert art.outputs.llm_narrative["recommendation"] == "BUY"
    assert not art.outputs.structured.get("valuation_withheld")
    assert "Valuation withheld" not in art.outputs.summary_text


def test_synthesis_dial_withhold_sets_top_level_flag_like_numeric_audit():
    """The synthesis dial withholds the POINT on its own terms (single-method
    out-of-calibration / method divergence — RIVN's path), independent of the
    numeric-audit gate. That withheld state must set the SAME top-level
    valuation_withheld=True as the numeric-audit path (JPM): the flag is the
    cause-independent 'point withheld' signal _is_withheld / _summary_text read.
    Before the fix it stayed None on the dial path while True on the audit path —
    identical withheld states reading differently downstream."""
    from finrobot.engine.compute.operators.valuation_synthesis import synthesize_valuations
    from finrobot.engine.models.financial import ValuationMethod

    # lone comps_pb far below market → outside the [0.5x, 2x] single-method band →
    # the dial withholds the point (the verdict still ships directionally).
    # current_price matches _fd's market block (100.0): in production the synthesis
    # price IS financial_data.market.current_price, and the artifact's single-as-of
    # gate (_assert_price_snapshot_coherent) rejects a synthesis price that trails
    # the market block, so the mock must keep them coherent.
    vs = synthesize_valuations(
        [
            ValuationMethod(
                name="comps_pb", low=3.92, mid=4.61, high=5.30, confidence=0.6, source="PB"
            )
        ],
        current_price=100.0,
    )
    assert vs.valuation_withheld is True  # precondition: the dial withheld
    # clean financials → numeric audit does NOT block (isolates the dial path)
    result = _result(_fd(ticker="RIVN", industry="Software"), price_target=None)
    result.structured_data["valuation_synthesis"] = vs
    art = _build(result, "RIVN")
    assert art.outputs.structured["numeric_audit"]["withhold_valuation"] is False
    assert art.outputs.structured["valuation_withheld"] is True


def test_loss_maker_caveated_keeps_target():
    # review (not blocked) → caveated banner but the DCF target survives.
    art = _build(_result(_fd(industry="Software", net_income=-1e9)))
    audit = art.outputs.structured["numeric_audit"]
    assert audit["artifact_status"] == "caveated"
    assert audit["withhold_valuation"] is False
    assert art.outputs.structured["thesis"]["price_target"] == 100.0
    assert art.outputs.structured["thesis"]["recommendation"] == "BUY"


def test_no_financial_data_publishable():
    result = PipelineResult(steps={"data_collection": "ok"}, structured_data={})
    art = build_equity_research_artifact(result, "AAPL", cast(Any, None))
    assert art.outputs.structured["numeric_audit"]["artifact_status"] == "publishable"


def test_standalone_dcf_carries_numeric_audit_when_clean():
    result = PipelineResult(
        steps={"historical_data": "ok", "dcf_calc": "ok"},
        structured_data={
            "historical_data": _fd(industry="Software", ev_ebitda=18.0),
            "dcf_calc": _dcf_result(),
        },
    )
    art = build_dcf_artifact(result, "X", cast(Any, None))

    assert art.outputs.structured["numeric_audit"]["artifact_status"] == "publishable"
    assert art.outputs.structured["implied_price"] == 120.0


def test_missing_fmp_key_marks_valuation_artifact_caveated():
    result = PipelineResult(
        steps={"historical_data": "ok", "dcf_calc": "ok"},
        structured_data={
            "historical_data": _fd(industry="Software", ev_ebitda=18.0),
            "dcf_calc": _dcf_result(),
        },
    )
    deps = SimpleNamespace(settings=SimpleNamespace(fmp_api_key="", language="en"))
    art = build_dcf_artifact(result, "X", cast(Any, deps))

    audit = art.outputs.structured["numeric_audit"]
    assert audit["artifact_status"] == "caveated"
    assert audit["data_capability"]["artifact_status"] == "caveated"
    assert audit["findings"] == []
    assert any("DATA-CAPABILITY" in w for w in art.outputs.warnings)
    # No-FMP-key is a data-quality caveat, NOT a withhold — the target still ships.
    assert art.outputs.structured["implied_price"] == 120.0


def test_standalone_dcf_blocks_direct_target_when_audit_withholds():
    # A genuinely-corrupt TTM (missing quarter) is a blocked_field → the DCF target built
    # on it is withheld. (Was a bank EV; that is now only a review caveat — see
    # test_bank_ev_caveats_but_target_ships — so use real corruption to exercise the gate.)
    result = PipelineResult(
        steps={"historical_data": "ok", "dcf_calc": "DCF implies $120 per share"},
        structured_data={
            "historical_data": _fd(industry="Software", ev_ebitda=18.0, ttm_ends=_BROKEN_TTM),
            "dcf_calc": _dcf_result(),
        },
    )
    art = build_dcf_artifact(result, "X", cast(Any, None))

    assert art.outputs.structured["numeric_audit"]["artifact_status"] == "caveated"
    assert art.outputs.structured["numeric_audit"]["withhold_valuation"] is True
    assert art.outputs.structured["valuation_withheld"] is True
    assert art.outputs.structured["implied_price"] is None
    assert "$120" not in art.outputs.summary_text
    assert "Valuation withheld" in art.outputs.summary_text
    assert any("ttm_quarter_gap" in w for w in art.outputs.warnings)


# ---------------------------------------------------------------------------
# Standalone LBO / Comps: the gate must never claim "withheld" while the numbers
# still ship. LBO returns (IRR/MOIC) are fully target-derived → withhold them on
# a blocked_field. Comps has no single target price to null (the peer medians are
# not invalidated by a target-only blocked_field) → flag-but-publish, and the
# summary must stay honest rather than announce a withhold that never happened.
# ---------------------------------------------------------------------------


def _lbo_result() -> LBOResult:
    schedule = [
        LBOYear(
            year=i,
            revenue=100,
            ebitda=30,
            da=4,
            ebit=26,
            interest_expense=8,
            ebt=18,
            taxes=4,
            net_income=14,
            capex=4,
            delta_nwc=1,
            fcf=15,
            mandatory_amort=2,
            cash_sweep_amount=10,
            total_debt_paydown=12,
            ending_debt=max(0, 150 - 12 * i),
        )
        for i in range(1, 6)
    ]
    return LBOResult(
        entry_ev=300,
        entry_debt=150,
        entry_equity=150,
        schedule=schedule,
        exit_ebitda=40,
        exit_ev=480,
        exit_equity=400,
        moic=2.67,
        irr=0.21,
    )


def _peer_comps() -> PeerComps:
    target = CompanyFinancials(
        ticker="X", revenue=100e9, ebitda=30e9, net_income=20e9, market_cap=500e9
    )
    peer = CompanyFinancials(
        ticker="P", revenue=80e9, ebitda=24e9, net_income=16e9, market_cap=400e9
    )
    return PeerComps(target=target, peers=[peer], median_pe=20.0, warnings=[])


def _lbo_pipeline_result(fd: FinancialData) -> PipelineResult:
    return PipelineResult(
        steps={"data_collection": "ok", "lbo_calculation": "LBO implies 0.21 IRR"},
        structured_data={"data_collection": fd, "lbo_calculation": _lbo_result()},
    )


def _comps_pipeline_result(fd: FinancialData) -> PipelineResult:
    return PipelineResult(
        steps={"target_data": "ok", "statistical_bench": "Comps median P/E 20x"},
        structured_data={"target_data": fd, "statistical_bench": _peer_comps()},
    )


def test_standalone_lbo_clean_publishes_returns():
    art = build_lbo_artifact(
        _lbo_pipeline_result(_fd(industry="Software", ev_ebitda=18.0)), "X", cast(Any, None)
    )
    assert art.outputs.structured["numeric_audit"]["withhold_valuation"] is False
    assert art.outputs.structured["irr"] == 0.21
    assert art.outputs.structured["moic"] == 2.67
    assert "valuation_withheld" not in art.outputs.structured
    assert "Valuation withheld" not in art.outputs.summary_text


def test_standalone_lbo_withholds_returns_when_audit_blocks():
    # Real corruption (broken TTM) blocks the target the LBO returns build on.
    art = build_lbo_artifact(
        _lbo_pipeline_result(_fd(industry="Software", ev_ebitda=18.0, ttm_ends=_BROKEN_TTM)),
        "X",
        cast(Any, None),
    )
    assert art.outputs.structured["numeric_audit"]["withhold_valuation"] is True
    assert art.outputs.structured["valuation_withheld"] is True
    # The headline returns are nulled — a return built on a corrupt target EBITDA
    # must not be published — but the ev/equity breakdown stays visible.
    assert art.outputs.structured["irr"] is None
    assert art.outputs.structured["moic"] is None
    assert art.outputs.structured["entry_ev"] == 300
    assert "Valuation withheld" in art.outputs.summary_text
    assert any("ttm_quarter_gap" in w for w in art.outputs.warnings)


def test_standalone_comps_flags_but_does_not_claim_withheld():
    # Regression: a blocked_field made withhold_valuation True, but comps passes no
    # withhold_keys, so nothing is nulled. The summary must NOT lie about a withhold,
    # and the peer medians (not invalidated by a target-only blocked_field) ship.
    art = build_comps_artifact(
        _comps_pipeline_result(_fd(industry="Software", ev_ebitda=18.0, ttm_ends=_BROKEN_TTM)),
        "X",
        cast(Any, None),
    )
    audit = art.outputs.structured["numeric_audit"]
    assert audit["withhold_valuation"] is True  # the audit still records the block
    assert audit["artifact_status"] == "caveated"
    assert "valuation_withheld" not in art.outputs.structured  # nothing was withheld
    assert art.outputs.structured["median_pe"] == 20.0  # medians still published
    assert "Valuation withheld" not in art.outputs.summary_text  # summary stays honest
    assert any("ttm_quarter_gap" in w for w in art.outputs.warnings)


# ---------------------------------------------------------------------------
# IC Memo: was the one builder that never ran the gate, yet its FinancialData is
# nested in ICFinancials.financial_data. Step 3 routes it through the shared sink
# so its snapshot is audited + the block ships for the audit banner + contract C4.
# No single per-share headline → the block is attached but nothing auto-withholds.
# ---------------------------------------------------------------------------


def _ic_memo_result(fd: FinancialData) -> PipelineResult:
    ic = ICFinancials(financial_data=fd, dcf_result=_dcf_result(), lbo_result=_lbo_result())
    return PipelineResult(
        steps={"financial_analysis": "ok"},
        structured_data={"financial_analysis": ic},
    )


def test_ic_memo_carries_numeric_audit_when_clean():
    art = build_ic_memo_artifact(
        _ic_memo_result(_fd(industry="Software", ev_ebitda=18.0)), "X", cast(Any, None)
    )
    audit = art.outputs.structured["numeric_audit"]
    assert audit["artifact_status"] == "publishable"
    assert audit["findings"] == []
    # The memo's DCF / LBO results still ship.
    assert "dcf_result" in art.outputs.structured
    assert "lbo_result" in art.outputs.structured


def test_ic_memo_audits_nested_snapshot_and_records_block():
    # The gate runs on ICFinancials.financial_data (nested). A genuinely-broken TTM is a
    # blocked_field — the block + finding surface (banner + contract C4 read them), but
    # ic_memo has no single headline target, so nothing auto-withholds.
    art = build_ic_memo_artifact(
        _ic_memo_result(_fd(industry="Software", ev_ebitda=18.0, ttm_ends=_BROKEN_TTM)),
        "X",
        cast(Any, None),
    )
    audit = art.outputs.structured["numeric_audit"]
    assert audit["artifact_status"] == "caveated"
    assert audit["withhold_valuation"] is True  # the audit records the block
    assert any(f["check"] == "ttm_quarter_gap" for f in audit["findings"])
    assert any("ttm_quarter_gap" in w for w in art.outputs.warnings)
    # No single per-share headline → nothing auto-withheld; the DCF / LBO ship.
    assert "valuation_withheld" not in art.outputs.structured
    assert "dcf_result" in art.outputs.structured


# ---------------------------------------------------------------------------
# Single-as-of gate — one artifact carries one price as-of (AAPL 2026-07-02:
# summary_text $287.98 / $4.230T trailed the frozen market block $294.38 /
# $4.324T by a full session; the 10% report-drift approximation band read the
# stale price as a rounding and shipped it).
# ---------------------------------------------------------------------------


def _split_result(data_collection_text: str):
    # _fd's market block = current_price 100.0 / market_cap 500e9.
    return PipelineResult(
        steps={"data_collection": data_collection_text, "thesis": "Price target $100"},
        structured_data={
            "data_collection": _fd(),
            "thesis": {"recommendation": "BUY", "price_target": 100.0, "tagline": "t"},
        },
    )


def test_price_snapshot_split_in_summary_fails_build():
    """A summary narrative restating a price/market-cap that trails the frozen
    market block (>1% same-number tolerance) fails the build — a second price
    for one artifact is a fabrication surface, never shipped (绝不编数字)."""
    result = _split_result("| Current Price | $95.00 |\n| Market Cap | $475.0 Billion |")
    with pytest.raises(ValueError, match="price snapshot as-of split"):
        _build(result, "X")


def test_price_snapshot_coherent_narrative_builds():
    """A narrative price within the tight same-number band builds fine — the gate
    only fires on a genuine cross-session split, not on rounding."""
    result = _split_result("| Current Price | $100.00 |\n| Market Cap | $500.0 Billion |")
    art = _build(result, "X")
    assert "$100.00" in art.outputs.summary_text  # built, no raise


def test_price_snapshot_derived_field_split_fails_build():
    """A code-derived price field (valuation_synthesis.current_price) that trails
    the frozen market block also fails the build — deterministic desync, not LLM
    variance."""
    result = _split_result("data collection ok")
    # 90.0 vs the market block's 100.0 → 10% split. A plain dict round-trips through
    # _safe_dump unchanged (structured_out reads current_price straight off it).
    result.structured_data["valuation_synthesis"] = {
        "current_price": 90.0,
        "valuation_withheld": False,
    }
    with pytest.raises(ValueError, match="price snapshot as-of split"):
        _build(result, "X")
