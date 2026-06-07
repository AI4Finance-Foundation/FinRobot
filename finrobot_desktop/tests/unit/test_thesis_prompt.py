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
