"""CLI tests using click.testing.CliRunner with TestModel mock."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner
from pydantic_ai.models.test import TestModel

from finagent.cli import cli
from finagent.engine.data.interface import DataResult
from finagent.engine.deps import FinAgentDeps

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "skills"


# ---------------------------------------------------------------------------
# Fake DataLayer for CLI tests
# ---------------------------------------------------------------------------


class FakeDataLayer:
    async def fetch(self, data_type: str, ticker: str, **kwargs) -> DataResult:
        if data_type == "price":
            data = {
                "current_price": 150.0,
                "price_history": [{"close": 150.0}],
            }
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


def _fake_deps():
    """Create fake deps for testing."""
    from finagent.config import get_settings

    settings = get_settings(model_name="test")
    return FinAgentDeps(data_layer=FakeDataLayer(), settings=settings)


def _patch_build_runtime(monkeypatch, call_tools=None):
    """Patch _build_runtime to return a TestModel agent + fake deps."""
    from finagent.config import get_settings
    from finagent.engine.orchestrator import create_lead_agent

    settings = get_settings(model_name="test")
    agent = create_lead_agent(settings)
    fake_deps = FinAgentDeps(data_layer=FakeDataLayer(), settings=settings)

    # Override the agent model to TestModel
    test_model = TestModel(
        custom_output_text="revenue 385B ebitda 130B price_history available",
        call_tools=call_tools or [],
    )

    def mock_build_runtime(model=None):
        return agent, fake_deps

    monkeypatch.setattr("finagent.cli._build_runtime", mock_build_runtime)
    return agent, test_model


def _patch_build_deps(monkeypatch):
    """Patch _build_deps for pipeline commands (research, comps, dcf)."""
    fake_deps = _fake_deps()

    def mock_build_deps(model=None):
        return fake_deps

    monkeypatch.setattr("finagent.cli._build_deps", mock_build_deps)
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
        from finagent.engine.pipelines.base import PipelineResult

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
            "finagent.engine.pipelines.base.Pipeline.execute",
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


class TestDcfCommand:
    def test_dcf_doesnt_crash_with_test_model(self, monkeypatch):
        _patch_build_deps(monkeypatch)
        from finagent.engine.pipelines.base import PipelineResult

        async def mock_execute(self, deps, ticker, **kwargs):
            return PipelineResult(
                steps={
                    "historical_data": "revenue 385B ebitda 130B",
                    "dcf_calc": "DCF implies $200/share. WACC: 10.0%. EV: $2.5B. Sensitivity: $180-$220.",
                    "output_gen": "DCF output: wacc terminal value free cash flow sensitivity implied price",
                },
            )

        monkeypatch.setattr(
            "finagent.engine.pipelines.base.Pipeline.execute",
            mock_execute,
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["dcf", "AAPL"])
        assert result.exit_code == 0, result.output

    def test_dcf_with_model_option(self, monkeypatch):
        _patch_build_deps(monkeypatch)
        from finagent.engine.pipelines.base import PipelineResult

        async def mock_execute(self, deps, ticker, **kwargs):
            return PipelineResult(
                steps={
                    "historical_data": "revenue 385B ebitda 130B",
                    "dcf_calc": "DCF implies $200/share. WACC: 10.0%. EV: $2.5B. Sensitivity: $180-$220.",
                    "output_gen": "DCF output: wacc terminal value free cash flow sensitivity implied price",
                },
            )

        monkeypatch.setattr(
            "finagent.engine.pipelines.base.Pipeline.execute",
            mock_execute,
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["dcf", "AAPL", "--model", "test"])
        assert result.exit_code == 0, result.output


class TestBuildDeps:
    def test_build_deps_returns_deps_with_settings(self):
        from finagent.cli import _build_deps

        # This will try to build with real settings — just verify it returns FinAgentDeps
        deps = _build_deps()
        assert hasattr(deps, "settings")
        assert hasattr(deps, "data_layer")
        assert hasattr(deps, "skill_runtime")

    def test_build_runtime_returns_agent_and_deps(self):
        from finagent.cli import _build_runtime

        agent, deps = _build_runtime()
        assert agent is not None
        assert hasattr(deps, "settings")


class TestSkillCommands:
    def test_skill_list_prints_skills(self, monkeypatch):
        monkeypatch.setenv("FINAGENT_SKILLS_DIR", str(FIXTURES_DIR))
        runner = CliRunner()
        result = runner.invoke(cli, ["skill", "list"])
        assert result.exit_code == 0, result.output
        assert "comps-analysis" in result.output

    def test_skill_search_finds_comps(self, monkeypatch):
        monkeypatch.setenv("FINAGENT_SKILLS_DIR", str(FIXTURES_DIR))
        runner = CliRunner()
        result = runner.invoke(cli, ["skill", "search", "comps"])
        assert result.exit_code == 0, result.output
        assert "comps-analysis" in result.output

    def test_skill_search_no_match(self, monkeypatch):
        monkeypatch.setenv("FINAGENT_SKILLS_DIR", str(FIXTURES_DIR))
        runner = CliRunner()
        result = runner.invoke(cli, ["skill", "search", "zzz_nonexistent"])
        assert result.exit_code == 0
        assert "No skills matching" in result.output

    def test_skill_list_no_skills_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FINAGENT_SKILLS_DIR", str(tmp_path / "nonexistent"))
        runner = CliRunner()
        result = runner.invoke(cli, ["skill", "list"])
        assert "No skills directory" in result.output


class TestCliProgress:
    @pytest.mark.asyncio
    async def test_cli_progress_retry_reprints_step_label(self, capsys):
        """I3: after retry, step label must be reprinted so 'done' has context."""
        from finagent.cli import CliProgress

        progress = CliProgress()
        await progress.on_step_start(1, 3, "data_collection")
        await progress.on_step_retry(1, "data_collection", 1, "timeout")
        await progress.on_step_end(1, 3, "data_collection", 2.5)
        output = capsys.readouterr().out
        lines = output.strip().split("\n")
        # Last line should contain both the step label and "done"
        assert (
            "Data Collection" in lines[-1] and "done" in lines[-1]
        ), f"Expected step label before 'done' on last line, got: {lines[-1]}"


class TestBacktestCommand:
    def test_backtest_basic(self, monkeypatch):
        from finagent.engine.backtest.engine import BacktestResult

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
            "finagent.engine.backtest.backtrader_adapter.BackTraderAdapter.run",
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
        from finagent.engine.backtest.engine import BacktestResult

        captured_configs = []

        async def mock_run(self, config):
            captured_configs.append(config)
            return BacktestResult(
                initial_value=100_000,
                final_value=100_000,
                total_return=0.0,
            )

        monkeypatch.setattr(
            "finagent.engine.backtest.backtrader_adapter.BackTraderAdapter.run",
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
            "finagent.engine.analysis.qa.run_qa",
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
            "finagent.engine.analysis.qa.run_qa",
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
            "finagent.engine.analysis.prompts.run_analysis",
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
            "finagent.engine.analysis.prompts.run_analysis",
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
