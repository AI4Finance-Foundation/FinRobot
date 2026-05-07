"""Tests for batch 4 code quality fixes.

Fix 4.3: asyncio task cancellation on eviction
Fix 4.4: circular import elimination (tasks.py → server.py)
Fix 4.6: ANALYSIS_TYPES derived from _PROMPTS
Fix 4.7: run_strategy_selection exposed in CLI/SDK
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from finagent.engine.analysis.prompts import ANALYSIS_TYPES, _PROMPTS


# ------------------------------------------------------------------ #
# Fix 4.3: asyncio task cancellation on eviction                     #
# ------------------------------------------------------------------ #


class TestTaskEvictionCancellation:
    def test_evict_cancels_running_async_task(self) -> None:
        """When a task is evicted, its asyncio.Task must be cancelled."""
        from finagent.web.tasks import (
            _MAX_TASKS,
            _async_tasks,
            _tasks,
            clear_tasks,
            create_task,
            register_async_task,
        )

        clear_tasks()

        # Create _MAX_TASKS tasks, then one more to trigger eviction
        first_task = create_task("OLD", "research")
        mock_async = MagicMock(spec=asyncio.Task)
        mock_async.done.return_value = False
        register_async_task(first_task.task_id, mock_async)

        for i in range(_MAX_TASKS):
            create_task(f"T{i}", "dcf")

        # The first task should have been evicted and its async task cancelled
        assert first_task.task_id not in _tasks
        assert first_task.task_id not in _async_tasks
        mock_async.cancel.assert_called_once()

        clear_tasks()

    def test_evict_skips_already_done_task(self) -> None:
        """Already-completed asyncio.Tasks should not be cancelled."""
        from finagent.web.tasks import (
            _MAX_TASKS,
            clear_tasks,
            create_task,
            register_async_task,
        )

        clear_tasks()

        first_task = create_task("DONE", "research")
        mock_async = MagicMock(spec=asyncio.Task)
        mock_async.done.return_value = True
        register_async_task(first_task.task_id, mock_async)

        for i in range(_MAX_TASKS):
            create_task(f"T{i}", "dcf")

        mock_async.cancel.assert_not_called()
        clear_tasks()

    def test_clear_tasks_cancels_running(self) -> None:
        """clear_tasks() should cancel all running asyncio.Tasks."""
        from finagent.web.tasks import (
            clear_tasks,
            create_task,
            register_async_task,
        )

        clear_tasks()
        task = create_task("X", "comps")
        mock_async = MagicMock(spec=asyncio.Task)
        mock_async.done.return_value = False
        register_async_task(task.task_id, mock_async)

        clear_tasks()
        mock_async.cancel.assert_called_once()


# ------------------------------------------------------------------ #
# Fix 4.4: circular import elimination                               #
# ------------------------------------------------------------------ #


class TestCircularImportFixed:
    def test_tasks_does_not_import_server(self) -> None:
        """tasks.py should import from pipelines.registry, not server."""
        import inspect

        from finagent.web import tasks

        source = inspect.getsource(tasks)
        assert "from finagent.server" not in source

    def test_registry_importable(self) -> None:
        from finagent.engine.pipelines.registry import get_pipeline_factories

        factories = get_pipeline_factories()
        assert "research" in factories
        assert "dcf" in factories
        assert "lbo" in factories

    def test_server_still_works(self) -> None:
        """server._get_pipeline_factories still delegates to registry."""
        from finagent.server import _get_pipeline_factories

        factories = _get_pipeline_factories()
        assert "research" in factories


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
