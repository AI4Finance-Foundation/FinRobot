"""CLI tests using click.testing.CliRunner with TestModel mock."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner
from pydantic_ai.models.test import TestModel

from finrobot.cli import cli
from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.types import DataType
from finrobot.engine.deps import FinRobotDeps

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "skills"


# ---------------------------------------------------------------------------
# Fake DataLayer for CLI tests
# ---------------------------------------------------------------------------


class FakeDataLayer:
    async def fetch(self, data_type: str, ticker: str, **kwargs) -> DataResult:
        try:
            dtype = DataType(data_type)
        except ValueError:
            # PydanticAI TestModel can emit placeholder tool args; legacy CLI
            # smoke tests expect the fake layer to keep returning financials.
            dtype = DataType.FINANCIALS
        if dtype == DataType.PRICE:
            data = {
                "current_price": 150.0,
                "price_history": [{"close": 150.0}],
            }
        elif dtype == DataType.PEER_CANDIDATES:
            data = {
                "profile": {
                    "symbol": ticker,
                    "company_name": f"{ticker} Inc.",
                    "sector": "Technology",
                    "industry": "Consumer Electronics",
                    "market_cap": 2_500_000_000_000,
                    "description": "Designs and sells consumer technology hardware and services.",
                },
                "industry_screen": ["MSFT", "GOOGL", "AMZN"],
                "stock_peers": ["MSFT", "GOOGL", "AMZN"],
                "sector_screen": ["MSFT", "GOOGL", "AMZN", "META"],
                "quotes": {
                    "MSFT": {"market_cap": 3_000_000_000_000, "pe": 35.0},
                    "GOOGL": {"market_cap": 2_100_000_000_000, "pe": 28.0},
                    "AMZN": {"market_cap": 1_900_000_000_000, "pe": 45.0},
                    "META": {"market_cap": 1_600_000_000_000, "pe": 24.0},
                },
                "profiles": {
                    "MSFT": {
                        "company_name": "Microsoft Corporation",
                        "sector": "Technology",
                        "industry": "Software - Infrastructure",
                        "description": "Develops software, cloud infrastructure, and productivity platforms.",
                    },
                    "GOOGL": {
                        "company_name": "Alphabet Inc.",
                        "sector": "Communication Services",
                        "industry": "Internet Content & Information",
                        "description": "Provides search, advertising, cloud, and consumer internet services.",
                    },
                    "AMZN": {
                        "company_name": "Amazon.com, Inc.",
                        "sector": "Consumer Cyclical",
                        "industry": "Internet Retail",
                        "description": "Operates online retail, marketplace, cloud, and subscription businesses.",
                    },
                    "META": {
                        "company_name": "Meta Platforms, Inc.",
                        "sector": "Communication Services",
                        "industry": "Internet Content & Information",
                        "description": "Operates social platforms and digital advertising services.",
                    },
                },
            }
        elif dtype == DataType.XBRL_FACTS:
            data = {}
        else:
            data = {
                "revenue": 385_000_000_000,
                "ebitda": 130_000_000_000,
                "net_income": 95_000_000_000,
                "market_cap": 2_500_000_000_000,
                "shares_outstanding": 15_500_000_000,
                "current_price": 150.0,
                "gross_margin": 0.43,
                "operating_margin": 0.30,
                "total_debt": 120_000_000_000,
                "total_cash": 60_000_000_000,
                "price_history": [{"close": 150.0}],
            }
        return DataResult(
            data=data,
            provider="fake",
            ticker=ticker,
            data_type=data_type,
            timestamp=datetime.now(tz=timezone.utc),
        )

    async def fetch_canonical(self, data_type, ticker, **kwargs):
        """Return NormalizedFinancials / NormalizedPrice (ADR-0006 canonical contract)."""
        from finrobot.engine.data.interface import ProviderError
        from finrobot.engine.data.normalize.financials import normalize_financials
        from finrobot.engine.data.normalize.price import normalize_price
        from finrobot.engine.data.types import DataType

        dtype = DataType(data_type)
        if dtype not in (DataType.PRICE, DataType.FINANCIALS):
            # FORWARD_ESTIMATES etc. (638a8164 canonical gate, unwrapped via
            # .payload()): refuse honestly so callers take their tolerated
            # "unavailable" branch instead of crashing on the wrong contract.
            raise ProviderError(f"no canonical fake for {dtype}")
        raw = await self.fetch(str(data_type), ticker, **kwargs)
        if dtype == DataType.PRICE:
            return normalize_price(raw)
        return normalize_financials(raw)

    async def fetch_historical(self, data_type: str, ticker: str, years: int = 5, **kwargs):
        return []


def _fake_deps():
    """Create fake deps for testing."""
    from finrobot.config import get_settings

    settings = get_settings(model_name="test")
    return FinRobotDeps(data_layer=FakeDataLayer(), settings=settings)


def _patch_build_runtime(monkeypatch, call_tools=None):
    """Patch _build_runtime to return a TestModel agent + fake deps."""
    from finrobot.config import get_settings
    from finrobot.engine.orchestrator import create_lead_agent

    settings = get_settings(model_name="test")
    agent = create_lead_agent(settings)
    fake_deps = FinRobotDeps(data_layer=FakeDataLayer(), settings=settings)

    # Override the agent model to TestModel
    test_model = TestModel(
        custom_output_text="revenue 385B ebitda 130B price_history available",
        call_tools=call_tools or [],
    )

    def mock_build_runtime(model=None):
        return agent, fake_deps

    monkeypatch.setattr("finrobot.cli._build_runtime", mock_build_runtime)
    return agent, test_model


def _patch_build_deps(monkeypatch):
    """Patch _build_deps for pipeline commands (research, comps, dcf)."""
    fake_deps = _fake_deps()

    def mock_build_deps(model=None):
        return fake_deps

    monkeypatch.setattr("finrobot.cli._build_deps", mock_build_deps)
    # Sub-agents built from these settings must not actually CALL tools:
    # query_financial_data raises ModelRetry on a bad data_type so a real
    # model can self-correct (b9b26d24), but TestModel keeps re-sending the
    # schema placeholder ("a") and burns max_retries — failing the critical
    # data step. These are CLI smoke tests ("doesn't crash"), not tool tests.
    monkeypatch.setattr(
        type(fake_deps.settings),
        "create_model",
        lambda self: TestModel(
            custom_output_text="revenue 385B ebitda 130B test analysis output",
            call_tools=[],
        ),
    )
    return fake_deps


class TestRunCommand:
    def test_run_doesnt_crash_with_test_model(self, monkeypatch):
        agent, test_model = _patch_build_runtime(monkeypatch)
        runner = CliRunner()
        with agent.override(model=test_model):
            result = runner.invoke(cli, ["run", "What is AAPL's PE?"])
        assert result.exit_code == 0, result.output

    def test_run_with_model_option(self, monkeypatch):
        agent, test_model = _patch_build_runtime(monkeypatch)
        runner = CliRunner()
        with agent.override(model=test_model):
            result = runner.invoke(
                cli, ["run", "test question", "--model", "anthropic:claude-sonnet-4-6"]
            )
        assert result.exit_code == 0, result.output


class TestResearchCommand:
    def test_research_doesnt_crash_with_test_model(self, monkeypatch):
        _patch_build_deps(monkeypatch)
        from finrobot.engine.pipelines.base import PipelineResult

        async def mock_execute(self, deps, ticker, **kwargs):
            return PipelineResult(
                steps={
                    "data_collection": "revenue 385B ebitda 130B",
                    "peer_analysis": "MSFT GOOG AMZN peers identified",
                    "financial_modeling": "DCF implies $200/share",
                    "thesis": "Buy recommendation price target $220",
                    "report": "# Report\n\n## Summary\n\nAAPL analysis.\n\n## Valuation\n\nFair value $200.\n\n## Risk\n\nDownside risks.\n\nThis is a test report with enough words to pass the 200-word minimum. "
                    * 5,
                },
            )

        monkeypatch.setattr(
            "finrobot.engine.pipelines.base.Pipeline.execute",
            mock_execute,
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["research", "AAPL"])
        assert result.exit_code == 0, result.output


class TestCompsCommand:
    def test_comps_doesnt_crash_with_test_model(self, monkeypatch):
        _patch_build_deps(monkeypatch)
        runner = CliRunner()
        result = runner.invoke(cli, ["comps", "AAPL"])
        assert result.exit_code == 0, result.output

    def test_comps_with_model_option(self, monkeypatch):
        _patch_build_deps(monkeypatch)
        runner = CliRunner()
        result = runner.invoke(cli, ["comps", "AAPL", "--model", "test"])
        assert result.exit_code == 0, result.output

    def test_comps_peers_too_few_rejected_at_entry(self, monkeypatch):
        """BUG-047: <3 peers fails fast with a clean ClickException, NOT a bare
        traceback ~30s into the pipeline. The pipeline must never run."""

        def _explode(*args, **kwargs):
            raise AssertionError("pipeline must not run for an invalid --peers")

        monkeypatch.setattr("finrobot.engine.pipelines.base.Pipeline.execute", _explode)
        _patch_build_deps(monkeypatch)
        runner = CliRunner()
        result = runner.invoke(cli, ["comps", "AAPL", "--peers", "MSFT,GOOGL"])
        assert result.exit_code != 0
        assert "--peers needs 3-10 tickers, got 2" in result.output

    def test_comps_peers_too_many_rejected_at_entry(self, monkeypatch):
        def _explode(*args, **kwargs):
            raise AssertionError("pipeline must not run for an invalid --peers")

        monkeypatch.setattr("finrobot.engine.pipelines.base.Pipeline.execute", _explode)
        _patch_build_deps(monkeypatch)
        runner = CliRunner()
        eleven = ",".join(f"PEER{i}" for i in range(11))
        result = runner.invoke(cli, ["comps", "AAPL", "--peers", eleven])
        assert result.exit_code != 0
        assert "got 11" in result.output

    def test_comps_peers_bad_format_rejected_at_entry(self, monkeypatch):
        """Junk like CJK / punctuation is caught by the shared validate_ticker
        at the CLI entry before reaching any provider."""

        def _explode(*args, **kwargs):
            raise AssertionError("pipeline must not run for an invalid --peers")

        monkeypatch.setattr("finrobot.engine.pipelines.base.Pipeline.execute", _explode)
        _patch_build_deps(monkeypatch)
        runner = CliRunner()
        result = runner.invoke(cli, ["comps", "AAPL", "--peers", "MSFT,苹果,!!!"])
        assert result.exit_code != 0
        assert "Invalid ticker" in result.output

    def test_comps_valid_peers_pass(self, monkeypatch):
        """A valid 3-peer set passes the entry check and reaches the pipeline,
        which receives the normalised (upper-cased) tickers."""
        captured: dict[str, object] = {}
        from finrobot.engine.pipelines.base import PipelineResult

        async def mock_execute(self, deps, ticker, **kwargs):
            captured["peers"] = kwargs.get("peers")
            return PipelineResult(steps={"data_collection": "ok"})

        monkeypatch.setattr("finrobot.engine.pipelines.base.Pipeline.execute", mock_execute)
        _patch_build_deps(monkeypatch)
        runner = CliRunner()
        result = runner.invoke(cli, ["comps", "AAPL", "--peers", "msft, googl ,amzn"])
        assert result.exit_code == 0, result.output
        assert captured["peers"] == ["MSFT", "GOOGL", "AMZN"]


class TestDcfCommand:
    def test_dcf_doesnt_crash_with_test_model(self, monkeypatch):
        _patch_build_deps(monkeypatch)
        from finrobot.engine.pipelines.base import PipelineResult

        async def mock_execute(self, deps, ticker, **kwargs):
            return PipelineResult(
                steps={
                    "historical_data": "revenue 385B ebitda 130B",
                    "dcf_calc": "DCF implies $200/share. WACC: 10.0%. EV: $2.5B. Sensitivity: $180-$220.",
                    "output_gen": "DCF output: wacc terminal value free cash flow sensitivity implied price",
                },
            )

        monkeypatch.setattr(
            "finrobot.engine.pipelines.base.Pipeline.execute",
            mock_execute,
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["dcf", "AAPL"])
        assert result.exit_code == 0, result.output

    def test_dcf_with_model_option(self, monkeypatch):
        _patch_build_deps(monkeypatch)
        from finrobot.engine.pipelines.base import PipelineResult

        async def mock_execute(self, deps, ticker, **kwargs):
            return PipelineResult(
                steps={
                    "historical_data": "revenue 385B ebitda 130B",
                    "dcf_calc": "DCF implies $200/share. WACC: 10.0%. EV: $2.5B. Sensitivity: $180-$220.",
                    "output_gen": "DCF output: wacc terminal value free cash flow sensitivity implied price",
                },
            )

        monkeypatch.setattr(
            "finrobot.engine.pipelines.base.Pipeline.execute",
            mock_execute,
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["dcf", "AAPL", "--model", "test"])
        assert result.exit_code == 0, result.output

    def test_should_use_ddm_is_async(self):
        """BUG-082: the bank probe MUST be a coroutine so it can be awaited
        inside the same asyncio.run as the pipeline. A sync helper that wraps
        its own asyncio.run is what bound a shared aiosqlite connection to a
        throwaway loop and hung the interpreter at shutdown."""
        import inspect

        from finrobot.cli import _should_use_ddm

        assert inspect.iscoroutinefunction(_should_use_ddm)

    def test_dcf_default_path_uses_single_event_loop(self):
        """BUG-082 regression: a DataCache (shared aiosqlite connection) opened
        in one asyncio.run and reused in a SECOND asyncio.run binds its worker
        thread to the destroyed first loop → the interpreter hangs forever
        joining the orphan thread at shutdown. The dcf fix folds bank detection
        and the pipeline run into ONE loop. We prove the single-loop shape (the
        fix) exits cleanly in a subprocess under a hard timeout."""
        import subprocess
        import sys
        import textwrap

        single_loop = textwrap.dedent(
            """
            import asyncio, tempfile, os
            from datetime import datetime, timezone
            from finrobot.engine.data.cache import DataCache
            from finrobot.engine.data.interface import DataResult

            db = os.path.join(tempfile.mkdtemp(), "c.db")
            cache = DataCache(db_path=db)

            def _r(t):
                return DataResult(data={"x": 1}, provider="p", ticker=t,
                                  data_type="financials",
                                  timestamp=datetime.now(tz=timezone.utc))

            async def main():
                # bank probe + pipeline-equivalent: every cache op on ONE loop
                await cache.set("financials", "AAPL", _r("AAPL"))
                await cache.get("financials", "AAPL")
                await cache.set("financials", "AAPL", _r("AAPL"))
                await cache.close()

            asyncio.run(main())
            """
        )
        proc = subprocess.run(
            [sys.executable, "-c", single_loop],
            capture_output=True,
            text=True,
            timeout=60,  # the bug hangs 3+ min; 60s is a generous non-hang bound
        )
        assert proc.returncode == 0, (
            f"single-loop dcf shape must exit cleanly, "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )


class TestBuildDeps:
    def test_build_deps_returns_deps_with_settings(self):
        from finrobot.cli import _build_deps

        # Use the "test" provider — config is app-stored only, so the default
        # (deepseek) provider would fail-fast on a missing key here.
        deps = _build_deps(model="test")
        assert hasattr(deps, "settings")
        assert hasattr(deps, "data_layer")
        assert hasattr(deps, "skill_runtime")

    def test_build_runtime_returns_agent_and_deps(self):
        from finrobot.cli import _build_runtime

        agent, deps = _build_runtime(model="test")
        assert agent is not None
        assert hasattr(deps, "settings")


class TestSkillCommands:
    def test_skill_list_prints_skills(self, monkeypatch):
        monkeypatch.setenv("FINROBOT_SKILLS_DIR", str(FIXTURES_DIR))
        runner = CliRunner()
        result = runner.invoke(cli, ["skill", "list"])
        assert result.exit_code == 0, result.output
        assert "comps-analysis" in result.output

    def test_skill_search_finds_comps(self, monkeypatch):
        monkeypatch.setenv("FINROBOT_SKILLS_DIR", str(FIXTURES_DIR))
        runner = CliRunner()
        result = runner.invoke(cli, ["skill", "search", "comps"])
        assert result.exit_code == 0, result.output
        assert "comps-analysis" in result.output

    def test_skill_search_no_match(self, monkeypatch):
        monkeypatch.setenv("FINROBOT_SKILLS_DIR", str(FIXTURES_DIR))
        runner = CliRunner()
        result = runner.invoke(cli, ["skill", "search", "zzz_nonexistent"])
        assert result.exit_code == 0
        assert "No skills matching" in result.output

    def test_skill_list_no_skills_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FINROBOT_SKILLS_DIR", str(tmp_path / "nonexistent"))
        runner = CliRunner()
        result = runner.invoke(cli, ["skill", "list"])
        assert "No skills directory" in result.output


class TestCliProgress:
    @pytest.mark.asyncio
    async def test_cli_progress_retry_reprints_step_label(self, capsys):
        """I3: after retry, step label must be reprinted so 'done' has context."""
        from finrobot.cli import CliProgress

        progress = CliProgress()
        await progress.on_step_start(1, 3, "data_collection")
        await progress.on_step_retry(1, "data_collection", 1, "timeout")
        await progress.on_step_end(1, 3, "data_collection", 2.5)
        output = capsys.readouterr().out
        lines = output.strip().split("\n")
        # Last line should contain both the step label and "done"
        assert "Data Collection" in lines[-1] and "done" in lines[-1], (
            f"Expected step label before 'done' on last line, got: {lines[-1]}"
        )


class TestBacktestCommand:
    def test_backtest_basic(self, monkeypatch):
        from finrobot.engine.backtest.engine import BacktestResult

        async def mock_run(self, config):
            return BacktestResult(
                initial_value=100_000,
                final_value=110_000,
                total_return=0.10,
                sharpe_ratio=1.2,
                max_drawdown=-0.05,
                total_trades=10,
                winning_trades=6,
                losing_trades=4,
            )

        monkeypatch.setattr(
            "finrobot.engine.backtest.backtrader_adapter.BackTraderAdapter.run",
            mock_run,
        )
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "backtest",
                "AAPL",
                "--start",
                "2023-01-01",
                "--end",
                "2024-01-01",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "$110,000" in result.output
        assert "10.00%" in result.output

    def test_backtest_with_params(self, monkeypatch):
        from finrobot.engine.backtest.engine import BacktestResult

        captured_configs = []

        async def mock_run(self, config):
            captured_configs.append(config)
            return BacktestResult(
                initial_value=100_000,
                final_value=100_000,
                total_return=0.0,
            )

        monkeypatch.setattr(
            "finrobot.engine.backtest.backtrader_adapter.BackTraderAdapter.run",
            mock_run,
        )
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "backtest",
                "MSFT",
                "--start",
                "2023-01-01",
                "--end",
                "2024-01-01",
                "--strategy",
                "sma_crossover",
                "--params",
                '{"fast": 5, "slow": 20}',
                "--cash",
                "200000",
            ],
        )
        assert result.exit_code == 0, result.output
        assert captured_configs[0].strategy_params == {"fast": 5, "slow": 20}
        assert captured_configs[0].initial_cash == 200_000.0

    def test_backtest_invalid_params_json(self):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "backtest",
                "AAPL",
                "--start",
                "2023-01-01",
                "--end",
                "2024-01-01",
                "--params",
                "not-json",
            ],
        )
        assert result.exit_code != 0
        assert "Invalid --params JSON" in result.output


class TestAskCommand:
    def test_ask_basic(self, monkeypatch):
        _patch_build_deps(monkeypatch)

        async def mock_run_qa(data_layer, settings, ticker, question, top_k=5):
            return f"Based on [Item 1A], {ticker} faces regulatory risks."

        monkeypatch.setattr(
            "finrobot.engine.analysis.qa.run_qa",
            mock_run_qa,
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["ask", "AAPL", "What are the risk factors?"])
        assert result.exit_code == 0, result.output
        assert "regulatory risks" in result.output

    def test_ask_with_top_k(self, monkeypatch):
        _patch_build_deps(monkeypatch)

        captured_top_k = []

        async def mock_run_qa(data_layer, settings, ticker, question, top_k=5):
            captured_top_k.append(top_k)
            return "Answer"

        monkeypatch.setattr(
            "finrobot.engine.analysis.qa.run_qa",
            mock_run_qa,
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["ask", "AAPL", "question", "--top-k", "10"])
        assert result.exit_code == 0, result.output
        assert captured_top_k == [10]


class TestAnalyzeCommand:
    def test_analyze_income(self, monkeypatch):
        _patch_build_deps(monkeypatch)

        async def mock_run_analysis(data_layer, settings, ticker, analysis_type):
            return f"## Income Analysis for {ticker}\n\nRevenue is $385B."

        monkeypatch.setattr(
            "finrobot.engine.analysis.prompts.run_analysis",
            mock_run_analysis,
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["analyze", "AAPL", "income"])
        assert result.exit_code == 0, result.output
        assert "Income Analysis" in result.output
        assert "AAPL" in result.output

    def test_analyze_all_types_accepted(self, monkeypatch):
        _patch_build_deps(monkeypatch)

        async def mock_run_analysis(data_layer, settings, ticker, analysis_type):
            return f"Analysis: {analysis_type}"

        monkeypatch.setattr(
            "finrobot.engine.analysis.prompts.run_analysis",
            mock_run_analysis,
        )
        runner = CliRunner()
        for atype in ("income", "balance", "cashflow", "risk", "competitors", "overview"):
            result = runner.invoke(cli, ["analyze", "AAPL", atype])
            assert result.exit_code == 0, f"{atype} failed: {result.output}"

    def test_analyze_invalid_type_rejected(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["analyze", "AAPL", "invalid"])
        assert result.exit_code != 0
        assert "Invalid value" in result.output or "invalid" in result.output.lower()


class TestServeCommand:
    def test_serve_doesnt_crash_on_import(self):
        """Just verify the serve command can be parsed without import errors."""
        runner = CliRunner()
        # Invoke with --help to avoid actually starting uvicorn
        result = runner.invoke(cli, ["serve", "--help"])
        assert result.exit_code == 0
        assert "port" in result.output.lower()
        assert "--parent-pid" in result.output


class TestParentDeathWatchdog:
    """The desktop sidecar must self-terminate when the Tauri shell is gone."""

    def test_watchdog_starts_daemon_thread_for_live_parent(self) -> None:
        import os
        import threading

        from finrobot.cli import _start_parent_death_watchdog

        # Watch our own (always-alive) pid: the watchdog must start but never
        # fire os._exit, so the test process survives.
        stop = _start_parent_death_watchdog(os.getpid())
        try:
            watchers = [t for t in threading.enumerate() if t.name == "parent-death-watchdog"]
            assert watchers, "watchdog thread was not started"
            assert watchers[0].daemon, "watchdog must be a daemon thread"
        finally:
            stop.set()  # stop the poll loop so the daemon thread can't leak into later tests

    def test_watchdog_exits_when_parent_gone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import os
        import subprocess
        import threading

        from finrobot.cli import _start_parent_death_watchdog

        # A reaped subprocess gives a pid that is reliably dead.
        dead = subprocess.Popen(["true"])
        dead.wait()

        fired = threading.Event()
        # Capture the hard-exit instead of actually killing the test runner.
        # NB: the real os._exit never returns, but this mock does — so the
        # watch loop keeps spinning. We MUST stop it (finally below) or it
        # fires the *restored* real os._exit on its next tick and hard-kills
        # the whole pytest session at some random later test (BUG-050).
        monkeypatch.setattr(os, "_exit", lambda code: fired.set())

        stop = _start_parent_death_watchdog(dead.pid)
        try:
            # Poll interval is 2s; allow a margin.
            assert fired.wait(timeout=6), "watchdog did not exit when parent pid was dead"
        finally:
            stop.set()
