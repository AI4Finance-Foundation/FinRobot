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
from finrobot.engine.data.cache import DataCache
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.compute.compare import ComparisonResult
from finrobot.engine.pipelines.base import PipelineResult

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from finrobot.engine.backtest.engine import BacktestConfig, BacktestResult
    from finrobot.engine.pipelines.base import ProgressCallback


class FinRobot:
    """High-level entry point for FinRobot pipelines.

    Args:
        model: Model name override (e.g. ``"anthropic:claude-sonnet-4-6"``).
            Falls back to ``FINROBOT_MODEL_NAME`` / config default when None.
        **kwargs: Forwarded to :class:`FinRobotSettings` constructor, letting
            callers override any setting (API keys, cache path, etc.).
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

        from finrobot.engine.agents.factory import create_sub_agents
        from finrobot.engine.data.providers.edgar_provider import (
            EdgarToolsProvider,
            _is_valid_identity,
        )
        from finrobot.engine.data.providers.yfinance_provider import YFinanceProvider
        from finrobot.engine.skills.registry import SkillRegistry

        providers: list[Any] = []
        if self._settings.fmp_api_key:
            from finrobot.engine.data.providers.fmp_provider import FMPProvider

            providers.append(FMPProvider(api_key=self._settings.fmp_api_key))
        if self._settings.finnhub_api_key:
            from finrobot.engine.data.providers.finnhub_provider import FinnhubProvider

            providers.append(FinnhubProvider(api_key=self._settings.finnhub_api_key))
        providers.append(YFinanceProvider())
        # SEC EDGAR — conditional on valid identity (same contract as
        # build_data_layer). SDK callers without a valid identity get a
        # DataLayer without SEC; downstream LLM-touching paths must
        # tolerate that (degrade rather than crash).
        if _is_valid_identity(getattr(self._settings, "sec_user_agent", "")):
            providers.append(EdgarToolsProvider(user_agent=self._settings.sec_user_agent))

        if self._settings.adanos_api_key:
            from finrobot.engine.data.providers.adanos_provider import AdanosProvider

            providers.append(AdanosProvider(api_key=self._settings.adanos_api_key))

        skills_path = Path(self._settings.skills_dir)
        registry = SkillRegistry(skills_path) if skills_path.exists() else None

        cache = DataCache(self._settings.cache_db_path)
        data_layer = DataLayer(providers=providers, cache=cache)
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

    def compare(
        self,
        tickers: list[str],
        progress: "ProgressCallback | None" = None,
    ) -> ComparisonResult:
        """Compare DCF valuation across multiple companies. Blocking.

        Runs the DCF pipeline concurrently for each ticker, then returns a
        side-by-side ComparisonResult. Use :meth:`acompare` in async contexts.

        Args:
            tickers: List of ticker symbols (2-10).
            progress: Optional progress callback (applied to each pipeline).
        """
        result: ComparisonResult = self._run_sync(lambda: self.acompare(tickers, progress=progress))
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
        from finrobot.engine.pipelines.equity_research import (
            create_equity_research_pipeline,
        )

        pipeline = create_equity_research_pipeline(self._get_sub_agents())
        return await pipeline.execute(self._ensure_deps(), ticker, progress=progress)

    async def adcf(self, ticker: str, progress: "ProgressCallback | None" = None) -> PipelineResult:
        from finrobot.engine.pipelines.dcf import create_dcf_pipeline

        pipeline = create_dcf_pipeline(self._get_sub_agents())
        return await pipeline.execute(self._ensure_deps(), ticker, progress=progress)

    async def acomps(
        self, ticker: str, progress: "ProgressCallback | None" = None
    ) -> PipelineResult:
        from finrobot.engine.pipelines.comps import create_comps_pipeline

        pipeline = create_comps_pipeline(self._get_sub_agents())
        return await pipeline.execute(self._ensure_deps(), ticker, progress=progress)

    async def albo(self, ticker: str, progress: "ProgressCallback | None" = None) -> PipelineResult:
        from finrobot.engine.pipelines.lbo import create_lbo_pipeline

        pipeline = create_lbo_pipeline(self._get_sub_agents())
        return await pipeline.execute(self._ensure_deps(), ticker, progress=progress)

    async def aearnings(
        self, ticker: str, progress: "ProgressCallback | None" = None
    ) -> PipelineResult:
        from finrobot.engine.pipelines.earnings_analysis import (
            create_earnings_analysis_pipeline,
        )

        pipeline = create_earnings_analysis_pipeline(self._get_sub_agents())
        return await pipeline.execute(self._ensure_deps(), ticker, progress=progress)

    async def aic_memo(
        self, ticker: str, progress: "ProgressCallback | None" = None
    ) -> PipelineResult:
        from finrobot.engine.pipelines.ic_memo import create_ic_memo_pipeline

        pipeline = create_ic_memo_pipeline(self._get_sub_agents())
        return await pipeline.execute(self._ensure_deps(), ticker, progress=progress)

    async def acompare(
        self,
        tickers: list[str],
        progress: "ProgressCallback | None" = None,
    ) -> ComparisonResult:
        """Compare DCF valuation across multiple companies. Async.

        Runs the DCF pipeline concurrently for each ticker, then returns a
        side-by-side ComparisonResult.

        Args:
            tickers: List of ticker symbols (2-10).
            progress: Optional progress callback (applied to each pipeline).
        """
        from finrobot.engine.compute.compare import (
            CompanyValuation,
            build_company_valuation,
        )
        from finrobot.engine.models.financial import DCFResult, FinancialData
        from finrobot.engine.pipelines.dcf import create_dcf_pipeline

        deps = self._ensure_deps()
        sub_agents = self._get_sub_agents()

        async def _run_one(ticker: str) -> CompanyValuation:
            try:
                pipeline = create_dcf_pipeline(sub_agents)
                result = await pipeline.execute(deps, ticker, progress=progress)

                dcf_result: DCFResult | None = None
                for value in result.structured_data.values():
                    if isinstance(value, DCFResult):
                        dcf_result = value
                        break

                if dcf_result is None:
                    return CompanyValuation(
                        ticker=ticker,
                        error="DCF pipeline completed but no DCFResult found",
                    )

                company_name = ""
                current_price: float | None = None
                ev_ebitda: float | None = None
                pe_ratio: float | None = None
                warnings: list[str] = []

                for value in result.structured_data.values():
                    if isinstance(value, FinancialData):
                        company_name = value.company_name
                        current_price = value.market.current_price
                        ev_ebitda = value.valuation.ev_ebitda
                        pe_ratio = value.market.pe_ratio
                        warnings = list(value.warnings)
                        break

                return build_company_valuation(
                    ticker=ticker,
                    company_name=company_name,
                    current_price=current_price,
                    dcf_result=dcf_result,
                    ev_ebitda=ev_ebitda,
                    pe_ratio=pe_ratio,
                    warnings=warnings,
                )
            except (ValueError, RuntimeError, KeyError, TypeError) as e:
                return CompanyValuation(ticker=ticker, error=str(e)[:200])

        tasks = [_run_one(t.upper()) for t in tickers]
        companies = await asyncio.gather(*tasks)
        return ComparisonResult(companies=list(companies))

    async def aanalyze(self, ticker: str, analysis_type: str) -> str:
        """Run standalone financial analysis. Async.

        analysis_type: income | balance | cashflow | risk | competitors | overview
        """
        from finrobot.engine.analysis.prompts import run_analysis

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

        deps = self._ensure_deps()
        return await run_qa(deps.data_layer, deps.settings, ticker, question)

    async def abacktest(self, config: "BacktestConfig") -> "BacktestResult":
        """Run a backtest. Async.

        Requires ``pip install 'finrobot[backtest]'``.
        """
        from finrobot.engine.backtest.backtrader_adapter import BackTraderAdapter

        engine = BackTraderAdapter()
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
        """
        from finrobot.engine.backtest.strategy_agent import run_strategy_selection

        return await run_strategy_selection(
            self._settings,
            ticker,
            start_date,
            end_date,
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
