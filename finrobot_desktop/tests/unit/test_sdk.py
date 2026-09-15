"""Tests for finrobot.sdk.FinRobot (Track 2 Tasks 5-7).

Covers:
- Lazy deps construction
- Model override at __init__ time
- Sync methods in async context raise a clear RuntimeError (no coro leak)
- aresearch() returns a PipelineResult when driven by TestModel + mock deps
- Context manager closes the data layer on __aexit__
- close() is safe to call twice

Every test injects a mock DataLayer so we never touch the network or disk.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from finrobot import FinRobot, PipelineResult
from finrobot.engine.data.interface import DataResult
from finrobot.engine.pipelines.base import Pipeline, PipelineStep
from finrobot.engine.pipelines.validators import validate_is_non_empty


def _fake_result() -> DataResult:
    return DataResult(
        data={
            "revenue": 1e9,
            "ebitda": 2e8,
            "net_income": 1e8,
            "market_cap": 5e9,
            "shares_outstanding": 1e8,
            "current_price": 50.0,
            "gross_margin": 0.4,
            "operating_margin": 0.15,
            "price_history": [{"close": 50.0}],
        },
        provider="test",
        ticker="TEST",
        data_type="financials",
        timestamp=datetime.now(tz=timezone.utc),
    )


def _inject_mock_deps(agent: FinRobot):
    """Replace agent's deps/sub_agents so no real IO happens."""
    from finrobot.engine.agents.factory import create_sub_agents
    from finrobot.engine.deps import FinRobotDeps

    mock_layer = MagicMock()
    mock_layer.fetch = AsyncMock(return_value=_fake_result())
    mock_layer.close = AsyncMock()

    agent._deps = FinRobotDeps(
        data_layer=mock_layer,
        settings=agent._settings,
        skill_runtime=None,
    )
    agent._sub_agents = create_sub_agents(agent._settings)
    return mock_layer


def _trivial_pipeline(*args, **kwargs) -> Pipeline:
    """Replacement factory that returns a 1-step pipeline that always succeeds.

    Used to monkey-patch create_equity_research_pipeline in SDK tests so we
    exercise SDK plumbing without running DCF math against TestModel output.
    """

    async def fn(agent, deps, prompt, structured_context, ticker):
        return f"trivial result for {ticker}"

    from finrobot.engine.pipelines.base import TextValidator

    step = PipelineStep(
        name="trivial",
        agent=MagicMock(),
        validator=TextValidator(validate_is_non_empty),
        executor=fn,
    )
    return Pipeline(steps=[step])


def test_init_with_model_override():
    agent = FinRobot(model="test")
    assert agent._settings.model_name == "test"


def test_init_bad_provider_fails_fast():
    """P3 audit D2: SDK must fail fast on bad model config instead of
    waiting for the first LLM call to blow up 60 seconds later."""
    with pytest.raises(ValueError, match="Unknown provider"):
        FinRobot(model="bogus:model-x")


def test_init_missing_api_key_fails_fast():
    """Missing API key should raise during __init__, not at first call."""
    with pytest.raises(ValueError, match="No API key configured for provider 'anthropic'"):
        FinRobot(model="anthropic:claude-sonnet-4-6", provider_keys={"anthropic": ""})


def test_init_empty_default_model_fails_fast():
    # The default model_name is now EMPTY (first-run onboarding state) — the SDK
    # exists to run analysis, so __init__ must fail fast with an actionable
    # message rather than defer the crash to the first LLM call. A key alone is
    # not enough; the caller must pick a model explicitly.
    with pytest.raises(ValueError, match="No AI model configured"):
        FinRobot(provider_keys={"openai": "sk-test"})


def test_init_explicit_model_is_honoured():
    agent = FinRobot(model="anthropic:claude-sonnet-4-6", provider_keys={"anthropic": "sk-test"})
    assert agent._settings.model_name == "anthropic:claude-sonnet-4-6"


def test_lazy_deps_not_built_on_init():
    """__init__ must not construct providers or cache."""
    agent = FinRobot(model="test")
    assert agent._deps is None
    assert agent._sub_agents is None


async def test_sync_method_in_async_context_raises():
    """Sync methods must detect an already-running loop and raise a clear
    error instead of crashing or silently creating orphaned coroutines."""
    agent = FinRobot(model="test")
    with pytest.raises(RuntimeError, match="async context"):
        agent.research("TEST")


def _patch_research_factory(monkeypatch) -> None:
    """Make the SDK's registry lookup return the trivial pipeline factory.

    BUG-025: the SDK's a*() methods now resolve the factory through
    ``registry.get_pipeline_factories()`` (the single source of truth) instead
    of importing ``create_equity_research_pipeline`` directly, so the seam these
    plumbing tests stub is the registry, not the pipeline module.
    """
    import finrobot.engine.pipelines.registry as reg

    monkeypatch.setattr(reg, "get_pipeline_factories", lambda: {"research": _trivial_pipeline})


async def test_aresearch_returns_pipeline_result(monkeypatch):
    """SDK plumbing test — stub the pipeline factory so we exercise
    dep injection + return type, not equity_research's DCF math."""
    _patch_research_factory(monkeypatch)

    agent = FinRobot(model="test")
    _inject_mock_deps(agent)

    result = await agent.aresearch("TEST")
    assert isinstance(result, PipelineResult)
    assert "trivial" in result.steps
    assert "TEST" in result.steps["trivial"]


async def test_context_manager_closes_data_layer(monkeypatch):
    _patch_research_factory(monkeypatch)

    async with FinRobot(model="test") as agent:
        mock_layer = _inject_mock_deps(agent)
        result = await agent.aresearch("TEST")
        assert isinstance(result, PipelineResult)
    # After __aexit__, close() must have been awaited on the data layer.
    mock_layer.close.assert_awaited()


async def test_close_safe_without_deps():
    """close() is a no-op if the agent never built deps."""
    agent = FinRobot(model="test")
    await agent.close()  # must not raise


async def test_close_safe_called_twice(monkeypatch):
    _patch_research_factory(monkeypatch)

    agent = FinRobot(model="test")
    mock_layer = _inject_mock_deps(agent)
    _ = await agent.aresearch("TEST")
    await agent.close()
    # Second call must not raise — DataLayer.close is idempotent.
    await agent.close()
    # DataLayer.close() was called at least once through the agent
    mock_layer.close.assert_awaited()


async def test_aanalyze_returns_string(monkeypatch):
    """SDK analyze method returns LLM analysis text."""
    import finrobot.engine.analysis.prompts as ap

    async def mock_run_analysis(data_layer, settings, ticker, analysis_type):
        return f"## {analysis_type.title()} Analysis for {ticker}"

    monkeypatch.setattr(ap, "run_analysis", mock_run_analysis)

    agent = FinRobot(model="test")
    _inject_mock_deps(agent)

    result = await agent.aanalyze("AAPL", "income")
    assert isinstance(result, str)
    assert "Income Analysis" in result
    assert "AAPL" in result


async def test_aask_returns_string(monkeypatch):
    """SDK ask method returns RAG-based answer text."""
    import finrobot.engine.analysis.qa as qa

    async def mock_run_qa(data_layer, settings, ticker, question, top_k=5):
        return f"Based on [Item 1A], {ticker} faces regulatory risks."

    monkeypatch.setattr(qa, "run_qa", mock_run_qa)

    agent = FinRobot(model="test")
    _inject_mock_deps(agent)

    result = await agent.aask("AAPL", "What are the risk factors?")
    assert isinstance(result, str)
    assert "regulatory risks" in result
    assert "AAPL" in result


async def test_abacktest_returns_result(monkeypatch):
    """SDK backtest method returns BacktestResult."""
    from finrobot.engine.backtest.engine import BacktestConfig, BacktestResult
    import finrobot.engine.backtest.backtrader_adapter as bta

    async def mock_run(self, config):
        return BacktestResult(
            initial_value=100_000,
            final_value=115_000,
            total_return=0.15,
            sharpe_ratio=1.3,
            total_trades=10,
            winning_trades=7,
            losing_trades=3,
        )

    monkeypatch.setattr(bta.BackTraderAdapter, "run", mock_run)

    agent = FinRobot(model="test")
    _inject_mock_deps(agent)

    config = BacktestConfig(
        ticker="AAPL",
        start_date="2023-01-01",
        end_date="2024-01-01",
    )
    result = await agent.abacktest(config)
    assert isinstance(result, BacktestResult)
    assert result.total_return == pytest.approx(0.15)
    assert result.winning_trades == 7


async def test_aanalyze_all_types(monkeypatch):
    """All 6 analysis types work through the SDK."""
    import finrobot.engine.analysis.prompts as ap

    async def mock_run_analysis(data_layer, settings, ticker, analysis_type):
        return f"Result: {analysis_type}"

    monkeypatch.setattr(ap, "run_analysis", mock_run_analysis)

    agent = FinRobot(model="test")
    _inject_mock_deps(agent)

    for atype in ("income", "balance", "cashflow", "risk", "competitors", "overview"):
        result = await agent.aanalyze("TEST", atype)
        assert atype in result


def test_ensure_deps_reuses_build_data_layer(monkeypatch):
    """BUG-035: SDK must assemble providers via the canonical build_data_layer
    (single source of truth), not a hand-rolled divergent chain. We assert it
    calls build_data_layer with self._settings and adopts its DataLayer.
    """
    import finrobot.sdk as sdk_mod

    sentinel_layer = MagicMock()
    captured: dict = {}

    def fake_build(settings):
        captured["settings"] = settings
        return sentinel_layer

    monkeypatch.setattr(sdk_mod, "build_data_layer", fake_build, raising=False)
    # build_data_layer is imported inside _ensure_deps; patch the source module
    # too so the deferred import resolves to our fake.
    import finrobot.engine.data.factory as dlf

    monkeypatch.setattr(dlf, "build_data_layer", fake_build)

    agent = FinRobot(model="test")
    deps = agent._ensure_deps()

    assert captured["settings"] is agent._settings
    assert deps.data_layer is sentinel_layer


def test_ensure_deps_provider_chain_includes_news_aggregator():
    """BUG-035: the real provider chain built by the SDK must contain a
    NewsAggregatorProvider (yfinance news, free/no-key, always-on) so SDK callers
    get the same DataType.NEWS coverage as the server — no silent drift.
    """
    from finrobot.engine.data.providers.news_aggregator import NewsAggregatorProvider

    agent = FinRobot(model="test")
    try:
        deps = agent._ensure_deps()
        providers = deps.data_layer._providers
        assert any(isinstance(p, NewsAggregatorProvider) for p in providers), (
            "SDK provider chain is missing NewsAggregatorProvider — drifted from build_data_layer"
        )
    finally:
        import asyncio

        asyncio.run(agent.close())


async def test_close_does_not_emit_event_loop_closed_warning():
    """I6: close() must flush pending callbacks before closing the loop.

    Without ``await asyncio.sleep(0)`` before ``loop.close()``, the
    aiosqlite worker thread may still have pending ``call_soon_threadsafe``
    callbacks that hit RuntimeError('Event loop is closed').
    """
    import asyncio
    import warnings

    agent = FinRobot(model="test")
    # Simulate the persistent sync loop that _run_sync creates.
    agent._loop = asyncio.new_event_loop()

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        await agent.close()
    assert agent._loop is None


# ---------------------------------------------------------------------------
# Ticker validation choke point (P2 audit 2026-06-10): the SDK is a pipeline
# entry like CLI / /api/runs / chat tools — junk symbols must be rejected
# BEFORE they mint a cache key and get re-fanned to providers forever.
# ---------------------------------------------------------------------------


async def test_sdk_rejects_junk_ticker_before_pipeline(monkeypatch):
    _patch_research_factory(monkeypatch)
    agent = FinRobot(model="test")
    _inject_mock_deps(agent)

    for junk in ("苹果", "AAPL;DROP", "", "A" * 13, "AAPL OK"):
        with pytest.raises(ValueError, match="Invalid ticker"):
            await agent.aresearch(junk)
    with pytest.raises(ValueError, match="Invalid ticker"):
        await agent.aanalyze("苹果", "income")
    with pytest.raises(ValueError, match="Invalid ticker"):
        await agent.aask("AAPL;DROP", "risks?")


async def test_sdk_normalises_ticker_case(monkeypatch):
    """Lower-case input reaches the pipeline upper-cased — one cache key per
    symbol, matching every other entry point."""
    _patch_research_factory(monkeypatch)
    agent = FinRobot(model="test")
    _inject_mock_deps(agent)

    result = await agent.aresearch("  test ")
    assert "TEST" in result.steps["trivial"]
