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

import pytest

from finrobot.engine.compute.operators.valuation_aggregator import aggregate_valuation
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
    / "operators"
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
            re.compile(
                r"^\s*from\s+finrobot\.engine\.compute\.operators\.lbo\s+import", re.MULTILINE
            ),
            re.compile(r"^\s*import\s+finrobot\.engine\.compute\.operators\.lbo", re.MULTILINE),
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
            assert row.method_type in (
                "valuation",
                "multiple",
            ), f"row {row.method} missing method_type — spec §6.4 requires it for UI rendering"

    def test_financial_sector_suppresses_cashflow_methods_keeps_multiples(self) -> None:
        """Bank / insurer: DCF, EV/EBITDA and P/FCF are category errors (free cash
        flow, EBITDA and the net-debt bridge are ill-defined when debt is the raw
        material, not financing). The aggregator drops those rows — with surfaced
        'method withheld' reasons — and leads with the relative multiples instead,
        never plotting a meaningless DCF (the report showed JPM DCF ~$719 vs a ~$325
        price before this gate). The bank must still get a method, never punt."""
        agg = aggregate_valuation(
            ticker="JPM",
            current_price=325.0,
            dcf=_dcf(implied_price=719.0),
            peer_comps=_peer_comps(median_pe=12.0),
            shares_outstanding=2.9e9,
            forward_eps=15.0,
            ttm_ebitda=120e9,
            historical_ev_ebitda_band=(8.0, 12.0),
            historical_ev_ebitda_sample_n=8,
            financial_sector=True,
        )
        names = {m.method for m in agg.methods}
        assert "dcf" not in names
        assert "ev_ebitda" not in names
        assert "p_fcf" not in names
        assert agg.methods, "bank must still ship a relative-multiple method (P/E), never punt"
        assert any("financial-sector" in w and w.startswith("dcf:") for w in agg.warnings)
        assert any("financial-sector" in w and w.startswith("ev_ebitda:") for w in agg.warnings)

    def test_non_financial_keeps_dcf_row_unchanged(self) -> None:
        """The financial-sector gate must not touch a non-bank: identical inputs,
        DCF row still ships (no over-suppression / regression)."""
        agg = aggregate_valuation(
            ticker="AAPL",
            current_price=325.0,
            dcf=_dcf(implied_price=719.0),
            peer_comps=_peer_comps(median_pe=12.0),
            shares_outstanding=2.9e9,
            forward_eps=15.0,
            financial_sector=False,
        )
        assert "dcf" in {m.method for m in agg.methods}

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
        # Compute expected prices manually from the grid we provided. The t+N
        # exit equity is a FUTURE value: it must be discounted to today at the
        # sponsor hurdle (ability-to-pay) before sharing the football-field
        # axis with PV methods and the current price — the undiscounted band
        # overstated the LBO row ~2x over a 5y hold.
        from finrobot.engine.models.valuation_thresholds import SPONSOR_IRR_HURDLE

        remaining_debt = lbo.schedule[-1].ending_debt
        discount = (1 + SPONSOR_IRR_HURDLE) ** len(lbo.schedule)
        expected = sorted(
            (mult * lbo.exit_ebitda - remaining_debt) / 2.4e9 / discount
            for mult in [10.0, 11.0, 12.0]
        )
        assert lbo_row.low == pytest.approx(expected[0])
        assert lbo_row.high == pytest.approx(expected[-1])
        assert "hurdle" in (lbo_row.source or "")

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

    def test_dcf_band_is_flat_plus_minus_twenty_percent(self) -> None:
        agg = aggregate_valuation(
            ticker="NVDA",
            current_price=876.42,
            dcf=_dcf(900.0),
            as_of=AS_OF,
        )
        row = next(m for m in agg.methods if m.method == "dcf")
        assert row.low == 720.0  # 900 * 0.8
        assert row.high == 1080.0  # 900 * 1.2
        # Honest placeholder label — no modelled distribution behind the band.
        assert "± 20%" in row.source
        assert "placeholder band" in row.source

    def test_dcf_band_never_emits_monte_carlo_source(self) -> None:
        # The Monte Carlo P10/P90 branch was dead code: nothing in the pipeline
        # ever writes p10/p90 into sensitivity_table (it only ever holds the
        # WACC×TG grid). Even when those keys are present, the band must stay a
        # flat ±20% placeholder and must not claim a 'monte_carlo' provenance.
        dcf = _dcf(900.0)
        dcf.sensitivity_table = {"p10": 800.0, "p90": 1040.0}
        agg = aggregate_valuation(
            ticker="NVDA",
            current_price=876.42,
            dcf=dcf,
            as_of=AS_OF,
        )
        row = next(m for m in agg.methods if m.method == "dcf")
        assert row.low == 720.0
        assert row.high == 1080.0
        assert "monte_carlo" not in row.source

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

    def test_ev_ebitda_bridges_on_current_net_debt(self) -> None:
        """EV/EBITDA EV→equity bridge must subtract CURRENT net debt — the same
        total_debt − cash口径 dcf_seed uses — not LBO ending_debt, not 0."""
        agg = aggregate_valuation(
            ticker="NVDA",
            current_price=876.42,
            dcf=_dcf(),
            shares_outstanding=2.4e9,
            current_net_debt=30e9,
            ttm_ebitda=40e9,
            historical_ev_ebitda_band=(20.0, 30.0),
            as_of=AS_OF,
        )
        row = next(m for m in agg.methods if m.method == "ev_ebitda")
        assert row.method_type == "multiple"
        assert row.confidence == 0.72
        # Exact bridge: (p × ttm_ebitda − current_net_debt) / shares.
        assert row.low == (20.0 * 40e9 - 30e9) / 2.4e9
        assert row.high == (30.0 * 40e9 - 30e9) / 2.4e9
        assert "current_net_debt" in row.source

    def test_ev_ebitda_net_debt_lowers_target_by_exactly_net_debt_per_share(self) -> None:
        """A levered firm's per-share target is lower than the debt-free case by
        exactly net_debt / shares — the whole point of the bridge."""
        kwargs = dict(
            ticker="NVDA",
            current_price=876.42,
            shares_outstanding=2.4e9,
            ttm_ebitda=40e9,
            historical_ev_ebitda_band=(20.0, 30.0),
            as_of=AS_OF,
        )
        levered = aggregate_valuation(current_net_debt=30e9, **kwargs)  # type: ignore[arg-type]
        debt_free = aggregate_valuation(current_net_debt=0.0, **kwargs)  # type: ignore[arg-type]
        lev_row = next(m for m in levered.methods if m.method == "ev_ebitda")
        free_row = next(m for m in debt_free.methods if m.method == "ev_ebitda")
        per_share = 30e9 / 2.4e9
        assert free_row.low - lev_row.low == per_share
        assert free_row.high - lev_row.high == per_share

    def test_ev_ebitda_net_cash_raises_target(self) -> None:
        """current_net_debt may be negative (net cash); the bridge adds it back,
        lifting the implied equity value above the zero-debt baseline."""
        kwargs = dict(
            ticker="AAPL",
            current_price=200.0,
            shares_outstanding=2.4e9,
            ttm_ebitda=40e9,
            historical_ev_ebitda_band=(20.0, 30.0),
            as_of=AS_OF,
        )
        net_cash = aggregate_valuation(current_net_debt=-10e9, **kwargs)  # type: ignore[arg-type]
        zero = aggregate_valuation(current_net_debt=0.0, **kwargs)  # type: ignore[arg-type]
        cash_row = next(m for m in net_cash.methods if m.method == "ev_ebitda")
        zero_row = next(m for m in zero.methods if m.method == "ev_ebitda")
        assert cash_row.low > zero_row.low
        assert cash_row.low == (20.0 * 40e9 - (-10e9)) / 2.4e9

    def test_ev_ebitda_skipped_when_current_net_debt_missing(self) -> None:
        """Missing current net debt → hide the row (口径-explicit warning), never
        assume net_debt = 0. This is the BUG-class the 0.0 fallback created."""
        agg = aggregate_valuation(
            ticker="NVDA",
            current_price=876.42,
            shares_outstanding=2.4e9,
            ttm_ebitda=40e9,
            historical_ev_ebitda_band=(20.0, 30.0),
            current_net_debt=None,
            as_of=AS_OF,
        )
        assert not any(m.method == "ev_ebitda" for m in agg.methods)
        assert any("current net debt" in w for w in agg.warnings)

    def test_ev_ebitda_never_borrows_lbo_ending_debt(self) -> None:
        """Even with a full LBO artifact present, EV/EBITDA must NOT reach into
        lbo.schedule[-1].ending_debt for the bridge — that is a future, post-
        paydown debt at exit (time-point mismatch). With LBO present but no
        current_net_debt supplied, the row stays hidden."""
        agg = aggregate_valuation(
            ticker="NVDA",
            current_price=876.42,
            lbo=_lbo_with_grid(),
            shares_outstanding=2.4e9,
            ttm_ebitda=40e9,
            historical_ev_ebitda_band=(20.0, 30.0),
            current_net_debt=None,
            as_of=AS_OF,
        )
        assert not any(m.method == "ev_ebitda" for m in agg.methods)

    def test_lbo_exit_equity_still_uses_ending_debt(self) -> None:
        """Regression guard: the net-debt fix must NOT touch LBO's own bridge.
        LBO exit equity legitimately uses post-paydown ending_debt at exit."""
        lbo = _lbo_with_grid()
        agg = aggregate_valuation(
            ticker="NVDA",
            current_price=876.42,
            lbo=lbo,
            shares_outstanding=2.4e9,
            current_net_debt=30e9,  # present, but must not leak into the LBO row
            as_of=AS_OF,
        )
        lbo_row = next(m for m in agg.methods if m.method == "lbo")
        from finrobot.engine.models.valuation_thresholds import SPONSOR_IRR_HURDLE

        remaining_debt = lbo.schedule[-1].ending_debt
        discount = (1 + SPONSOR_IRR_HURDLE) ** len(lbo.schedule)
        expected = sorted(
            (mult * lbo.exit_ebitda - remaining_debt) / 2.4e9 / discount
            for mult in [10.0, 11.0, 12.0]
        )
        assert lbo_row.low == pytest.approx(expected[0])
        assert lbo_row.high == pytest.approx(expected[-1])

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
        # BUG-029: the forward path uses an AS-REPORTED peer median P/E (a
        # different earnings caliber than the trailing NOPAT-core path). The
        # source must disclose that口径 rather than mix definitions silently.
        assert "as-reported" in row.source

    def test_comps_pe_prefers_peer_forward_pe_when_available(self) -> None:
        # When peers carry a forward P/E (median_forward_pe, set per peer in
        # _fetch_one_peer), comps_pe pairs the peer FORWARD median with the target
        # forward EPS — one forward caliber both sides, resolving the BUG-029
        # as-reported fallback. Higher confidence than that fallback.
        pc = _peer_comps(median_pe=28.0)
        pc.median_forward_pe = 40.0
        agg = aggregate_valuation(
            ticker="NVDA",
            current_price=876.42,
            peer_comps=pc,
            forward_eps=12.5,
            shares_outstanding=2.4e9,
            as_of=AS_OF,
        )
        row = next(m for m in agg.methods if m.method == "comps_pe")
        assert row.mid == 40.0 * 12.5  # peer forward median, NOT the trailing 28.0
        assert row.confidence == 0.80
        assert "forward_pe" in row.source

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

    def test_dcf_row_carries_load_bearing_assumptions(self) -> None:
        """A DCF mid is an answer conditional on WACC / growth fade / beta — the
        row must carry those so no consumer cites the price naked (the $73
        NVDA pathology). See _dcf_assumptions."""
        agg = aggregate_valuation(
            ticker="NVDA",
            current_price=876.42,
            dcf=_dcf(implied_price=73.44),
            as_of=AS_OF,
        )
        row = next(m for m in agg.methods if m.method == "dcf")
        # fixture: wacc 0.082, growth [0.10,0.08,0.06], terminal 0.025, beta 1.2
        assert row.assumptions == "WACC 8.2% · 3yr growth 10%→2.5% · β1.20"

    def test_dcf_assumptions_surface_peak_when_first_year_dips(self) -> None:
        """A slow-FY1 growth path ([3.2%, 18.2%, …decay…, 3%]) rendered as the
        two-point "3%→3.0%" hides the 18% peak entirely — the reader reads a
        flat-3% Microsoft worth +17% and calls the model broken (2026-07-07
        blind panoramic review). The peak must show whenever it sits >1pp above
        the first year."""
        dcf = _dcf(implied_price=451.22)
        dcf.inputs.revenue_growth_rates = [0.032, 0.182, 0.14, 0.09, 0.03]
        agg = aggregate_valuation(
            ticker="MSFT",
            current_price=386.74,
            dcf=dcf,
            as_of=AS_OF,
        )
        row = next(m for m in agg.methods if m.method == "dcf")
        assert row.assumptions == "WACC 8.2% · 5yr growth 3%↗18%→2.5% · β1.20"

    def test_comps_pe_row_carries_caliber_assumption(self) -> None:
        """comps_pe's load-bearing bet is 'NVDA deserves the peer median P/E' on a
        named EPS caliber — the assumption that put NVDA at $341 on inflated EPS."""
        agg = aggregate_valuation(
            ticker="NVDA",
            current_price=876.42,
            peer_comps=_peer_comps(),
            forward_eps=12.5,
            shares_outstanding=2.4e9,
            as_of=AS_OF,
        )
        row = next(m for m in agg.methods if m.method == "comps_pe")
        # The caliber now discloses the as-reported peer-P/E口径 (BUG-029).
        assert (
            row.assumptions
            == "anchored to peer median P/E 28.0× × forward EPS (as-reported peer P/E)"
        )

    def test_ddm_row_carries_discount_and_growth_assumption(self) -> None:
        agg = aggregate_valuation(
            ticker="JPM",
            current_price=180.0,
            ddm=_ddm(),
            as_of=AS_OF,
        )
        row = next(m for m in agg.methods if m.method == "ddm")
        # fixture: cost_of_equity 0.10, dividend growth [0.05,0.04,0.03], terminal 0.02
        assert (
            row.assumptions
            == "discount rate (cost of equity) 10.0% · dividend growth 5%→terminal 2.0%"
        )

    def test_lbo_row_carries_exit_multiple_and_hold_assumption(self) -> None:
        agg = aggregate_valuation(
            ticker="NVDA",
            current_price=876.42,
            lbo=_lbo_with_grid(),
            shares_outstanding=2.4e9,
            as_of=AS_OF,
        )
        row = next(m for m in agg.methods if m.method == "lbo")
        # fixture: exit_multiples [10,11,12], 5-year schedule
        assert row.assumptions == "exit EV/EBITDA 10.0–12.0× · hold 5yr"
