"""FinRobot Python SDK — programmatic access to all pipelines.

What this code does that raw LLM cannot: type-safe public API with IDE
auto-completion and resource lifecycle management. Hides the seven-layer
initialisation (settings → providers → cache → data layer → deps →
sub-agents → pipeline) behind one class.

Usage::

    from finrobot import FinRobot

    # Sync (scripts, CLI):
    agent = FinRobot()
    result = agent.research("AAPL")
    print(result.format_summary())

    # Async (Jupyter, FastAPI, async code):
    async with FinRobot() as agent:
        result = await agent.aresearch("AAPL")

    # Manual cleanup (if not using a context manager):
    import asyncio
    agent = FinRobot()
    try:
        result = agent.research("AAPL")
    finally:
        asyncio.run(agent.close())
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from finrobot.config import get_settings
from finrobot.engine.data.ticker import validate_ticker
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.pipelines.base import PipelineResult

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from finrobot.engine.backtest.engine import BacktestConfig, BacktestResult
    from finrobot.engine.pipelines.base import ProgressCallback


class FinRobot:
    """High-level entry point for FinRobot pipelines.

    Args:
        model: Model name override (e.g. ``"anthropic:claude-sonnet-4-6"``).
            Falls back to the config default when None.
        **kwargs: Forwarded to :func:`get_settings`. Pass LLM provider API keys
            as ``provider_keys={"deepseek": "sk-…"}`` (keyed by provider id);
            data-source keys (``fmp_api_key`` …) and any other setting override
            go through as-is.
    """

    def __init__(self, model: str | None = None, **kwargs: Any) -> None:
        overrides: dict[str, Any] = {}
        if model:
            overrides["model_name"] = model
        overrides.update(kwargs)
        self._settings = get_settings(**overrides)
        # Fail fast on bad model config (P3 audit D2). ValueError bubbles
        # out of __init__ so the SDK user sees the error immediately
        # instead of waiting for the first LLM call to surface it.
        self._settings.validate_runtime_config()
        self._deps: FinRobotDeps | None = None
        self._sub_agents: dict[str, Agent] | None = None
        # Persistent loop for sync calls — see ``_run_sync``.
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------ #
    # Context manager                                                    #
    # ------------------------------------------------------------------ #

    async def __aenter__(self) -> "FinRobot":
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any
    ) -> None:
        await self.close()

    # ------------------------------------------------------------------ #
    # Resource management                                                #
    # ------------------------------------------------------------------ #

    def _ensure_deps(self) -> FinRobotDeps:
        """Lazily build deps + sub-agents on the first pipeline call."""
        if self._deps is not None:
            return self._deps

        from pathlib import Path

        from finrobot.engine.data.factory import build_data_layer
        from finrobot.engine.agents.factory import create_sub_agents
        from finrobot.engine.skills.registry import SkillRegistry

        skills_path = Path(self._settings.skills_dir)
        registry = SkillRegistry(skills_path) if skills_path.exists() else None

        # Single source of truth for provider assembly — reuse the canonical
        # build_data_layer (same as the server) instead of hand-rolling a
        # divergent chain. This keeps SDK/CLI callers in lock-step with the
        # server: FMP/Finnhub/yfinance/EDGAR(conditional)/Adanos plus the
        # always-on NewsAggregator (yfinance news, free, no key). Any future
        # provider added there flows here automatically — no second drift.
        data_layer = build_data_layer(self._settings)
        self._deps = FinRobotDeps(
            data_layer=data_layer,
            settings=self._settings,
            skill_runtime=registry,
        )
        self._sub_agents = create_sub_agents(self._settings, skill_registry=registry)
        return self._deps

    def _get_sub_agents(self) -> dict[str, Agent]:
        self._ensure_deps()
        assert self._sub_agents is not None  # set by _ensure_deps
        return self._sub_agents

    async def _run_pipeline(
        self, key: str, ticker: str, progress: "ProgressCallback | None"
    ) -> PipelineResult:
        """Build the pipeline registered under ``key`` and execute it.

        Shared body for every ``a*()`` method — looks the factory up in the
        pipeline registry (the single source of truth) so adding a pipeline no
        longer means adding a hand-written SDK method with its own inline
        ``create_*_pipeline`` import.

        ``ticker`` goes through the shared :func:`validate_ticker` choke point
        first — the SDK is a pipeline entry just like CLI / /api/runs / chat
        tools, and an unvalidated symbol would mint a junk cache key and be
        re-fanned to providers forever (raises ``ValueError`` on junk).
        """
        from finrobot.engine.pipelines.base import Pipeline
        from finrobot.engine.pipelines.registry import get_pipeline_factories

        ticker = validate_ticker(ticker)
        pipeline: Pipeline = get_pipeline_factories()[key](self._get_sub_agents())
        return await pipeline.execute(self._ensure_deps(), ticker, progress=progress)

    # ------------------------------------------------------------------ #
    # Sync API                                                           #
    # ------------------------------------------------------------------ #

    def _run_sync(self, coro_fn: Any) -> Any:
        """Run an async coroutine factory synchronously.

        ``coro_fn`` must be a **callable** that returns a coroutine (typically
        a ``lambda``). The indirection means we do NOT create a coroutine
        object when raising RuntimeError in Jupyter/FastAPI contexts — no
        "coroutine was never awaited" warning.

        Why a persistent loop instead of ``asyncio.run``? ``asyncio.run``
        creates a fresh loop every call, but DataCache holds an aiosqlite
        connection bound to the first loop. Re-using a single loop avoids
        "attached to a different loop" errors across repeated sync calls.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No running loop — good, we can proceed.
            pass
        else:
            raise RuntimeError(
                "FinRobot sync methods (research, dcf, etc.) cannot be "
                "called from an async context (Jupyter notebook, FastAPI "
                "handler, etc.). Use the async API instead: "
                "`await agent.aresearch('AAPL')`."
            )

        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        return self._loop.run_until_complete(coro_fn())

    def research(self, ticker: str, progress: "ProgressCallback | None" = None) -> PipelineResult:
        """Run equity research pipeline. Blocking.

        Use :meth:`aresearch` in async contexts (Jupyter, FastAPI, etc.).
        """
        result: PipelineResult = self._run_sync(lambda: self.aresearch(ticker, progress=progress))
        return result

    def dcf(self, ticker: str, progress: "ProgressCallback | None" = None) -> PipelineResult:
        result: PipelineResult = self._run_sync(lambda: self.adcf(ticker, progress=progress))
        return result

    def comps(self, ticker: str, progress: "ProgressCallback | None" = None) -> PipelineResult:
        result: PipelineResult = self._run_sync(lambda: self.acomps(ticker, progress=progress))
        return result

    def lbo(self, ticker: str, progress: "ProgressCallback | None" = None) -> PipelineResult:
        result: PipelineResult = self._run_sync(lambda: self.albo(ticker, progress=progress))
        return result

    def earnings(self, ticker: str, progress: "ProgressCallback | None" = None) -> PipelineResult:
        result: PipelineResult = self._run_sync(lambda: self.aearnings(ticker, progress=progress))
        return result

    def ic_memo(self, ticker: str, progress: "ProgressCallback | None" = None) -> PipelineResult:
        result: PipelineResult = self._run_sync(lambda: self.aic_memo(ticker, progress=progress))
        return result

    def analyze(self, ticker: str, analysis_type: str) -> str:
        """Run standalone financial analysis. Blocking.

        analysis_type: income | balance | cashflow | risk | competitors | overview
        """
        result: str = self._run_sync(lambda: self.aanalyze(ticker, analysis_type))
        return result

    def ask(self, ticker: str, question: str) -> str:
        """Ask a question about a company's 10-K filing using RAG. Blocking."""
        result: str = self._run_sync(lambda: self.aask(ticker, question))
        return result

    def backtest(self, config: "BacktestConfig") -> "BacktestResult":
        """Run a backtest. Blocking.

        Requires ``pip install 'finrobot[backtest]'``.
        """
        result: BacktestResult = self._run_sync(lambda: self.abacktest(config))
        return result

    def auto_backtest(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        initial_cash: float = 100_000.0,
    ) -> "BacktestResult":
        """LLM-guided strategy selection with iterative tuning. Blocking.

        The LLM picks an initial strategy/params, runs the backtest, reviews
        results, and iterates up to 3 times to improve performance.
        """
        result: BacktestResult = self._run_sync(
            lambda: self.aauto_backtest(ticker, start_date, end_date, initial_cash)
        )
        return result

    # ------------------------------------------------------------------ #
    # Async API                                                          #
    # ------------------------------------------------------------------ #

    async def aresearch(
        self, ticker: str, progress: "ProgressCallback | None" = None
    ) -> PipelineResult:
        return await self._run_pipeline("research", ticker, progress)

    async def adcf(self, ticker: str, progress: "ProgressCallback | None" = None) -> PipelineResult:
        return await self._run_pipeline("dcf", ticker, progress)

    async def acomps(
        self, ticker: str, progress: "ProgressCallback | None" = None
    ) -> PipelineResult:
        return await self._run_pipeline("comps", ticker, progress)

    async def albo(self, ticker: str, progress: "ProgressCallback | None" = None) -> PipelineResult:
        return await self._run_pipeline("lbo", ticker, progress)

    async def aearnings(
        self, ticker: str, progress: "ProgressCallback | None" = None
    ) -> PipelineResult:
        return await self._run_pipeline("earnings", ticker, progress)

    async def aic_memo(
        self, ticker: str, progress: "ProgressCallback | None" = None
    ) -> PipelineResult:
        return await self._run_pipeline("ic-memo", ticker, progress)

    async def aanalyze(self, ticker: str, analysis_type: str) -> str:
        """Run standalone financial analysis. Async.

        analysis_type: income | balance | cashflow | risk | competitors | overview
        """
        from finrobot.engine.analysis.prompts import run_analysis

        ticker = validate_ticker(ticker)
        deps = self._ensure_deps()
        return await run_analysis(
            deps.data_layer,
            deps.settings,
            ticker,
            analysis_type,
        )

    async def aask(self, ticker: str, question: str) -> str:
        """Ask a question about a company's 10-K filing using RAG. Async."""
        from finrobot.engine.analysis.qa import run_qa

        ticker = validate_ticker(ticker)
        deps = self._ensure_deps()
        return await run_qa(deps.data_layer, deps.settings, ticker, question)

    async def abacktest(self, config: "BacktestConfig") -> "BacktestResult":
        """Run a backtest. Async.

        Requires ``pip install 'finrobot[backtest]'``.
        """
        from finrobot.engine.backtest.backtrader_adapter import BackTraderAdapter

        engine = BackTraderAdapter(self._ensure_deps().data_layer)
        return await engine.run(config)

    async def aauto_backtest(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        initial_cash: float = 100_000.0,
    ) -> "BacktestResult":
        """LLM-guided strategy selection with iterative tuning. Async.

        Requires ``pip install 'finrobot[backtest]'``.

        (``abacktest`` needs no explicit call here — ``BacktestConfig`` runs
        the same ``validate_ticker`` in its pydantic field validator.)
        """
        from finrobot.engine.backtest.strategy_agent import run_strategy_selection

        ticker = validate_ticker(ticker)
        return await run_strategy_selection(
            self._settings,
            ticker,
            start_date,
            end_date,
            self._ensure_deps().data_layer,
            initial_cash=initial_cash,
        )

    async def close(self) -> None:
        """Close the data cache connection and persistent sync loop.

        Safe to call multiple times. ``DataLayer.close`` delegates to
        ``DataCache.close`` which is itself idempotent.
        """
        if self._deps is not None:
            await self._deps.data_layer.close()
        # I6: yield once so any pending callbacks (e.g. aiosqlite worker
        # thread posting via call_soon_threadsafe) are processed before
        # we close the loop.  Without this, loop.close() can race with
        # still-queued callbacks → RuntimeError("Event loop is closed").
        await asyncio.sleep(0)
        if self._loop is not None and not self._loop.is_closed():
            self._loop.close()
            self._loop = None
