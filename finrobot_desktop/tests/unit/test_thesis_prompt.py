"""Tests for build_thesis_prompt — the pure thesis-prompt assembler.

Drives the assembler with real synthesize_valuations + resolve_canonical_thesis
inputs (no async shell, no LLM) and pins the load-bearing prompt invariants:
the data-health gate block, the authoritative target/market-price block, the
strict-numeric-discipline whitelist, the segment-grounding constant, and the
untrusted-news-headline wrapping of injected catalyst text.
"""

from datetime import datetime, timezone

from finrobot.engine.models.financial import (
    CatalystAnalysis,
    CatalystEvent,
    DCFInputs,
    DCFResult,
    FinancialData,
    IncomeStatement,
    MarketData,
    MarketImpliedCheck,
    ValuationMethod,
)
from finrobot.engine.compute.operators.valuation_synthesis import (
    resolve_canonical_thesis,
    synthesize_valuations,
)
from finrobot.engine.pipelines._thesis_prompt import build_thesis_prompt


def _financial_data(
    *,
    current_price: float,
    high_52w: float | None = None,
    low_52w: float | None = None,
    trailing_1y_return_pct: float | None = None,
) -> FinancialData:
    return FinancialData(
        ticker="TEST",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        income=IncomeStatement(revenue=1.0),
        market=MarketData(
            market_cap=1.0,
            shares_outstanding=1.0,
            current_price=current_price,
            price_52w_high=high_52w,
            price_52w_low=low_52w,
            trailing_1y_return_pct=trailing_1y_return_pct,
        ),
    )


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
        # Provenance VALUES mirror the real English generator output (dcf_seed
        # `_cycle_stats` + the cyclical_normalization string), so this fixture
        # reflects what production actually injects — not a stale Chinese format.
        prov["cyclical_normalization"] = (
            "Classified as a commodity-cyclical (memory/storage whitelist / keyword hit) "
            "→ through-cycle normalization"
        )
        prov["ebitda_margin"] = (
            "52.9% (peak 49.3% / trough -37.0% / median 28.9% / mean 20.1%, 7yr)"
        )
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
    def test_point_withheld_block_still_issues_directional_verdict(self):
        """Option-value regime (DCF $12 + comps $26 agree but ~0.05x the $418
        market) → POINT withheld, but the verdict is STILL directional. The prompt
        must (a) NOT contain the deleted REVIEW instruction, (b) inject the
        directional recommendation, (c) forbid a price target / inventing a
        number, and (d) NOT inject the authoritative-target block."""
        methods = [
            ValuationMethod(name="dcf", low=10, mid=11.80, high=14, confidence=0.85, source="DCF"),
            ValuationMethod(
                name="comps_pe", low=21, mid=25.54, high=30, confidence=0.55, source="Comps"
            ),
        ]
        prompt = _build(methods, current_price=418.45)
        assert "POINT PRICE TARGET WITHHELD" in prompt
        assert "STILL ISSUE A DIRECTIONAL VERDICT" in prompt
        # The REVIEW state is deleted — its instruction must be gone.
        assert "REVIEW" not in prompt
        assert "AUTHORITATIVE RECOMMENDATION (do not deviate):" in prompt
        assert "`price_target` field MUST be null" in prompt
        assert "we never invent a number" in prompt
        # On the withheld path no authoritative-target block is injected.
        assert "AUTHORITATIVE PRICE TARGET (do not deviate)" not in prompt
        # ④ The withhold-reason instruction references the AUTHORITATIVE basis instead
        # of hardcoding "methods diverge" — so a fairly-valued bank isn't mis-narrated.
        assert "RESTATING" in prompt
        assert "do NOT" in prompt and "methods diverge" in prompt  # forbidden unless the basis says so
        assert "FAIRLY VALUED" in prompt

    def test_method_fidelity_rule_lists_only_run_methods(self):
        """④ The whitelist pins the exact methods run so the narrative cannot name a
        method that wasn't (JPM: P/B + P/E + RI narrated as DDM)."""
        methods = [
            ValuationMethod(
                name="comps_pb", low=200, mid=210, high=220, confidence=0.6, source="PB"
            ),
            ValuationMethod(
                name="comps_pe", low=260, mid=272, high=285, confidence=0.55, source="PE"
            ),
            ValuationMethod(
                name="residual_income", low=272, mid=309, high=369, confidence=0.6, source="RI"
            ),
        ]
        prompt = _build(methods, current_price=334.0)
        assert "METHOD FIDELITY RULE" in prompt
        assert "comps_pb, comps_pe, residual_income" in prompt
        assert "do not assume DDM or FCF-DCF were computed" in prompt

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
        assert "peak 49.3% / trough -37.0%" in prompt
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
        assert "peak 49.3% / trough -37.0%" in prompt
        assert "permanence, not the level" in prompt

    def test_reachable_growth_withheld_prompt_does_not_inject_option_value(self):
        """Contradiction fix (2026-06-16): on the point-withheld path, when the
        reverse-DCF read is REACHABLE (growth_unreachable=False), the prompt must NOT
        inject the unconditional 'the market prices option value the models cannot
        capture' framing — a reachable implied growth is AGGRESSIVE GROWTH, not
        optionality. Shipped MU output had price_target_basis asserting 'option value'
        while valuation_overview correctly read 'implied 36.9% growth'; the two
        surfaces contradicted. The nature-of-gap claim is the reverse-DCF's alone, and
        on the reachable branch its verdict is aggressive growth — never option value."""
        methods = [
            ValuationMethod(name="dcf", low=160, mid=188, high=226, confidence=0.85, source="DCF"),
            ValuationMethod(
                name="comps_pb", low=1200, mid=1414, high=1620, confidence=0.6, source="Comps"
            ),
        ]
        prompt = _build(
            methods,
            current_price=1088.0,
            ticker="MU",
            extra_context={"financial_modeling": _reachable_dcf(cyclical=True)},
        )
        assert "POINT PRICE TARGET WITHHELD" in prompt  # point withheld (span 7.5x)
        assert "implies ~28.1%/yr" in prompt  # the authoritative reachable read is cited
        # the contradictory unconditional option-value injection is GONE
        assert "option value" not in prompt.lower()
        assert "option-value" not in prompt.lower()

    def test_industry_cyclical_auto_oem_gets_no_supercycle_clause(self):
        """A volume-cyclical auto OEM (TSLA — industry-whitelist arm, provenance
        names 行业白名单 not memory/storage) must NOT inherit the memory-supercycle
        permanence framing: its price gap is option value, not margin permanence.
        Live TSLA artifact 2fadab regressed exactly this way ("Tesla's stock
        pricing suggests a super-cycle peak")."""
        dcf = _reachable_dcf(cyclical=True)
        dcf.inputs.assumption_provenance["cyclical_normalization"] = (
            "Classified as a commodity-cyclical (industry whitelist hit: steel / shipping / "
            "chemicals / oil & gas / autos and other commodity cyclicals) → through-cycle normalization"
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


class TestMomentumContext:
    """BACKLOG A2/P1-1: momentum context injection + whitelist + the mandatory
    hedge-paragraph instruction on strong verdict-vs-momentum divergence."""

    # Two tightly-clustered methods well above current_price → comfortably past
    # even the widest ("very_low", 50%) BUY band regardless of how the synthesis
    # grades confidence — the test only needs a robust BUY, not a specific tier.
    _BUY_METHODS = [
        ValuationMethod(name="DCF", low=280, mid=320, high=360, confidence=0.7, source="DCF"),
        ValuationMethod(name="Comps", low=300, mid=330, high=360, confidence=0.6, source="Comps"),
    ]
    # Symmetric SELL setup: methods well below current_price.
    _SELL_METHODS = [
        ValuationMethod(name="DCF", low=150, mid=180, high=210, confidence=0.6, source="DCF"),
        ValuationMethod(name="Comps", low=160, mid=190, high=220, confidence=0.5, source="Comps"),
    ]

    def test_momentum_context_injected_and_whitelisted(self):
        methods = [
            ValuationMethod(name="DCF", low=210, mid=245, high=290, confidence=0.5, source="DCF"),
            ValuationMethod(
                name="EV/EBITDA", low=220, mid=250, high=280, confidence=0.3, source="Comps"
            ),
        ]
        fd = _financial_data(
            current_price=80.0, high_52w=120.0, low_52w=70.0, trailing_1y_return_pct=-20.5
        )
        prompt = _build(methods, current_price=230.0, extra_context={"data_collection": fd})

        assert "AUTHORITATIVE MOMENTUM CONTEXT" in prompt
        assert "1-year price return: -20.5%" in prompt
        assert "52-week range position: 20%" in prompt  # (80-70)/(120-70)
        assert "Drawdown from 52-week high: -33.3%" in prompt  # (80-120)/120

        discipline = prompt[prompt.find("STRICT NUMERIC DISCIPLINE") :]
        assert "momentum_context.one_year_return_pct: -20.5%" in discipline
        assert "momentum_context.range_position_52w: 20%" in discipline
        assert "momentum_context.drawdown_from_52w_high_pct: -33.3%" in discipline

    def test_no_momentum_block_when_data_collection_absent(self):
        methods = [
            ValuationMethod(name="DCF", low=210, mid=245, high=290, confidence=0.5, source="DCF"),
            ValuationMethod(
                name="EV/EBITDA", low=220, mid=250, high=280, confidence=0.3, source="Comps"
            ),
        ]
        prompt = _build(methods, current_price=230.0)
        assert "AUTHORITATIVE MOMENTUM CONTEXT" not in prompt
        assert "MOMENTUM DIVERGENCE" not in prompt

    def test_no_momentum_lines_when_price_history_too_short(self):
        """A FinancialData with no 52w bounds / no 1y return (short history)
        degrades to zero momentum lines — never fabricates a partial read."""
        methods = [
            ValuationMethod(name="DCF", low=210, mid=245, high=290, confidence=0.5, source="DCF"),
            ValuationMethod(
                name="EV/EBITDA", low=220, mid=250, high=280, confidence=0.3, source="Comps"
            ),
        ]
        fd = _financial_data(current_price=230.0)
        prompt = _build(methods, current_price=230.0, extra_context={"data_collection": fd})
        assert "AUTHORITATIVE MOMENTUM CONTEXT" not in prompt

    def test_buy_with_strong_pullback_gets_mandatory_hedge_instruction(self):
        fd = _financial_data(current_price=200.0, trailing_1y_return_pct=-20.0)
        prompt = _build(
            self._BUY_METHODS,
            current_price=200.0,
            ticker="MU",
            extra_context={"data_collection": fd},
        )
        # Sanity: this setup really does resolve to a BUY.
        assert "AUTHORITATIVE RECOMMENDATION (do not deviate): BUY" in prompt
        assert "MOMENTUM DIVERGENCE — MANDATORY HEDGE PARAGRAPH" in prompt
        assert "momentum_divergence_note" in prompt
        # The instruction explicitly forbids touching the numbers already set.
        assert "must NOT change your `recommendation`, `price_target`, or confidence" in prompt

    def test_buy_with_mild_pullback_gets_no_hedge_instruction(self):
        """+5%/-5% momentum is ordinary — no divergence, no mandatory paragraph."""
        fd = _financial_data(current_price=200.0, trailing_1y_return_pct=-5.0)
        prompt = _build(
            self._BUY_METHODS,
            current_price=200.0,
            ticker="MU",
            extra_context={"data_collection": fd},
        )
        assert "AUTHORITATIVE RECOMMENDATION (do not deviate): BUY" in prompt
        assert "MOMENTUM DIVERGENCE" not in prompt

    def test_sell_with_strong_rally_gets_mandatory_hedge_instruction(self):
        fd = _financial_data(current_price=400.0, trailing_1y_return_pct=45.0)
        prompt = _build(
            self._SELL_METHODS,
            current_price=400.0,
            ticker="XYZ",
            extra_context={"data_collection": fd},
        )
        assert "AUTHORITATIVE RECOMMENDATION (do not deviate): SELL" in prompt
        assert "MOMENTUM DIVERGENCE — MANDATORY HEDGE PARAGRAPH" in prompt

    def test_sell_with_mild_rally_gets_no_hedge_instruction(self):
        fd = _financial_data(current_price=400.0, trailing_1y_return_pct=10.0)
        prompt = _build(
            self._SELL_METHODS,
            current_price=400.0,
            ticker="XYZ",
            extra_context={"data_collection": fd},
        )
        assert "AUTHORITATIVE RECOMMENDATION (do not deviate): SELL" in prompt
        assert "MOMENTUM DIVERGENCE" not in prompt
