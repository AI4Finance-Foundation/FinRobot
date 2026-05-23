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

from finagent.config import get_settings
from finagent.engine.agents.factory import create_sub_agents
from finagent.engine.data.cache import DataCache
from finagent.engine.data.layer import DataLayer
from finagent.engine.data.providers.yfinance_provider import YFinanceProvider
from finagent.engine.deps import FinAgentDeps
from finagent.engine.orchestrator import create_lead_agent
from finagent.engine.pipelines.equity_research import create_equity_research_pipeline


def _build_runtime():
    settings = get_settings()
    deps = FinAgentDeps(
        data_layer=DataLayer(
            providers=[YFinanceProvider()], cache=DataCache(settings.cache_db_path)
        ),
        settings=settings,
    )
    agent = create_lead_agent(settings)
    return agent, deps


@pytest.mark.integration
@pytest.mark.slow
async def test_mode_a_quick_query():
    """P0 acceptance: finagent run 'What is AAPL's PE ratio?'
    Must return real data in < 10 seconds."""
    agent, deps = _build_runtime()
    start = time.time()
    result = await agent.run("What is AAPL's PE ratio?", deps=deps)
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
    agent, deps = _build_runtime()
    sub_agents = create_sub_agents(deps.settings)
    pipeline = create_equity_research_pipeline(sub_agents)

    start = time.time()
    result = await pipeline.execute(deps, "AAPL")
    elapsed = time.time() - start

    summary = result.format_summary()

    assert elapsed < 60, f"Too slow: {elapsed:.1f}s (limit: 60s)"
    assert set(result.steps.keys()) == {
        "data_collection",
        "catalyst_analysis",
        "peer_analysis",
        "financial_modeling",
        "technical_analysis",
        "thesis",
        "report",
    }, "Not all 7 steps ran"
    assert len(summary) > 200, "Report too short"

    # Check for real financial data markers (not hallucinated)
    lower = summary.lower()
    assert any(kw in lower for kw in ["revenue", "ebitda", "margin"]), "No financial data in report"
    assert any(
        kw in lower for kw in ["peer", "comparable", "msft", "googl", "meta"]
    ), "No peer analysis in report"
    assert any(
        kw in lower for kw in ["valuation", "dcf", "multiple", "price target"]
    ), "No valuation in report"

    print(f"\nMode B report ({elapsed:.1f}s):\n{summary[:2000]}...")
