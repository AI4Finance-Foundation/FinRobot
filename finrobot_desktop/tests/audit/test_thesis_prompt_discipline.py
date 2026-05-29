"""Thesis prompt numeric discipline audit.

Red-line guards:
1. The "严格数字纪律" whitelist block is present in every thesis prompt.
2. The company_overview segment-fabrication guard is present in every thesis prompt.
3. Specific fake AAPL training-data numbers (e.g. "$3.5T market cap", "P/E 30x",
   "products 80%" fabricated split) are NOT in the prompt when the whitelist
   contains no such values.
4. Whitelist injects only values traceable to the structured_context fields that
   were actually passed in — no phantom numbers.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from finrobot.engine.models.financial import (
    CompanyFinancials,
    DCFInputs,
    DCFResult,
    PeerComps,
    ValuationMethod,
    ValuationSynthesis,
)


# ---------------------------------------------------------------------------
# Helpers — build minimal structured_context that mimics pipeline output
# ---------------------------------------------------------------------------

_DCF_INPUTS = DCFInputs(
    revenue_base=385_000_000_000,
    revenue_growth_rates=[0.07, 0.07, 0.06, 0.06, 0.05],
    ebitda_margin=0.33,
    capex_pct_revenue=0.03,
    nwc_pct_revenue=0.01,
    da_pct_revenue=0.04,
    tax_rate=0.16,
    risk_free_rate=0.045,
    beta=1.22,
    equity_risk_premium=0.055,
    cost_of_debt=0.035,
    debt_ratio=0.20,
    terminal_growth_rate=0.025,
    shares_outstanding=15_500_000_000,
    net_debt=60_000_000_000,
)

_DCF_RESULT = DCFResult(
    cost_of_equity=0.112,
    wacc=0.0993,
    projection_years=5,
    projected_revenue=[411e9, 439e9, 465e9, 493e9, 518e9],
    projected_ebitda=[135e9, 144e9, 153e9, 162e9, 171e9],
    projected_fcf=[40e9, 42e9, 45e9, 47e9, 49e9],
    terminal_value=900e9,
    pv_terminal=560e9,
    pv_fcf_total=190e9,
    enterprise_value=750e9,
    equity_value=690e9,
    implied_price=174.23,
    inputs=_DCF_INPUTS,
)

_PEER_AAPL = CompanyFinancials(
    ticker="MSFT",
    name="Microsoft",
    revenue=211_000_000_000,
    ebitda=95_000_000_000,
    net_income=72_000_000_000,
    market_cap=3_100_000_000_000,
    total_debt=60_000_000_000,
    total_cash=80_000_000_000,
    gross_margin=0.69,
    operating_margin=0.44,
    pe_ratio=35.2,
    ev_ebitda=21.4,
)

_PEER_COMPS = PeerComps(
    target=CompanyFinancials(
        ticker="AAPL",
        name="Apple Inc.",
        revenue=385_000_000_000,
        ebitda=130_000_000_000,
        net_income=95_000_000_000,
        market_cap=2_500_000_000_000,
        total_debt=120_000_000_000,
        total_cash=60_000_000_000,
        gross_margin=0.43,
        operating_margin=0.30,
        pe_ratio=28.7,
        ev_ebitda=19.1,
    ),
    peers=[_PEER_AAPL],
    median_ev_ebitda=21.4,
    median_pe=35.2,
    median_ev_revenue=10.1,
)

_VALUATION_SYNTHESIS = ValuationSynthesis(
    methods=[
        ValuationMethod(
            name="DCF", low=160.0, mid=174.23, high=195.0, confidence=0.55, source="finrobot"
        ),
        ValuationMethod(
            name="EV/EBITDA Comps",
            low=168.0,
            mid=181.0,
            high=198.0,
            confidence=0.45,
            source="finrobot",
        ),
    ],
    weighted_price=177.12,
    current_price=172.50,
    upside_downside=0.027,
)


def _make_structured_context(**overrides: Any) -> dict[str, object]:
    ctx: dict[str, object] = {
        "financial_modeling": _DCF_RESULT,
        "peer_analysis": _PEER_COMPS,
        "valuation_synthesis": _VALUATION_SYNTHESIS,
        "xbrl_facts_snapshot": {},
    }
    ctx.update(overrides)
    return ctx


# ---------------------------------------------------------------------------
# Extract the thesis_prompt as built inside _execute_thesis — without running
# the LLM. We do this by patching Agent to capture the prompt.
# ---------------------------------------------------------------------------


async def _capture_thesis_prompt(structured_context: dict[str, object]) -> str:
    """Run _execute_thesis up to the Agent.run call and capture the full prompt."""
    from finrobot.engine.pipelines.equity_research import _execute_thesis

    captured_prompt: list[str] = []

    class _CapturingAgent:
        """Stub that records the prompt instead of calling the LLM."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def run(self, prompt: str, **kwargs: Any) -> Any:
            captured_prompt.append(prompt)
            # Return a minimal ThesisResult to avoid validation errors.
            from finrobot.engine.models.financial import ThesisResult

            thesis = ThesisResult(
                recommendation="BUY",
                price_target=177.12,
                price_target_basis="weighted synthesis",
                narrative="test narrative",
                catalysts=["catalyst one"],
                risks=["risk one"],
                tagline="Test tagline",
                key_takeaways=["takeaway one"],
                company_overview="Company overview text.",
                valuation_overview="Valuation overview text.",
                competitor_analysis="Competitor analysis text.",
                news_summary="News summary text.",
            )

            result = MagicMock()
            result.output = thesis
            return result

    fake_deps = MagicMock()
    fake_deps.settings.create_model.return_value = MagicMock()
    fake_skill = MagicMock()
    fake_skill.return_value = None
    fake_deps.skill_runtime = None

    import finrobot.engine.pipelines.equity_research as _mod

    original_agent = _mod.Agent

    _mod.Agent = _CapturingAgent  # type: ignore[assignment]
    try:
        await _execute_thesis(
            agent=MagicMock(),
            deps=fake_deps,
            prompt="Step: thesis\n\nData:\nAAPL analysis.",
            structured_context=structured_context,
            ticker="AAPL",
        )
    finally:
        _mod.Agent = original_agent  # type: ignore[assignment]

    assert captured_prompt, "Agent.run was never called — test setup error"
    return captured_prompt[0]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_whitelist_block_present_in_prompt() -> None:
    """'严格数字纪律' discipline block must appear in every thesis prompt."""
    ctx = _make_structured_context()
    prompt = await _capture_thesis_prompt(ctx)
    assert "严格数字纪律" in prompt, (
        "Whitelist discipline block missing from thesis prompt. "
        "Any narrative number that can't be traced to the whitelist fields is a hallucination."
    )


@pytest.mark.asyncio
async def test_segment_fabrication_guard_present() -> None:
    """Segment fabrication guard must be injected when xbrl has no segment data."""
    ctx = _make_structured_context(xbrl_facts_snapshot={})
    prompt = await _capture_thesis_prompt(ctx)
    assert "SEC XBRL 当前不提供按分部或地理区域拆分" in prompt, (
        "Company-overview segment fabrication guard missing from prompt. "
        "Without this guard the LLM invents segment splits like 'products 80%'."
    )


@pytest.mark.asyncio
async def test_whitelist_contains_actual_dcf_numbers() -> None:
    """Whitelist block must contain the DCF implied_price injected from DCFResult."""
    ctx = _make_structured_context()
    prompt = await _capture_thesis_prompt(ctx)
    # DCFResult.implied_price = 174.23
    assert "174.23" in prompt, (
        "DCF implied_price (174.23) must appear in the whitelist section so the "
        "LLM can legitimately cite it."
    )


@pytest.mark.asyncio
async def test_whitelist_contains_peer_medians() -> None:
    """Whitelist must include peer median multiples from the actual PeerComps."""
    ctx = _make_structured_context()
    prompt = await _capture_thesis_prompt(ctx)
    # median_ev_ebitda = 21.4 from _PEER_COMPS
    assert "21.4" in prompt, (
        "Peer median EV/EBITDA (21.4) missing from whitelist. "
        "The LLM would be forbidden from citing any peer multiple at all."
    )


@pytest.mark.asyncio
async def test_whitelist_contains_valuation_synthesis_weighted_price() -> None:
    """Whitelist must expose weighted_price so LLM can cite it in valuation_overview."""
    ctx = _make_structured_context()
    prompt = await _capture_thesis_prompt(ctx)
    # weighted_price = 177.12
    assert "177.12" in prompt, (
        "ValuationSynthesis.weighted_price (177.12) not in whitelist. "
        "LLM cannot reference the synthesis price without this."
    )


@pytest.mark.asyncio
async def test_data_health_gate_withholds_weighted_price_from_whitelist() -> None:
    """When the data-health gate trips (reliable=False) the withheld weighted_price
    must NOT be whitelisted — otherwise the LLM narrative fields (valuation_overview
    etc.) can "legally" quote the very target the gate exists to suppress. This is
    the 2026-05-28 TSLA leak: structured price_target is force-nulled post-run, but
    free prose can still print "$12.71" if the number is in the citable set.
    """
    gated = ValuationSynthesis(
        methods=[
            ValuationMethod(
                name="DCF", low=4.0, mid=5.88, high=7.0, confidence=0.85, source="finrobot"
            ),
            ValuationMethod(
                name="EV/EBITDA Comps",
                low=17.0,
                mid=19.54,
                high=22.0,
                confidence=0.72,
                source="finrobot",
            ),
        ],
        weighted_price=12.71,
        current_price=11.25,
        upside_downside=0.13,
        outlier_methods=["DCF", "EV/EBITDA Comps"],
        warnings=["DCF deviates 54% from median; methods do not corroborate"],
        reliable=False,
    )
    ctx = _make_structured_context(valuation_synthesis=gated)
    prompt = await _capture_thesis_prompt(ctx)

    discipline_section = prompt[prompt.find("严格数字纪律") :]
    # The withheld headline target must NOT be a citable number.
    assert "12.71" not in discipline_section, (
        "Data-health gate tripped but weighted_price 12.71 is still whitelisted — "
        "the narrative can leak the withheld target (TSLA 2026-05-28 regression)."
    )
    # Per-method mids stay citable — "DCF says $5.88, comps say $19.54, they disagree"
    # is exactly the honest narrative the gate wants.
    assert "5.88" in discipline_section
    assert "19.54" in discipline_section
    # The gate must explicitly forbid valuation_overview from stating a target.
    assert "DATA-HEALTH GATE TRIPPED" in prompt
    assert "valuation_overview" in prompt


@pytest.mark.asyncio
async def test_no_phantom_training_numbers_when_absent_from_context() -> None:
    """The whitelist block must not inject numbers that aren't in structured_context.

    Specifically: if neither the DCF nor comps contain a P/E of ~30x for AAPL,
    the string '30x' must not appear in the whitelist bullet points. We cannot
    stop the LLM from hallucinating at inference time, but we ensure the prompt
    does not license hallucinations by pre-loading training-data values.
    """
    ctx = _make_structured_context()
    prompt = await _capture_thesis_prompt(ctx)

    # The whitelist section is everything after the "严格数字纪律" marker.
    discipline_start = prompt.find("严格数字纪律")
    assert discipline_start != -1
    discipline_section = prompt[discipline_start:]

    # "$3.5 trillion" — classic AAPL training-data hallucination, not in our fixture.
    assert "3.5 trillion" not in discipline_section.lower()
    assert "3.5t" not in discipline_section.lower()

    # "P/E 30x" — AAPL 2024 consensus P/E from training data; not in our fixture
    # (our fixture has pe_ratio=28.7 for AAPL and 35.2 for MSFT, not 30x).
    assert "30x" not in discipline_section


@pytest.mark.asyncio
async def test_empty_structured_context_still_produces_discipline_block() -> None:
    """Even with no valuation/peer/dcf data the discipline block is still injected."""
    ctx: dict[str, object] = {}
    prompt = await _capture_thesis_prompt(ctx)
    assert "严格数字纪律" in prompt
    assert "SEC XBRL 当前不提供按分部或地理区域拆分" in prompt


@pytest.mark.asyncio
async def test_wacc_from_dcf_result_not_inputs() -> None:
    """wacc in whitelist must come from DCFResult.wacc (0.0993), not DCFInputs."""
    ctx = _make_structured_context()
    prompt = await _capture_thesis_prompt(ctx)
    # DCFResult.wacc = 0.0993; DCFInputs has no .wacc field so this also guards
    # against an AttributeError regression.
    assert "0.0993" in prompt, (
        "DCFResult.wacc (0.0993) must appear in the whitelist. "
        "If this fails, the whitelist may be pulling from DCFInputs (which has no wacc field) "
        "or has silently swallowed an AttributeError."
    )
