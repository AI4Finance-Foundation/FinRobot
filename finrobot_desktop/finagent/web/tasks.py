"""In-memory task store and pipeline runner for the web UI.

What this code does that raw LLM cannot: manages concurrent pipeline
execution as asyncio tasks, tracks state transitions (pending -> running ->
complete/error), collects structured log events, and exposes a task
lifecycle API. This is pure infrastructure logic with no LLM involvement.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from finagent.engine.data.interface import ProviderError


class TaskStatus(StrEnum):
    """Pipeline task lifecycle states."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    ERROR = "error"


class TaskInfo(BaseModel):
    """Typed representation of a tracked pipeline task."""

    task_id: str
    ticker: str
    pipeline_type: str
    status: TaskStatus
    logs: list[str]
    report_url: str | None = None
    created_at: str


# Module-level task store. Keyed by task_id. Capped at _MAX_TASKS.
_MAX_TASKS = 500
_MAX_RUNNING = 3
_tasks: dict[str, TaskInfo] = {}
# Parallel store for asyncio.Task references so we can cancel on eviction.
_async_tasks: dict[str, asyncio.Task[None]] = {}


def running_count() -> int:
    """Return the number of currently running tasks."""
    return sum(1 for t in _tasks.values() if t.status == TaskStatus.RUNNING)


def get_task(task_id: str) -> TaskInfo | None:
    return _tasks.get(task_id)


def list_tasks() -> list[TaskInfo]:
    """Return all tasks, most recent first."""
    return sorted(_tasks.values(), key=lambda t: t.created_at, reverse=True)


def _evict_oldest() -> None:
    """Remove oldest tasks when the store exceeds _MAX_TASKS.

    Fix 4.3: Cancel the associated asyncio.Task before removing references,
    preventing background coroutines from leaking resources (LLM calls, etc.).
    """
    if len(_tasks) <= _MAX_TASKS:
        return
    by_time = sorted(_tasks.keys(), key=lambda k: _tasks[k].created_at)
    for key in by_time[: len(_tasks) - _MAX_TASKS]:
        async_task = _async_tasks.pop(key, None)
        if async_task is not None and not async_task.done():
            async_task.cancel()
        del _tasks[key]


def create_task(ticker: str, pipeline_type: str) -> TaskInfo:
    """Create a new task entry in pending state."""
    task_id = uuid.uuid4().hex[:12]
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    task = TaskInfo(
        task_id=task_id,
        ticker=ticker.upper(),
        pipeline_type=pipeline_type,
        status=TaskStatus.PENDING,
        logs=[],
        created_at=now,
    )
    _tasks[task_id] = task
    _evict_oldest()
    return task


async def run_task(task: TaskInfo, app_state: Any) -> None:
    """Execute a pipeline for the given task using app.state resources.

    This function is designed to be wrapped in asyncio.create_task(). It
    updates the TaskInfo in-place as the pipeline progresses, making
    status available to the polling endpoint.
    """
    from pydantic import ValidationError

    from finagent.engine.orchestrator import build_report_context
    from finagent.engine.pipelines.registry import get_pipeline_factories

    task.status = TaskStatus.RUNNING
    task.logs.append(f"[INFO] Pipeline {task.pipeline_type} started for {task.ticker}")

    factories = get_pipeline_factories()
    if task.pipeline_type not in factories:
        task.status = TaskStatus.ERROR
        task.logs.append(
            f"[ERROR] Invalid pipeline type: {task.pipeline_type}. "
            f"Valid: {sorted(factories.keys())}"
        )
        return

    class TaskProgress:
        """ProgressCallback that writes to the task's log list."""

        async def on_step_start(
            self, step_index: int, total: int, name: str
        ) -> None:
            task.logs.append(f"[STEP] ({step_index}/{total}) Starting: {name}")

        async def on_step_end(
            self, step_index: int, total: int, name: str, duration: float
        ) -> None:
            task.logs.append(
                f"[STEP] ({step_index}/{total}) Completed: {name} "
                f"({duration:.1f}s)"
            )

        async def on_step_retry(
            self, step_index: int, name: str, attempt: int, error: str
        ) -> None:
            task.logs.append(
                f"[RETRY] Step {name} attempt {attempt}: {error[:200]}"
            )

    try:
        deps = app_state.deps
        sub_agents = app_state.sub_agents
        pipeline = factories[task.pipeline_type](sub_agents)
        result = await pipeline.execute(
            deps, task.ticker, progress=TaskProgress()
        )
        deps.report_cache[task.ticker] = build_report_context(
            task.ticker, result
        )
        report_url = f"/api/report/html?ticker={task.ticker}"
        task.report_url = report_url
        task.status = TaskStatus.COMPLETE
        task.logs.append(f"[COMPLETE] Report ready: {report_url}")
    except asyncio.CancelledError:
        task.status = TaskStatus.ERROR
        task.logs.append("[ERROR] Task was cancelled")
        raise
    except (ProviderError, ValidationError, ValueError, RuntimeError) as e:
        task.status = TaskStatus.ERROR
        task.logs.append(f"[ERROR] {str(e)[:500]}")


def register_async_task(task_id: str, async_task: asyncio.Task[None]) -> None:
    """Store the asyncio.Task reference so eviction can cancel it."""
    _async_tasks[task_id] = async_task


def clear_tasks() -> None:
    """Clear all tasks. Used by tests."""
    for at in _async_tasks.values():
        if not at.done():
            at.cancel()
    _async_tasks.clear()
    _tasks.clear()
