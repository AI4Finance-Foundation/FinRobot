"""Audit invariants for pipeline valuation synthesis (Football Field source).

Pins three contracts broken by Bug A + Bug B:

1. DCF always appears in methods when DCFResult is in structured_context.
2. len(methods) >= 2 when both DCF + Comps are available.
3. weighted_price is None when only 1 method resolves (no cross-check).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from finrobot.engine.compute.operators.forward_estimates import ForwardFinancials
from finrobot.engine.compute.operators.valuation_aggregator import (
    _comps_median_refusal,
    _ev_ebitda_method,
    aggregate_valuation,
)
from finrobot.engine.compute.operators.valuation_synthesis import synthesize_valuations
from finrobot.engine.models.financial import (
    CompanyFinancials,
    DCFInputs,
    DCFResult,
    DDMInputs,
    DDMResult,
    FinancialData,
    IncomeStatement,
    BalanceSheet,
    LBOResult,
    LBOYear,
    MarketData,
    PeerComps,
    ValuationMethod,
)
from finrobot.engine.pipelines._helpers import build_valuation_synthesis


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _dcf(implied_price: float = 150.0) -> DCFResult:
    return DCFResult(
        cost_of_equity=0.09,
        wacc=0.082,
        projection_years=5,
        projected_revenue=[100e9, 110e9, 121e9],
        projected_ebitda=[25e9, 27e9, 30e9],
        projected_fcf=[18e9, 20e9, 22e9],
        terminal_value=800e9,
        pv_terminal=600e9,
        pv_fcf_total=80e9,
        enterprise_value=680e9,
        equity_value=640e9,
        implied_price=implied_price,
        sensitivity_table=None,
        inputs=DCFInputs(
            revenue_base=100e9,
            revenue_growth_rates=[0.10, 0.08, 0.06],
            ebitda_margin=0.25,
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
            shares_outstanding=15.4e9,
            net_debt=40e9,
        ),
    )


def _peer_comps() -> PeerComps:
    target = CompanyFinancials(
        ticker="AAPL",
        name="Apple Inc.",
        revenue=390e9,
        ebitda=120e9,
        net_income=95e9,
        market_cap=2.8e12,
        total_debt=110e9,
        total_cash=62e9,
        gross_margin=0.44,
        operating_margin=0.30,
        pe_ratio=29.0,
        ev_ebitda=22.0,
    )
    peer = target.model_copy(
        update={"ticker": "MSFT", "pe_ratio": 35.0, "ev_ebitda": 26.0, "market_cap": 3.1e12}
    )
    return PeerComps(
        target=target,
        peers=[peer],
        median_pe=32.0,
        median_ev_ebitda=24.0,
    )


def _cyclical_peer_comps_thin_pb() -> PeerComps:
    """A commodity-cyclical peer set whose P/B median rests on a single peer
    (``pb_sample_n=1``) — the thin-sample guard must refuse comps_pb, the P/B
    sibling of the comps_pe thin-sample case. Carries a positive book value so
    the method is *attempted* (and then refused at the median guard) rather than
    skipped earlier for missing data."""
    target = CompanyFinancials(
        ticker="X",
        name="Steelco",
        revenue=20e9,
        ebitda=4e9,
        net_income=2e9,
        market_cap=15e9,
        total_debt=8e9,
        total_cash=2e9,
        gross_margin=0.20,
        operating_margin=0.12,
        pe_ratio=8.0,
        ev_ebitda=5.0,
        book_value_per_share=30.0,
        pb_ratio=1.4,
    )
    peer = target.model_copy(update={"ticker": "Y", "pb_ratio": 1.1})
    return PeerComps(
        target=target,
        peers=[peer],
        median_pe=8.5,
        median_ev_ebitda=5.5,
        median_pb=1.2,
        pb_sample_n=1,
    )


def _ddm() -> DDMResult:
    return DDMResult(
        cost_of_equity=0.10,
        projected_dividends=[2.0, 2.1, 2.2],
        pv_dividends=[1.8, 1.7, 1.6],
        pv_dividends_total=5.1,
        terminal_dividend=2.4,
        terminal_value=40.0,
        pv_terminal=30.0,
        equity_value_per_share=120.0,
        inputs=DDMInputs(
            dividend_per_share=2.0,
            dividend_growth_rates=[0.05, 0.04, 0.03],
            payout_ratio=0.5,
            risk_free_rate=0.04,
            beta=1.0,
            equity_risk_premium=0.05,
            terminal_growth_rate=0.02,
            shares_outstanding=15.4e9,
            current_price=110.0,
        ),
    )


def _lbo() -> LBOResult:
    schedule = [
        LBOYear(
            year=i,
            revenue=100.0,
            ebitda=30.0,
            da=4.0,
            ebit=26.0,
            interest_expense=8.0,
            ebt=18.0,
            taxes=4.0,
            net_income=14.0,
            capex=4.0,
            delta_nwc=1.0,
            fcf=15.0,
            mandatory_amort=2.0,
            cash_sweep_amount=10.0,
            total_debt_paydown=12.0,
            ending_debt=max(0.0, 150.0 - 12.0 * i),
        )
        for i in range(1, 6)
    ]
    return LBOResult(
        entry_ev=300.0,
        entry_debt=150.0,
        entry_equity=150.0,
        schedule=schedule,
        exit_ebitda=40.0,
        exit_ev=480.0,
        exit_equity=400.0,
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


# ---------------------------------------------------------------------------
# Contract 1: DCF appears in methods when DCFResult is in context
# ---------------------------------------------------------------------------


class TestDCFAlwaysPresent:
    def test_dcf_in_methods_when_dcf_result_in_context(self) -> None:
        """Bug A: DCF was silently dropped because context was read before write."""
        structured_context: dict[str, object] = {
            "financial_modeling": _dcf(150.0),
            "peer_analysis": _peer_comps(),
        }
        vs = build_valuation_synthesis(structured_context, current_price=170.0, ticker="AAPL")
        assert vs is not None, "Should produce ValuationSynthesis when DCF + Comps available"
        method_names = {m.name for m in vs.methods}
        assert (
            "dcf" in method_names
        ), f"DCF method missing from synthesis — Bug A regression. Got: {method_names}"

    def test_dcf_in_aggregate_valuation_directly(self) -> None:
        """aggregate_valuation emits a dcf row when DCFResult is provided."""
        agg = aggregate_valuation(
            ticker="AAPL",
            current_price=170.0,
            dcf=_dcf(150.0),
            peer_comps=_peer_comps(),
            shares_outstanding=15.4e9,
        )
        method_names = {m.method for m in agg.methods}
        assert "dcf" in method_names, f"DCF missing from aggregate_valuation. Got: {method_names}"


# ---------------------------------------------------------------------------
# Contract 2: ≥2 methods when both DCF + Comps are available
# ---------------------------------------------------------------------------


class TestMinMethodCount:
    def test_two_or_more_methods_with_dcf_and_comps(self) -> None:
        """Bug B: old build_valuation_synthesis only wired 2 branches,
        but DCF branch silently failed → len == 1."""
        structured_context: dict[str, object] = {
            "financial_modeling": _dcf(150.0),
            "peer_analysis": _peer_comps(),
        }
        vs = build_valuation_synthesis(structured_context, current_price=170.0, ticker="AAPL")
        assert vs is not None
        assert len(vs.methods) >= 2, (
            f"Expected ≥2 methods with DCF + Comps, got {len(vs.methods)}: "
            f"{[m.name for m in vs.methods]}"
        )

    def test_weighted_price_not_none_with_two_methods(self) -> None:
        structured_context: dict[str, object] = {
            "financial_modeling": _dcf(150.0),
            "peer_analysis": _peer_comps(),
        }
        vs = build_valuation_synthesis(structured_context, current_price=170.0, ticker="AAPL")
        assert vs is not None
        assert (
            vs.weighted_price is not None
        ), "weighted_price must be a float when ≥2 methods are present"
        assert vs.weighted_price > 0

    def test_ddm_calc_step_name_reaches_synthesis(self) -> None:
        structured_context: dict[str, object] = {
            "financial_modeling": _dcf(150.0),
            "ddm_calc": _ddm(),
        }
        vs = build_valuation_synthesis(structured_context, current_price=170.0, ticker="JPM")
        assert vs is not None
        method_names = {m.name for m in vs.methods}
        assert "ddm" in method_names

    def test_lbo_calculation_step_name_reaches_synthesis(self) -> None:
        structured_context: dict[str, object] = {
            "financial_modeling": _dcf(150.0),
            "lbo_calculation": _lbo(),
        }
        vs = build_valuation_synthesis(structured_context, current_price=170.0, ticker="AAPL")
        assert vs is not None
        method_names = {m.name for m in vs.methods}
        assert "lbo" in method_names


# ---------------------------------------------------------------------------
# Contract 3: single-method → weighted_price is None
# ---------------------------------------------------------------------------


class TestSingleMethodWeightedPriceNone:
    def test_weighted_price_none_when_only_one_method(self) -> None:
        """When only 1 method resolves, we must not surface a fake weighted average."""
        methods = [
            ValuationMethod(
                name="DCF", low=120.0, mid=150.0, high=180.0, confidence=0.85, source="dcf"
            )
        ]
        vs = synthesize_valuations(methods, current_price=170.0)
        assert (
            vs.weighted_price is None
        ), "Single-method synthesis must have weighted_price=None (no cross-check)"
        assert vs.upside_downside is None

    def test_weighted_price_none_propagates_from_build_synthesis(self) -> None:
        """build_valuation_synthesis with only DCF (no comps) → weighted_price None."""
        structured_context: dict[str, object] = {
            "financial_modeling": _dcf(150.0),
            # No peer_analysis → only DCF method resolves
        }
        vs = build_valuation_synthesis(structured_context, current_price=170.0, ticker="AAPL")
        assert vs is not None, "Should still return a ValuationSynthesis with 1 method"
        assert len(vs.methods) == 1
        assert vs.weighted_price is None

    def test_isinstance_check_on_result_not_prompt(self) -> None:
        """DCF field is present via isinstance on the result object, not a prompt string."""
        structured_context: dict[str, object] = {
            "financial_modeling": _dcf(150.0),
            "peer_analysis": _peer_comps(),
        }
        vs = build_valuation_synthesis(structured_context, current_price=170.0, ticker="AAPL")
        assert vs is not None
        # Confirm the DCF method came from an actual DCFResult, not a magic string
        dcf_method = next((m for m in vs.methods if m.name == "dcf"), None)
        assert dcf_method is not None
        # The mid must equal the DCFResult.implied_price (±20% band, mid is implied_price)
        assert dcf_method.mid == 150.0, f"DCF mid {dcf_method.mid} should equal implied_price 150.0"


class TestGuardExitReasonsReachArtifact:
    def test_comps_guard_exit_reason_lands_on_synthesis_warnings(self) -> None:
        """comps_pe 被守卫请出场时,退出原因必须落在 ValuationSynthesis.warnings
        (builder 收割进 artifact),不能只活在 debug 日志——TSLA 复验 run
        (run_413ad4913cc1,2026-06-10)里 basis 说「only one method resolved」
        而读者看不到另一半句子。fixture 走 trailing 路径(无 forward EPS),
        pe_sample_n=1 确定性触发 thin-sample 守卫。"""
        comps = _peer_comps()
        comps.pe_sample_n = 1
        structured_context: dict[str, object] = {
            "financial_modeling": _dcf(40.0),
            "peer_analysis": comps,
        }
        vs = build_valuation_synthesis(structured_context, current_price=396.0, ticker="TSLA")
        assert vs is not None
        assert [m.name for m in vs.methods] == ["dcf"], "comps_pe 应被 thin-sample 守卫退出"
        assert any("样本仅 1 家" in w and "方法退出" in w for w in vs.warnings)

    def test_comps_pb_guard_exit_reason_lands_on_synthesis_warnings(self) -> None:
        """兄弟位置:comps_pb 是 comps_pe 的姊妹腿,共用 _comps_median_refusal 与
        同一条 "方法退出" surface 约定,但在此之前没有任何测试钉住 P/B 腿的退出原因
        也能进 artifact——正是兄弟漏修的高发形状(修了 comps_pe 吞点,漏 comps_pb)。
        commodity-cyclical(industry=Steel)把 comps_pb 当主倍数走;pb_sample_n=1
        确定性触发 thin-sample 守卫,拒因必须落在 ValuationSynthesis.warnings,
        而不是只活在 debug 日志。"""
        structured_context: dict[str, object] = {
            "financial_modeling": _dcf(40.0),
            "peer_analysis": _cyclical_peer_comps_thin_pb(),
            "data_collection": _financial_data(industry="Steel"),
        }
        vs = build_valuation_synthesis(structured_context, current_price=100.0, ticker="X")
        assert vs is not None
        assert "comps_pb" not in [m.name for m in vs.methods], "comps_pb 应被 thin-sample 守卫退出"
        assert any(
            "comps_pb" in w and "样本仅 1 家" in w and "方法退出" in w for w in vs.warnings
        ), f"comps_pb 退出原因必须 surface 到 vs.warnings,实际: {vs.warnings}"

    @pytest.mark.parametrize("method", ["comps_pe", "comps_pb"])
    @pytest.mark.parametrize(
        "sample_n,target_multiple,branch",
        [
            (1, 18.0, "thin-sample"),  # 0 < n < 3 → 单一对手不构成中位数
            (5, 322.0, "premise-mismatch"),  # 322x vs 5.8x = 55x > 10x 上限
        ],
    )
    def test_relative_multiple_refusal_carries_surfacing_marker(
        self, method: str, sample_n: int, target_multiple: float, branch: str
    ) -> None:
        """兄弟摊开:comps_pe / comps_pb 共用 _comps_median_refusal,其**每一条**拒因
        分支都必须带 build_valuation_synthesis 转发时过滤的 "方法退出" 标记——少了它,
        该方法的退出原因会被 logger.debug 吞掉、永不进 artifact(run_413ad4913cc1 形状)。
        producer 侧钉死;consumer 侧由上面的 comps_pe/comps_pb 端到端测试钉死,两端合拢。"""
        reason = _comps_median_refusal(
            median_val=5.8,
            sample_n=sample_n,
            target_multiple=target_multiple,
            label="P/E",
            method=method,
        )
        assert reason is not None, f"{method} {branch} 分支应产生拒因"
        assert "方法退出" in reason, f"{method} {branch} 拒因缺 surface 标记,会被吞掉: {reason!r}"
        assert method in reason, f"拒因必须标明是哪个方法退出: {reason!r}"


def _financial_data(
    *, reporting: str = "USD", quote: str = "USD", industry: str | None = None
) -> FinancialData:
    """Minimal single-currency FinancialData with a real net-debt bridge."""
    return FinancialData(
        ticker="AAPL",
        timestamp=datetime.now(tz=timezone.utc),
        income=IncomeStatement(revenue=390e9, ebitda=120e9, net_income=95e9),
        balance=BalanceSheet(total_debt=110e9, total_cash=62e9),
        market=MarketData(
            market_cap=2.8e12,
            shares_outstanding=15.4e9,
            current_price=170.0,
            industry=industry,
        ),
        reporting_currency=reporting,
        quote_currency=quote,
    )


def _forward(*, forward_ebitda: float | None = 130e9) -> ForwardFinancials:
    return ForwardFinancials(
        ticker="AAPL",
        forward_eps=7.0,
        forward_revenue=420e9,
        forward_ebitda=forward_ebitda,
        forward_fcf=None,
        confidence="high",
        source="test",
        warnings=[],
        fiscal_period="2026-09-30",
    )


class TestEvEbitdaBandRevivesMethod:
    """The EV/EBITDA reverse-multiple row was structurally dead in production —
    both callers passed band=None, so it never fired regardless of inputs. Wiring
    the self historical EV/EBITDA band (a real degraded proxy: own历史倍数 P25/P75
    × forward consensus EBITDA − current net debt, every input reported) revives
    it, giving the synthesis MORE corroborating methods. Pins that the band, once
    threaded, actually emits the row and that the degradation is recorded."""

    def test_ev_ebitda_row_emitted_when_band_threaded(self) -> None:
        structured_context: dict[str, object] = {
            "financial_modeling": _dcf(150.0),
            "data_collection": _financial_data(),
            "forward_financials": _forward(),
        }
        vs = build_valuation_synthesis(
            structured_context,
            current_price=170.0,
            ticker="AAPL",
            historical_ev_ebitda_band=(20.0, 30.0),
            historical_ev_ebitda_sample_n=900,
        )
        assert vs is not None
        assert "ev_ebitda" in [
            m.name for m in vs.methods
        ], "EV/EBITDA must appear once the band is threaded — it was dead before"

    def test_ev_ebitda_row_absent_without_band(self) -> None:
        """No band threaded (the old production state) → row stays dead. This is the
        exact regression the fix addresses: same inputs, band=None → no row."""
        structured_context: dict[str, object] = {
            "financial_modeling": _dcf(150.0),
            "data_collection": _financial_data(),
            "forward_financials": _forward(),
        }
        vs = build_valuation_synthesis(structured_context, current_price=170.0, ticker="AAPL")
        assert vs is not None
        assert "ev_ebitda" not in [m.name for m in vs.methods]

    def test_ev_ebitda_withheld_on_currency_mismatch_not_fabricated(self) -> None:
        """A native-currency forward EBITDA must NOT mix with a USD net-debt bridge.
        reporting ≠ quote → forward_ebitda gated out → row drops (no fabrication)."""
        structured_context: dict[str, object] = {
            "financial_modeling": _dcf(150.0),
            "data_collection": _financial_data(reporting="TWD", quote="USD"),
            "forward_financials": _forward(),
        }
        vs = build_valuation_synthesis(
            structured_context,
            current_price=170.0,
            ticker="TSM",
            historical_ev_ebitda_band=(20.0, 30.0),
            historical_ev_ebitda_sample_n=900,
        )
        assert vs is not None
        assert "ev_ebitda" not in [m.name for m in vs.methods]

    def test_degradation_recorded_on_emitted_row(self) -> None:
        """The band's sample depth must surface on the row's warnings so the dial
        and the analyst see a thin-history reverse multiple for what it is."""
        row = _ev_ebitda_method(40e9, (20.0, 30.0), 2.4e9, 30e9, band_sample_n=120)
        assert row is not None
        assert any("120 个样本" in w and "历史" in w for w in row.warnings)

    def test_no_degradation_warning_when_sample_n_unknown(self) -> None:
        """band_sample_n=None (hand-built / legacy caller) → no fabricated count."""
        row = _ev_ebitda_method(40e9, (20.0, 30.0), 2.4e9, 30e9, band_sample_n=None)
        assert row is not None
        assert row.warnings == []
