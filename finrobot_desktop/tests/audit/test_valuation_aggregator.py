"""Audit invariants for v5 §6.4 Football Field aggregator.

These tests pin three high-value contracts:

1. **Leaf-layer isolation** — valuation_aggregator.py must not reach into
   provider SDKs / LLM libraries / upper engine layers. The architecture
   audit covers compute/* generically; this file repeats the check inline
   so a single grep shows why this aggregator is special (it touches several
   pipeline result types and is easy to drift).

2. **LBO reuse, never re-run** — spec §6.4.2 forbids the aggregator from
   calling ``calculate_lbo`` per cell. We assert by source-grep that the
   module never imports or names the offending entry points.

3. **method_type required on every emitted row** — front-end §6.4 renders
   valuation vs multiple methods with different visual weight; an unlabelled
   row would mis-render. The Pydantic model enforces this, but we double-pin
   it here to keep the contract visible to PR readers.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from finrobot.engine.compute.valuation_aggregator import aggregate_valuation
from finrobot.engine.models.financial import (
    CompanyFinancials,
    DCFInputs,
    DCFResult,
    DDMInputs,
    DDMResult,
    LBOResult,
    LBOYear,
    PeerComps,
)

AGG_SRC = (
    Path(__file__).resolve().parents[2]
    / "finrobot"
    / "engine"
    / "compute"
    / "valuation_aggregator.py"
)
UTC = timezone.utc
AS_OF = datetime(2026, 5, 21, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Source-level invariants
# ---------------------------------------------------------------------------


class TestAggregatorLeafIsolation:
    """valuation_aggregator.py is a leaf — no providers, LLMs, or upper layers."""

    def test_no_forbidden_imports_in_aggregator_source(self) -> None:
        src = AGG_SRC.read_text()
        forbidden = (
            "from finrobot.engine.pipelines",
            "from finrobot.engine.agents",
            "from finrobot.engine.orchestrator",
            "from finrobot.engine.data",
            "import pydantic_ai",
            "from pydantic_ai",
            "import openai",
            "import yfinance",
            "import finnhub",
        )
        violations = [
            pat for pat in forbidden if re.search(rf"^\s*{re.escape(pat)}", src, re.MULTILINE)
        ]
        assert not violations, f"aggregator leaks: {violations}"

    def test_aggregator_never_invokes_calculate_lbo(self) -> None:
        # spec §6.4.2: re-running the full LBO per cell would 25x endpoint cost.
        # The grid math must reuse LBOResult.sensitivity, never call calculate_lbo*.
        # Check for actual import or call sites — not docstring mentions of the rule.
        src = AGG_SRC.read_text()
        forbidden_call_patterns = (
            re.compile(r"^\s*from\s+finrobot\.engine\.compute\.lbo\s+import", re.MULTILINE),
            re.compile(r"^\s*import\s+finrobot\.engine\.compute\.lbo", re.MULTILINE),
            re.compile(r"\bcalculate_lbo\s*\("),
            re.compile(r"\bcalculate_lbo_sensitivity\s*\("),
        )
        violations = [pat.pattern for pat in forbidden_call_patterns if pat.search(src)]
        assert not violations, (
            "valuation_aggregator.py must NOT import or call calculate_lbo / "
            "calculate_lbo_sensitivity — reuse LBOResult.sensitivity grid + exit_ebitda + "
            f"remaining_debt instead (spec §6.4.2). Violations: {violations}"
        )


# ---------------------------------------------------------------------------
# Contract invariants enforced by aggregate_valuation()
# ---------------------------------------------------------------------------


def _dcf(implied_price: float = 920.0) -> DCFResult:
    return DCFResult(
        cost_of_equity=0.10,
        wacc=0.082,
        projection_years=5,
        projected_revenue=[100, 110, 121],
        projected_ebitda=[30, 33, 36],
        projected_fcf=[20, 22, 24],
        terminal_value=400,
        pv_terminal=300,
        pv_fcf_total=200,
        enterprise_value=500,
        equity_value=480,
        implied_price=implied_price,
        sensitivity_table=None,
        inputs=DCFInputs(
            revenue_base=1000,
            revenue_growth_rates=[0.10, 0.08, 0.06],
            ebitda_margin=0.30,
            capex_pct_revenue=0.04,
            nwc_pct_revenue=0.02,
            da_pct_revenue=0.04,
            tax_rate=0.21,
            risk_free_rate=0.04,
            beta=1.2,
            equity_risk_premium=0.05,
            cost_of_debt=0.05,
            debt_ratio=0.2,
            terminal_growth_rate=0.025,
            shares_outstanding=2.4e9,
            net_debt=30e9,
        ),
    )


def _ddm() -> DDMResult:
    return DDMResult(
        cost_of_equity=0.10,
        projected_dividends=[2, 2.1, 2.2],
        pv_dividends=[1.8, 1.7, 1.6],
        pv_dividends_total=5.1,
        terminal_dividend=2.4,
        terminal_value=40,
        pv_terminal=30,
        equity_value_per_share=120.0,
        inputs=DDMInputs(
            dividend_per_share=2.0,
            dividend_growth_rates=[0.05, 0.04, 0.03],
            payout_ratio=0.5,
            risk_free_rate=0.04,
            beta=1.0,
            equity_risk_premium=0.05,
            terminal_growth_rate=0.02,
            shares_outstanding=2.4e9,
            current_price=110.0,
        ),
    )


def _lbo_with_grid() -> LBOResult:
    schedule = [
        LBOYear(
            year=i,
            revenue=100 * (1 + 0.05 * i),
            ebitda=30 * (1 + 0.05 * i),
            da=4,
            ebit=26 * (1 + 0.05 * i),
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
        sensitivity={
            "entry_multiples": [9.0, 10.0, 11.0],
            "exit_multiples": [10.0, 11.0, 12.0],
            "irr_grid": [[0.18, 0.20, 0.22]] * 3,
            "moic_grid": [[2.3, 2.5, 2.7]] * 3,
        },
        irr_formula_warning=None,
    )


def _peer_comps(median_pe: float = 28.0) -> PeerComps:
    target = CompanyFinancials(
        ticker="NVDA",
        name="NVIDIA",
        revenue=60e9,
        ebitda=33e9,
        net_income=24e9,
        market_cap=2.1e12,
        total_debt=11e9,
        total_cash=8e9,
        gross_margin=0.72,
        operating_margin=0.40,
        pe_ratio=88.0,
        ev_ebitda=64.0,
    )
    peer = target.model_copy(update={"ticker": "AMD", "pe_ratio": 32.0, "ev_ebitda": 28.0})
    return PeerComps(target=target, peers=[peer], median_pe=median_pe, median_ev_ebitda=46.0)


class TestAggregatorContract:
    def test_every_emitted_row_has_method_type_label(self) -> None:
        agg = aggregate_valuation(
            ticker="NVDA",
            current_price=876.42,
            dcf=_dcf(),
            peer_comps=_peer_comps(),
            ddm=_ddm(),
            lbo=_lbo_with_grid(),
            shares_outstanding=2.4e9,
            as_of=AS_OF,
        )
        for row in agg.methods:
            assert row.method_type in ("valuation", "multiple"), (
                f"row {row.method} missing method_type — spec §6.4 requires it for UI rendering"
            )

    def test_lbo_band_built_from_sensitivity_grid_not_recompute(self) -> None:
        lbo = _lbo_with_grid()
        agg = aggregate_valuation(
            ticker="NVDA",
            current_price=876.42,
            dcf=_dcf(),
            lbo=lbo,
            shares_outstanding=2.4e9,
            as_of=AS_OF,
        )
        lbo_row = next(m for m in agg.methods if m.method == "lbo")
        # Compute expected prices manually from the grid we provided
        remaining_debt = lbo.schedule[-1].ending_debt
        expected = sorted(
            (mult * lbo.exit_ebitda - remaining_debt) / 2.4e9 for mult in [10.0, 11.0, 12.0]
        )
        assert lbo_row.low == expected[0]
        assert lbo_row.high == expected[-1]

    def test_lbo_skipped_when_shares_unknown(self) -> None:
        agg = aggregate_valuation(
            ticker="NVDA",
            current_price=876.42,
            lbo=_lbo_with_grid(),
            shares_outstanding=None,
            as_of=AS_OF,
        )
        assert not any(m.method == "lbo" for m in agg.methods)
        assert any("shares_outstanding" in w for w in agg.warnings)

    def test_dcf_band_uses_monte_carlo_when_present(self) -> None:
        dcf = _dcf()
        dcf.sensitivity_table = {"p10": 800.0, "p90": 1040.0}
        agg = aggregate_valuation(
            ticker="NVDA",
            current_price=876.42,
            dcf=dcf,
            as_of=AS_OF,
        )
        row = next(m for m in agg.methods if m.method == "dcf")
        assert row.low == 800.0
        assert row.high == 1040.0
        assert "monte_carlo" in row.source

    def test_dcf_band_falls_back_to_plus_minus_twenty_percent(self) -> None:
        agg = aggregate_valuation(
            ticker="NVDA",
            current_price=876.42,
            dcf=_dcf(900.0),
            as_of=AS_OF,
        )
        row = next(m for m in agg.methods if m.method == "dcf")
        assert row.low == 720.0  # 900 * 0.8
        assert row.high == 1080.0  # 900 * 1.2

    def test_multiple_rows_omitted_until_pr3_pr4c_inputs_arrive(self) -> None:
        agg = aggregate_valuation(
            ticker="NVDA",
            current_price=876.42,
            dcf=_dcf(),
            as_of=AS_OF,
        )
        method_names = {m.method for m in agg.methods}
        assert "ev_ebitda" not in method_names
        assert "p_fcf" not in method_names
        assert any("ev_ebitda" in w for w in agg.warnings)
        assert any("p_fcf" in w for w in agg.warnings)

    def test_ev_ebitda_emitted_when_inputs_supplied(self) -> None:
        agg = aggregate_valuation(
            ticker="NVDA",
            current_price=876.42,
            dcf=_dcf(),
            lbo=_lbo_with_grid(),
            shares_outstanding=2.4e9,
            forward_ebitda=40e9,
            historical_ev_ebitda_band=(20.0, 30.0),
            as_of=AS_OF,
        )
        row = next(m for m in agg.methods if m.method == "ev_ebitda")
        assert row.method_type == "multiple"
        assert row.low < row.high
        assert row.confidence == 0.72

    def test_p_fcf_emitted_when_inputs_supplied(self) -> None:
        agg = aggregate_valuation(
            ticker="NVDA",
            current_price=876.42,
            shares_outstanding=2.4e9,
            forward_fcf=30e9,
            historical_p_fcf_band=(25.0, 35.0),
            as_of=AS_OF,
        )
        row = next(m for m in agg.methods if m.method == "p_fcf")
        assert row.method_type == "multiple"
        assert row.low > 0
        assert row.high > row.low

    def test_comps_pe_uses_forward_eps_when_provided(self) -> None:
        agg = aggregate_valuation(
            ticker="NVDA",
            current_price=876.42,
            peer_comps=_peer_comps(),
            forward_eps=12.5,
            shares_outstanding=2.4e9,
            as_of=AS_OF,
        )
        row = next(m for m in agg.methods if m.method == "comps_pe")
        assert row.mid == 28.0 * 12.5
        assert row.confidence == 0.78
        assert "forward_eps" in row.source

    def test_comps_pe_uses_core_caliber_when_available(self) -> None:
        """Trailing path with NOPAT core fields populated (the real post-
        calculate_core_pe pipeline state) pairs the core peer median with the
        target's core EPS — one earnings caliber on both sides."""
        comps = _peer_comps()
        comps.median_core_pe = 24.0
        comps.target.core_net_income = 18e9  # below net_income 24e9 (non-op stripped)
        agg = aggregate_valuation(
            ticker="NVDA",
            current_price=876.42,
            peer_comps=comps,
            shares_outstanding=2.4e9,
            as_of=AS_OF,
        )
        row = next(m for m in agg.methods if m.method == "comps_pe")
        assert row.mid == 24.0 * (18e9 / 2.4e9)  # median_core_pe × core EPS
        assert row.confidence == 0.55
        assert "core_eps" in row.source

    def test_comps_pe_falls_back_to_trailing_eps_when_core_unavailable(self) -> None:
        """No core fields (provider omitted margin/tax) → keep the as-reported
        trailing path rather than dropping the comps_pe row entirely."""
        agg = aggregate_valuation(
            ticker="NVDA",
            current_price=876.42,
            peer_comps=_peer_comps(),  # median_core_pe / core_net_income unset
            shares_outstanding=2.4e9,
            as_of=AS_OF,
        )
        row = next(m for m in agg.methods if m.method == "comps_pe")
        eps = 24e9 / 2.4e9  # 10.0
        assert row.mid == 28.0 * eps
        assert row.confidence == 0.55
        assert "trailing_eps" in row.source

    def test_empty_inputs_return_zero_methods_plus_warnings(self) -> None:
        agg = aggregate_valuation(
            ticker="NVDA",
            current_price=None,
            as_of=AS_OF,
        )
        assert agg.methods == []
        assert len(agg.warnings) >= 4  # at least dcf / comps / ev / pf flagged
        assert agg.ticker == "NVDA"
