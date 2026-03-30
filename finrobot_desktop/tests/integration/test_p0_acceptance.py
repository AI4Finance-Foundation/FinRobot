"""
P0 Acceptance Tests — Real API calls. Run manually only.

Usage:
    ANTHROPIC_API_KEY=sk-... pytest tests/integration/test_p0_acceptance.py -v -m "integration and slow"

These tests call real yfinance + real Claude API.
They are slow, cost money, and are NOT run in CI.
Both must pass before P0 is considered done.
"""
import time

import pytest

from finagent.engine.data.cache import DataCache
from finagent.engine.data.layer import DataLayer
from finagent.engine.data.providers.yfinance_provider import YFinanceProvider
from finagent.engine.deps import FinAgentDeps
from finagent.engine.orchestrator import lead_agent
from finagent.engine.pipelines.equity_research import create_equity_research_pipeline


def _build_deps() -> FinAgentDeps:
    return FinAgentDeps(
        data_layer=DataLayer(providers=[YFinanceProvider()], cache=DataCache()),
    )


@pytest.mark.integration
@pytest.mark.slow
async def test_mode_a_quick_query():
    """P0 acceptance: finagent run 'What is AAPL's PE ratio?'
    Must return real data in < 10 seconds."""
    deps = _build_deps()
    start = time.time()
    result = await lead_agent.run("What is AAPL's PE ratio?", deps=deps)
    elapsed = time.time() - start

    assert isinstance(result.output, str)
    assert len(result.output) > 10, "Response is too short — likely no real data"
    assert elapsed < 10, f"Too slow: {elapsed:.1f}s (limit: 10s)"
    print(f"\nMode A response ({elapsed:.1f}s):\n{result.output}")


@pytest.mark.integration
@pytest.mark.slow
async def test_mode_b_equity_research():
    """P0 acceptance: finagent research AAPL
    Must produce a Markdown report with real data in < 60 seconds,
    all 5 pipeline steps logged."""
    deps = _build_deps()
    pipeline = create_equity_research_pipeline(lead_agent)

    class Ctx:
        pass
    ctx = Ctx()
    ctx.deps = deps

    start = time.time()
    result = await pipeline.execute(ctx, "AAPL")
    elapsed = time.time() - start

    summary = result.format_summary()

    assert elapsed < 60, f"Too slow: {elapsed:.1f}s (limit: 60s)"
    assert set(result.steps.keys()) == {
        "data_collection", "peer_analysis", "financial_modeling", "thesis", "report"
    }, "Not all 5 steps ran"
    assert len(summary) > 200, "Report too short"

    # Check for real financial data markers (not hallucinated)
    lower = summary.lower()
    assert any(kw in lower for kw in ["revenue", "ebitda", "margin"]), \
        "No financial data in report"
    assert any(kw in lower for kw in ["peer", "comparable", "msft", "googl", "meta"]), \
        "No peer analysis in report"
    assert any(kw in lower for kw in ["valuation", "dcf", "multiple", "price target"]), \
        "No valuation in report"

    print(f"\nMode B report ({elapsed:.1f}s):\n{summary[:2000]}...")
