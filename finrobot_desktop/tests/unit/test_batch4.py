"""Tests for batch 4 code quality fixes.

Fix 4.6: ANALYSIS_TYPES derived from _PROMPTS
Fix 4.7: run_strategy_selection exposed in CLI/SDK

(Fix 4.3 task-eviction-cancellation and 4.4 circular-import tests removed
along with the legacy ``finagent/web`` router and the in-memory
``_tasks`` registry — the SSE runner now lives in routes/runs.py with
RunStore persistence, so those code paths simply don't exist anymore.)
"""

from __future__ import annotations

import asyncio

from finagent.engine.analysis.prompts import ANALYSIS_TYPES, _PROMPTS


class TestRegistryImportable:
    def test_registry_importable(self) -> None:
        from finagent.engine.pipelines.registry import get_pipeline_factories

        factories = get_pipeline_factories()
        assert "research" in factories
        assert "dcf" in factories
        assert "lbo" in factories


# ------------------------------------------------------------------ #
# Fix 4.6: ANALYSIS_TYPES derived from _PROMPTS                     #
# ------------------------------------------------------------------ #


class TestAnalysisTypesSingleSource:
    def test_analysis_types_equals_prompts_keys(self) -> None:
        assert ANALYSIS_TYPES == frozenset(_PROMPTS)

    def test_all_prompts_have_analysis_type(self) -> None:
        for key in _PROMPTS:
            assert key in ANALYSIS_TYPES

    def test_no_orphan_analysis_types(self) -> None:
        """No type in ANALYSIS_TYPES without a corresponding prompt."""
        for atype in ANALYSIS_TYPES:
            assert atype in _PROMPTS


# ------------------------------------------------------------------ #
# Fix 4.7: run_strategy_selection exposed in CLI/SDK                 #
# ------------------------------------------------------------------ #


class TestAutoBacktestCLI:
    def test_backtest_command_has_auto_flag(self) -> None:
        from click.testing import CliRunner

        from finagent.cli import backtest

        # --help should mention --auto
        runner = CliRunner()
        result = runner.invoke(backtest, ["--help"])
        assert "--auto" in result.output
        assert "LLM-guided" in result.output


class TestAutoBacktestSDK:
    def test_sdk_has_auto_backtest_methods(self) -> None:
        from finagent.sdk import FinAgent

        assert hasattr(FinAgent, "auto_backtest")
        assert hasattr(FinAgent, "aauto_backtest")
        assert callable(getattr(FinAgent, "auto_backtest"))
        assert asyncio.iscoroutinefunction(getattr(FinAgent, "aauto_backtest"))
