"""CLI tests using click.testing.CliRunner with TestModel mock."""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from pydantic_ai.models.test import TestModel

from finagent.cli import cli
from finagent.engine.data.interface import DataResult


# ---------------------------------------------------------------------------
# Fake DataLayer for CLI tests
# ---------------------------------------------------------------------------

class FakeDataLayer:
    async def fetch(self, data_type: str, ticker: str, **kwargs) -> DataResult:
        return DataResult(
            data={"revenue": 385_000_000_000, "ebitda": 130_000_000_000,
                  "price_history": [{"close": 150.0}]},
            provider="fake",
            ticker=ticker,
            data_type=data_type,
            timestamp=datetime.now(tz=timezone.utc),
        )


def _patch_deps(monkeypatch):
    """Patch _build_deps to return fake deps with TestModel override."""
    from finagent.engine.data.cache import DataCache
    from finagent.engine.data.layer import DataLayer
    from finagent.engine.deps import FinAgentDeps

    class FakeDeps(FinAgentDeps):
        pass

    fake_deps = FinAgentDeps(data_layer=FakeDataLayer())
    monkeypatch.setattr("finagent.cli._build_deps", lambda model_name: fake_deps)
    return fake_deps


class TestRunCommand:
    def test_run_doesnt_crash_with_test_model(self, monkeypatch):
        _patch_deps(monkeypatch)
        from finagent.engine.orchestrator import lead_agent

        runner = CliRunner()
        with lead_agent.override(model=TestModel(custom_output_text="AAPL PE is 28.3x", call_tools=[])):
            result = runner.invoke(cli, ["run", "What is AAPL's PE?"])
        assert result.exit_code == 0, result.output
        assert "AAPL PE is 28.3x" in result.output

    def test_run_with_model_option(self, monkeypatch):
        _patch_deps(monkeypatch)
        from finagent.engine.orchestrator import lead_agent

        runner = CliRunner()
        with lead_agent.override(model=TestModel(custom_output_text="answer", call_tools=[])):
            result = runner.invoke(cli, ["run", "test question", "--model", "anthropic:claude-sonnet-4-6"])
        assert result.exit_code == 0, result.output


class TestResearchCommand:
    def test_research_doesnt_crash_with_test_model(self, monkeypatch):
        _patch_deps(monkeypatch)
        from finagent.engine.orchestrator import lead_agent

        runner = CliRunner()
        with lead_agent.override(model=TestModel(
            custom_output_text="revenue 385B ebitda 130B price_history available",
            call_tools=[],
        )):
            result = runner.invoke(cli, ["research", "AAPL"])
        assert result.exit_code == 0, result.output
        assert "Step" in result.output or "report" in result.output.lower()


class TestServeCommand:
    def test_serve_doesnt_crash_on_import(self):
        """Just verify the serve command can be parsed without import errors."""
        runner = CliRunner()
        # Invoke with --help to avoid actually starting uvicorn
        result = runner.invoke(cli, ["serve", "--help"])
        assert result.exit_code == 0
        assert "port" in result.output.lower()
