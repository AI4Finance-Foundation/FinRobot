"""Tests for build_thesis_prompt — the pure thesis-prompt assembler.

Drives the assembler with real synthesize_valuations + resolve_canonical_thesis
inputs (no async shell, no LLM) and pins the load-bearing prompt invariants:
the data-health gate block, the authoritative target/market-price block, the
strict-numeric-discipline whitelist, the segment-grounding constant, and the
untrusted-news-headline wrapping of injected catalyst text.
"""

from finrobot.engine.models.financial import (
    CatalystAnalysis,
    CatalystEvent,
    DCFInputs,
    DCFResult,
    MarketImpliedCheck,
    ValuationMethod,
)
from finrobot.engine.compute.operators.valuation_synthesis import (
    resolve_canonical_thesis,
    synthesize_valuations,
)
from finrobot.engine.pipelines._thesis_prompt import build_thesis_prompt


def _build(methods, current_price, ticker="AAPL", extra_context=None):
    vs = synthesize_valuations(methods, current_price=current_price)
    canonical = resolve_canonical_thesis(vs, ticker)
    context: dict[str, object] = {"valuation_synthesis": vs}
    if extra_context:
        context.update(extra_context)
    return build_thesis_prompt("BASE PROMPT", context, canonical)


def _unreachable_dcf(*, cyclical: bool) -> DCFResult:
    """A growth-unreachable (option-value) DCFResult. When ``cyclical`` the inputs
    carry the seed's cyclical_normalization + a through-cycle ebitda_margin band so
    the prompt can reframe the gap per the design's 审校修正 1."""
    return _dcf_result(
        cyclical=cyclical,
        market_implied=MarketImpliedCheck(
            horizon_years=5,
            growth_unreachable=True,
            growth_ceiling=0.50,
            ceiling_price=406.0,
        ),
    )


def _reachable_dcf(*, cyclical: bool) -> DCFResult:
    """A solvable market-implied DCFResult (MU post deep-history: implied ~28%/yr
    inside the bracket, growth_unreachable=False). The cyclical permanence reframe
    must still fire on this branch."""
    return _dcf_result(
        cyclical=cyclical,
        market_implied=MarketImpliedCheck(
            horizon_years=10,
            implied_growth=0.281,
            implied_wacc=0.049,
            growth_unreachable=False,
        ),
    )


def _dcf_result(*, cyclical: bool, market_implied: MarketImpliedCheck) -> DCFResult:
    prov: dict[str, str] = {}
    if cyclical:
        prov["cyclical_normalization"] = "判定为大宗周期股(memory/storage) → through-cycle 正常化"
        prov["ebitda_margin"] = "52.9%（峰 49.3% / 谷 -37.0% / 中位 28.9% / 均值 20.1%，7 年）"
    inputs = DCFInputs(
        revenue_base=58e9,
        revenue_growth_rates=[0.15, 0.10, 0.08, 0.06, 0.04],
        ebitda_margin=0.529,
        capex_pct_revenue=0.24,
        nwc_pct_revenue=0.05,
        da_pct_revenue=0.24,
        tax_rate=0.15,
        risk_free_rate=0.045,
        beta=1.4,
        equity_risk_premium=0.055,
        cost_of_debt=0.04,
        debt_ratio=0.2,
        terminal_growth_rate=0.025,
        shares_outstanding=1.13e9,
        net_debt=10e9,
        assumption_provenance=prov,
    )
    return DCFResult(
        cost_of_equity=0.12,
        wacc=0.11,
        projection_years=5,
        projected_revenue=[67e9, 74e9, 80e9, 85e9, 88e9],
        projected_ebitda=[35e9, 39e9, 42e9, 45e9, 47e9],
        projected_fcf=[10e9, 12e9, 14e9, 15e9, 16e9],
        terminal_value=300e9,
        pv_terminal=180e9,
        pv_fcf_total=60e9,
        enterprise_value=240e9,
        equity_value=230e9,
        implied_price=187.0,
        market_implied=market_implied,
        inputs=inputs,
    )


class TestBuildThesisPrompt:
    def test_gate_failed_block(self):
        """2.57x method spread (DCF $86 vs Comps $221) trips the data-health gate."""
        methods = [
            ValuationMethod(name="DCF", low=70, mid=86, high=100, confidence=0.5, source="DCF"),
            ValuationMethod(
                name="Comps", low=190, mid=221, high=260, confidence=0.5, source="Comps"
            ),
        ]
        prompt = _build(methods, current_price=180.0)
        assert "DATA-HEALTH GATE TRIPPED — DO NOT STATE A PRICE TARGET" in prompt
        assert "MUST be exactly 'REVIEW'" in prompt
        # On the gate path no authoritative target block is injected.
        assert "AUTHORITATIVE PRICE TARGET (do not deviate)" not in prompt

    def test_converged_target_block(self):
        """Three converging methods → authoritative target + market-price block."""
        methods = [
            ValuationMethod(name="DCF", low=210, mid=245, high=290, confidence=0.5, source="DCF"),
            ValuationMethod(
                name="EV/EBITDA", low=220, mid=250, high=280, confidence=0.3, source="Comps"
            ),
            ValuationMethod(name="P/E", low=210, mid=240, high=260, confidence=0.2, source="PE"),
        ]
        prompt = _build(methods, current_price=230.0)
        assert "AUTHORITATIVE PRICE TARGET (do not deviate)" in prompt
        assert "AUTHORITATIVE CURRENT MARKET PRICE" in prompt
        assert "DATA-HEALTH GATE TRIPPED" not in prompt

    def test_always_contains_numeric_discipline_and_segment_sections(self):
        """The whitelist + segment-grounding constants land regardless of branch."""
        methods = [
            ValuationMethod(name="DCF", low=210, mid=245, high=290, confidence=0.5, source="DCF"),
            ValuationMethod(
                name="EV/EBITDA", low=220, mid=250, high=280, confidence=0.3, source="Comps"
            ),
        ]
        prompt = _build(methods, current_price=230.0)
        assert "STRICT NUMERIC DISCIPLINE" in prompt
        assert "SEGMENT / GEOGRAPHIC REVENUE" in prompt

    def test_catalyst_section_wraps_headlines_as_untrusted(self):
        """Injected catalyst headlines are wrapped in an untrusted-news block."""
        methods = [
            ValuationMethod(name="DCF", low=210, mid=245, high=290, confidence=0.5, source="DCF"),
            ValuationMethod(
                name="EV/EBITDA", low=220, mid=250, high=280, confidence=0.3, source="Comps"
            ),
        ]
        catalyst = CatalystAnalysis(
            events=[],
            overall_sentiment="bullish",
            key_catalysts=["New product cycle"],
            net_sentiment=1.5,
            top_positive=[
                CatalystEvent(
                    category="product_launch",
                    headline="Company unveils next-gen chip",
                    sentiment="positive",
                    impact_score=4,
                    probability=0.7,
                    reasoning="Strong demand signal",
                )
            ],
        )
        prompt = _build(
            methods,
            current_price=230.0,
            extra_context={"catalyst_analysis": catalyst},
        )
        assert "Catalyst Analysis:" in prompt
        assert "<untrusted_news_headline>" in prompt

    def test_cyclical_option_value_reframes_per_audit_correction(self):
        """A growth-unreachable COMMODITY-CYCLICAL gets the 审校修正 1 framing:
        cite the through-cycle 峰/谷/中位 band, frame the gap as the PEAK held as a
        PERPETUAL steady state, and forbid the attackable 'above historical peak =
        impossible' claim (reversible by the latest super-cycle quarter)."""
        methods = [
            ValuationMethod(name="DCF", low=160, mid=187, high=237, confidence=0.5, source="DCF"),
            ValuationMethod(
                name="comps_pb", low=170, mid=200, high=230, confidence=0.6, source="Comps"
            ),
        ]
        prompt = _build(
            methods,
            current_price=949.88,
            ticker="MU",
            extra_context={"financial_modeling": _unreachable_dcf(cyclical=True)},
        )
        assert "COMMODITY-CYCLICAL" in prompt
        assert "PERPETUAL steady state" in prompt
        # the through-cycle band travels from provenance (not invented)
        assert "峰 49.3% / 谷 -37.0%" in prompt
        # the un-attackable point is permanence, NOT 'implied margin above the peak'
        assert "do NOT claim the implied" in prompt
        assert "permanence, not the level" in prompt

    def test_non_cyclical_option_value_has_no_cyclical_clause(self):
        """The cyclical reframing is gated on cyclical_normalization provenance — a
        non-cyclical option-value name (TSLA-type) keeps the generic narrative."""
        methods = [
            ValuationMethod(name="DCF", low=20, mid=28, high=40, confidence=0.5, source="DCF"),
            ValuationMethod(name="comps_pe", low=22, mid=30, high=42, confidence=0.5, source="C"),
        ]
        prompt = _build(
            methods,
            current_price=418.0,
            ticker="TSLA",
            extra_context={"financial_modeling": _unreachable_dcf(cyclical=False)},
        )
        # the generic option-value narrative still fires
        assert "option-value" in prompt
        # but none of the cyclical-specific reframing
        assert "COMMODITY-CYCLICAL" not in prompt
        assert "PERPETUAL steady state" not in prompt

    def test_cyclical_reachable_growth_still_reframes(self):
        """MU post deep-history: the anchor rises and the implied growth becomes
        solvable (~28%/yr, growth_unreachable=False) — yet a decade of that growth
        at through-cycle margins is still the super-cycle priced as permanent. The
        permanence reframe must fire on the reachable branch too, not only on
        growth_unreachable."""
        methods = [
            ValuationMethod(name="DCF", low=200, mid=246, high=295, confidence=0.5, source="DCF"),
            ValuationMethod(
                name="comps_pb", low=900, mid=1005, high=1100, confidence=0.6, source="Comps"
            ),
        ]
        prompt = _build(
            methods,
            current_price=891.0,
            ticker="MU",
            extra_context={"financial_modeling": _reachable_dcf(cyclical=True)},
        )
        # the generic reality-check line carries the solved implied growth
        assert "implies ~28.1%/yr" in prompt
        # and the cyclical permanence reframe rides along
        assert "COMMODITY-CYCLICAL" in prompt
        assert "PERPETUAL steady state" in prompt
        assert "峰 49.3% / 谷 -37.0%" in prompt
        assert "permanence, not the level" in prompt

    def test_industry_cyclical_auto_oem_gets_no_supercycle_clause(self):
        """A volume-cyclical auto OEM (TSLA — industry-whitelist arm, provenance
        names 行业白名单 not memory/storage) must NOT inherit the memory-supercycle
        permanence framing: its price gap is option value, not margin permanence.
        Live TSLA artifact 2fadab regressed exactly this way ("Tesla's stock
        pricing suggests a super-cycle peak")."""
        dcf = _reachable_dcf(cyclical=True)
        dcf.inputs.assumption_provenance["cyclical_normalization"] = (
            "判定为大宗周期股(行业白名单命中:钢铁/航运/化工/油气/汽车等大宗周期) "
            "→ 盈利基底走 through-cycle 正常化"
        )
        methods = [
            ValuationMethod(name="DCF", low=40, mid=52, high=70, confidence=0.5, source="DCF"),
            ValuationMethod(
                name="comps_pb", low=200, mid=254, high=300, confidence=0.6, source="Comps"
            ),
        ]
        prompt = _build(
            methods,
            current_price=388.88,
            ticker="TSLA",
            extra_context={"financial_modeling": dcf},
        )
        # generic reality-check line still present
        assert "implies ~28.1%/yr" in prompt
        # no memory-supercycle permanence framing
        assert "COMMODITY-CYCLICAL" not in prompt
        assert "PERPETUAL steady state" not in prompt

    def test_non_cyclical_reachable_growth_has_no_cyclical_clause(self):
        """A non-cyclical with solvable implied growth keeps the plain
        reality-check line — no permanence reframe."""
        methods = [
            ValuationMethod(name="DCF", low=200, mid=246, high=295, confidence=0.5, source="DCF"),
            ValuationMethod(
                name="comps_pe", low=210, mid=250, high=290, confidence=0.5, source="C"
            ),
        ]
        prompt = _build(
            methods,
            current_price=260.0,
            ticker="AAPL",
            extra_context={"financial_modeling": _reachable_dcf(cyclical=False)},
        )
        assert "implies ~28.1%/yr" in prompt
        assert "COMMODITY-CYCLICAL" not in prompt
        assert "PERPETUAL steady state" not in prompt
