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
from finrobot.engine.compute.operators.valuation_synthesis import (
    resolve_canonical_thesis,
    synthesize_valuations,
)
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


def _cyclical_peer_comps_no_bvps() -> PeerComps:
    """Cyclical peer set with a healthy P/B median (pb_sample_n≥3) but the TARGET
    carries no book value per share — comps_pb is degraded ("退回 P/E") for a
    substantive reason (负权益 / provider 未报 / ADR 跨币种), the sibling shape of
    the cyclical comps_pe suppression. The reason must surface, not be swallowed."""
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
        book_value_per_share=None,
        pb_ratio=None,
    )
    peer = target.model_copy(update={"ticker": "Y", "book_value_per_share": 28.0, "pb_ratio": 1.1})
    return PeerComps(
        target=target,
        peers=[peer],
        median_pe=8.5,
        median_ev_ebitda=5.5,
        median_pb=1.2,
        pb_sample_n=4,
    )


def _peer_comps_thin_pe() -> PeerComps:
    """Non-cyclical peer set whose P/E median rests on a single peer
    (``pe_sample_n=1``) → comps_pe thin-sample refusal (the original兄弟 case)."""
    comps = _peer_comps()
    comps.pe_sample_n = 1
    return comps


def _loss_making_peer_comps() -> PeerComps:
    """Pre-profitability cohort — target AND peers are loss-making (TTM net income
    ≤ 0), so no P/E median exists and comps_pe is structurally INAPPLICABLE (a
    negative-earnings P/E is undefined, not merely missing data). A substantive
    method exit, sibling of the thin-sample / cyclical exits — its reason must
    surface with the 方法退出 marker, not silently degrade into a "forward EPS 不可得"
    data-absence line."""
    target = CompanyFinancials(
        ticker="RIVN",
        name="Rivian",
        revenue=5e9,
        ebitda=-4e9,
        net_income=-5e9,
        market_cap=16e9,
        total_debt=5e9,
        total_cash=8e9,
        gross_margin=-0.30,
        operating_margin=-1.0,
        pe_ratio=None,
    )
    peer = target.model_copy(update={"ticker": "LCID", "net_income": -3e9, "pe_ratio": None})
    return PeerComps(target=target, peers=[peer], median_pe=None, median_ev_ebitda=None)


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


def _ddm_nonpositive() -> DDMResult:
    """DDM whose per-share equity value is ≤ 0 (degenerate / direct-construction
    path) → _ddm_method drops it. The drop reason must surface, not vanish — the
    aggregate had no elif for ddm at all, so a provided-but-degenerate DDM was the
    one method that fell out with zero diagnostics."""
    return _ddm().model_copy(update={"equity_value_per_share": -1.0})


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
        assert "dcf" in method_names, (
            f"DCF method missing from synthesis — Bug A regression. Got: {method_names}"
        )

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
        assert vs.weighted_price is not None, (
            "weighted_price must be a float when ≥2 methods are present"
        )
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
        assert vs.weighted_price is None, (
            "Single-method synthesis must have weighted_price=None (no cross-check)"
        )
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
        assert any("sample is only 1" in w and "method withheld" in w for w in vs.warnings)

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
            "comps_pb" in w and "sample is only 1" in w and "method withheld" in w
            for w in vs.warnings
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
        assert "method withheld" in reason, (
            f"{method} {branch} 拒因缺 surface 标记,会被吞掉: {reason!r}"
        )
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
        assert "ev_ebitda" in [m.name for m in vs.methods], (
            "EV/EBITDA must appear once the band is threaded — it was dead before"
        )

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

    def test_ev_ebitda_shows_on_currency_mismatch_off_canonical_ttm(self) -> None:
        """batch2: the ev leg is DECOUPLED from the forward FX guard — it prices off the
        canonical TTM operating EBITDA (income.ebitda), not the native forward consensus.
        income.ebitda, the net-debt bridge and shares all come from ONE canonical snapshot
        (same currency) and the band is a unitless ratio, so no cross-currency mix is
        possible. A reporting ≠ quote issuer (TSM/SAP-class) therefore now SHOWS the row
        instead of dropping it — the intentional ADR behavior change."""
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
        ev = next((m for m in vs.methods if m.name == "ev_ebitda"), None)
        assert ev is not None, "ev leg must show — canonical TTM EBITDA carries no FX mix"
        # priced off TTM operating EBITDA (income.ebitda), single-caliber label, never forward.
        assert "ttm_ebitda" in ev.source and "forward" not in ev.source.lower()

    def test_degradation_recorded_on_emitted_row(self) -> None:
        """The band's sample depth must surface on the row's warnings so the dial
        and the analyst see a thin-history reverse multiple for what it is."""
        row = _ev_ebitda_method(40e9, (20.0, 30.0), 2.4e9, 30e9, band_sample_n=120)
        assert row is not None
        assert any("120 samples" in w and "historical" in w for w in row.warnings)

    def test_no_degradation_warning_when_sample_n_unknown(self) -> None:
        """band_sample_n=None (hand-built / legacy caller) → no fabricated sample count.
        The unconditional no-growth-credit disclosure (batch2 condition ii) is still
        present — only the sample-depth line is gated on band_sample_n."""
        row = _ev_ebitda_method(40e9, (20.0, 30.0), 2.4e9, 30e9, band_sample_n=None)
        assert row is not None
        assert not any("samples" in w for w in row.warnings)  # no fabricated count
        # the trailing-earnings / no-growth-credit conservatism disclosure is structural
        assert any("systematically conservative" in w for w in row.warnings)

    def test_negative_equity_diagnosed_with_marker_not_misreported(self) -> None:
        """Step3 兄弟漏洞:净债 > 即便 p75 乐观倍数下的隐含 EV → 隐含股权全程 ≤ 0,方法 drop。
        此前 aggregate 的 elif 链落到 else,误报「historical valuation band ... unavailable」
        (band/TTM EBITDA 其实在场)。修后:_ev_ebitda_method 记带 marker 的负权益拒因,
        aggregate 不再误诊。直测 aggregate_valuation(端到端 band 穿线另需 financial_data
        plumbing,此处直给输入更确定)。"""
        agg = aggregate_valuation(
            ticker="X",
            current_price=100.0,
            ttm_ebitda=10e9,
            historical_ev_ebitda_band=(5.0, 8.0),  # p75 × ttm = 80e9
            shares_outstanding=2e9,
            current_net_debt=200e9,  # > 80e9 → implied equity ≤ 0 across the whole band
        )
        assert "ev_ebitda" not in [m.method for m in agg.methods]
        assert any(
            "ev_ebitda" in w and "method withheld" in w and "equity" in w for w in agg.warnings
        ), f"negative-equity reason must surface with the marker: {agg.warnings}"
        assert not any(
            "ev_ebitda: historical valuation band (PR3 not wired)" in w for w in agg.warnings
        ), "ev_ebitda must not be mis-diagnosed as band/forward unavailable (they are present)"


# ---------------------------------------------------------------------------
# 兄弟摊开 sweep: EVERY substantive method-suppression reason surfaces to artifact
# ---------------------------------------------------------------------------

# 每行 = 一个被 guard「请出场」的估值方法,因 substantive 分析理由(非单纯输入缺失)
# 退出/降级。其原因 **必须** 进 ValuationSynthesis.warnings(带 "方法退出" 标记被
# build_valuation_synthesis 转发),绝不能只活在 debug 日志(run_413ad4913cc1 兄弟形状:
# basis 写「only one method resolved」而读者看不到另一半句子)。新增一种 substantive
# 抑制 → 这里加一行,否则它未经此闸就发布。注意区分:「无 X artifact / 输入不可得」是
# 行未展示的 data-absence 诊断,不在此列——那不是 guard 把能跑的方法请出场。
_SUPPRESSION_SWEEP = [
    # (case_id, structured_context factory, 期望出现在 vs.warnings 的原因片段)
    (
        "comps_pe_cyclical_forward_peak_suppression",
        lambda: {
            "financial_modeling": _dcf(40.0),
            "peer_analysis": _cyclical_peer_comps_thin_pb(),
            "data_collection": _financial_data(industry="Steel"),
        },
        "comps_pe: cyclical",
    ),
    (
        "comps_pb_book_value_unavailable",
        lambda: {
            "financial_modeling": _dcf(40.0),
            "peer_analysis": _cyclical_peer_comps_no_bvps(),
            "data_collection": _financial_data(industry="Steel"),
        },
        "comps_pb: target book value per share unavailable",
    ),
    (
        "comps_pb_thin_sample",
        lambda: {
            "financial_modeling": _dcf(40.0),
            "peer_analysis": _cyclical_peer_comps_thin_pb(),
            "data_collection": _financial_data(industry="Steel"),
        },
        "comps_pb: peer P/B sample is only 1",
    ),
    (
        "comps_pe_thin_sample",
        lambda: {
            "financial_modeling": _dcf(40.0),
            "peer_analysis": _peer_comps_thin_pe(),
        },
        "sample is only 1",
    ),
    (
        "comps_pe_loss_making_pe_inapplicable",
        lambda: {
            "financial_modeling": _dcf(40.0),
            "peer_analysis": _loss_making_peer_comps(),
            "forward_financials": _forward(),
            "data_collection": _financial_data(),
        },
        "P/E method cannot be applied",
    ),
    (
        "dcf_nonpositive_implied_price",
        lambda: {
            "financial_modeling": _dcf(-5.0),  # implied price ≤ 0 → method withheld
            "peer_analysis": _peer_comps(),  # comps_pe co-resolves so vs is non-None
        },
        "dcf: implied share price",
    ),
    (
        "ddm_nonpositive_equity",
        lambda: {
            "financial_modeling": _dcf(40.0),  # co-resolves so vs is non-None
            "ddm_calc": _ddm_nonpositive(),  # equity/share ≤ 0 → method withheld
        },
        "ddm: equity value per share",
    ),
    # Balance-sheet financial (bank / insurer): the cash-flow methods DCF / EV-EBITDA /
    # P-FCF are category errors (deposits / float / reserves are operating raw material,
    # not financing) and are suppressed at the aggregate. Each suppression reason must
    # surface to vs.warnings AND the analyst headline (basis) — the same sibling闸 the
    # per-method exits ride. The report path additionally withholds the whole FCFF-DCF at
    # the SOURCE (equity_research._execute_financial_modeling) so no DCFResult exists to
    # begin with; these rows pin the belt-and-suspenders aggregate suppression that keeps
    # the football field clean even if a DCF is somehow present. A surviving bank method
    # (DDM) keeps vs non-None. One row per suppressed cash-flow method.
    (
        "financial_sector_dcf_suppressed",
        lambda: {
            "ddm_calc": _ddm(),  # bank lead method → vs non-None
            "data_collection": _financial_data(industry="Banks - Diversified"),
        },
        "dcf: financial-sector issuer",
    ),
    (
        "financial_sector_ev_ebitda_suppressed",
        lambda: {
            "ddm_calc": _ddm(),
            "data_collection": _financial_data(industry="Banks - Diversified"),
        },
        "ev_ebitda: financial-sector issuer",
    ),
    (
        "financial_sector_p_fcf_suppressed",
        lambda: {
            "ddm_calc": _ddm(),
            "data_collection": _financial_data(industry="Banks - Diversified"),
        },
        "p_fcf: financial-sector issuer",
    ),
]


class TestMethodSuppressionSweep:
    """兄弟位置闸:遍历每个被 guard 请出场的估值方法,其退出/抑制原因都必须 surface
    到 artifact(vs.warnings),不是只进 debug 日志。新增 substantive 抑制 → 在
    _SUPPRESSION_SWEEP 加一行,否则未经此闸就发布。"""

    @pytest.mark.parametrize(
        "context_factory,expected_fragment",
        [(c[1], c[2]) for c in _SUPPRESSION_SWEEP],
        ids=[c[0] for c in _SUPPRESSION_SWEEP],
    )
    def test_suppression_reason_surfaces(
        self, context_factory: object, expected_fragment: str
    ) -> None:
        vs = build_valuation_synthesis(context_factory(), current_price=100.0, ticker="X")  # type: ignore[operator]
        assert vs is not None, "被抑制方法之外仍有方法解析 → 应产出 ValuationSynthesis"
        assert any(expected_fragment in w and "method withheld" in w for w in vs.warnings), (
            f"抑制原因被吞掉,未带标记进 vs.warnings: {vs.warnings}"
        )


# ---------------------------------------------------------------------------
# 兄弟位置闸(headline 层): 抑制原因必须到达分析师真正读的 CanonicalThesis.basis,
# 不能只活在 vs.warnings(那只是 artifact 的另一个 list 面)。basis 当前从
# method_breakdown + range + degradation_note 建,而 degradation_note 只来自
# confidence dial、从不读 vs.warnings——所以 step1/step2 把退出原因 forward 进
# vs.warnings 后,headline 仍只说 "only one method resolved",读者看不到另一半
# 句子(run_413ad4913cc1 形状的根)。叙事 prompt 读 canonical.basis,故修好 basis
# 同时修好叙事。复用 _SUPPRESSION_SWEEP: 同一张表同时钉 vs.warnings 面与 basis 面。
# ---------------------------------------------------------------------------


class TestSuppressionReasonReachesHeadline:
    """每个 substantive 抑制原因必须出现在 CanonicalThesis.basis(分析师 headline),
    不只在 vs.warnings。新增 substantive 抑制 → _SUPPRESSION_SWEEP 加一行,本闸自动覆盖。"""

    @pytest.mark.parametrize(
        "context_factory,expected_fragment",
        [(c[1], c[2]) for c in _SUPPRESSION_SWEEP],
        ids=[c[0] for c in _SUPPRESSION_SWEEP],
    )
    def test_suppression_reason_reaches_canonical_basis(
        self, context_factory: object, expected_fragment: str
    ) -> None:
        vs = build_valuation_synthesis(context_factory(), current_price=100.0, ticker="X")  # type: ignore[operator]
        assert vs is not None
        thesis = resolve_canonical_thesis(vs, "X")
        assert thesis.basis is not None, "抑制场景仍有方法解析 → basis 不应为 None"
        assert expected_fragment in thesis.basis, (
            f"抑制原因未到达分析师 headline(basis): 期望片段 {expected_fragment!r} 不在 basis。"
            f" basis 只读 degradation_note 不读 vs.warnings = split-brain。\n"
            f"basis={thesis.basis!r}\nvs.warnings={vs.warnings!r}"
        )


# ---------------------------------------------------------------------------
# Re-rating disclosure warnings (slice 2 plumbing, 2026-07-07). A multiples
# method whose implied multiple sits far from the target's own current multiple
# is betting on an unproven re-rating. Two deliberate surfaces, pinned here:
#   1. the warning MUST reach vs.warnings (report warnings section) via
#      build_valuation_synthesis's marker forwarding;
#   2. the warning MUST NOT be folded into CanonicalThesis.basis — the cover
#      prose stays lean (assumptions live on the football-field method row);
#      only "method withheld" exit reasons belong in basis.
# ---------------------------------------------------------------------------


def _rerating_context() -> dict[str, object]:
    """Forward comps path with a large implied re-rating: median_forward_pe=32
    vs self forward P/E = 100.0 / 7.0 ≈ 14.3 → ratio ≈ 2.24 > 1.25 threshold."""
    comps = _peer_comps()
    comps.median_forward_pe = 32.0
    comps.forward_pe_sample_n = 5
    return {
        "financial_modeling": _dcf(90.0),
        "peer_analysis": comps,
        "forward_financials": _forward(),
        "data_collection": _financial_data(),
    }


class TestReratingDisclosureReachesWarnings:
    def test_rerating_warning_forwarded_to_synthesis_warnings(self) -> None:
        """re-rating 披露必须经 RERATING_WARNING_MARKER 转发进 vs.warnings
        (报告 warnings 区);只进 REST agg.warnings = 外审读者看不见 = 白修。"""
        from finrobot.engine.compute.operators.valuation_aggregator import (
            RERATING_WARNING_MARKER,
        )

        vs = build_valuation_synthesis(_rerating_context(), current_price=100.0, ticker="X")
        assert vs is not None
        assert any("comps_pe" in m.name for m in vs.methods), "comps_pe 应正常出行(非退出)"
        assert any(RERATING_WARNING_MARKER in w for w in vs.warnings), (
            f"re-rating warning 未转发进 vs.warnings(报告面丢失): {vs.warnings!r}"
        )

    def test_rerating_warning_stays_out_of_canonical_basis(self) -> None:
        """有意行为:re-rating 披露不是方法退出,basis 的 withheld-only 过滤不许
        吸收它——封面保持克制,方法行 assumptions 已带同一信息。"""
        from finrobot.engine.compute.operators.valuation_aggregator import (
            RERATING_WARNING_MARKER,
        )

        vs = build_valuation_synthesis(_rerating_context(), current_price=100.0, ticker="X")
        assert vs is not None
        thesis = resolve_canonical_thesis(vs, "X")
        assert thesis.basis is not None
        assert RERATING_WARNING_MARKER not in thesis.basis, (
            "re-rating 披露泄漏进封面 basis——它不是 method-withheld 退出原因,"
            f"不属于 basis prose。basis={thesis.basis!r}"
        )
