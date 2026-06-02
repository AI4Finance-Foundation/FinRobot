from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError
from pydantic_ai import UnexpectedModelBehavior
from pydantic_ai.exceptions import AgentRunError
from starlette.requests import Request
from starlette.responses import StreamingResponse

from finrobot.engine.data.interface import ProviderError
from finrobot.engine.pipelines.base import PipelineResult
from finrobot.engine.pipelines.registry import get_pipeline_factories
from finrobot.events import (
    ArtifactReady,
    RunCompleted,
    RunEvent,
    RunFailed,
    RunStarted,
    StepCompleted,
    StepRetry,
    StepStarted,
)
from finrobot.obs import bind_run
from finrobot.run_store import RunRecord, RunStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/runs", tags=["runs"])


class CreateRunRequest(BaseModel):
    pipeline_type: str
    ticker: str
    language: Literal["en", "zh"] | None = None
    """Output language for the report's prose. Set by the frontend from the
    current UI locale at trigger time; None → pipeline falls back to
    settings.language. Stamped onto the artifact's meta.language."""

    source_artifact_id: str | None = None
    """When this run is a re-run triggered from an existing report, the id of
    that source artifact. Stamped onto the new artifact's
    meta.parent_artifact_id so the version-diff view can default to comparing
    against the version it was re-run from. None for fresh runs."""

    @classmethod
    def model_validate_strict(cls, data: Any) -> "CreateRunRequest":
        # Pydantic would happily accept ticker="" — reject early so the
        # frontend (or curl users) get a clean 422 instead of a stack trace
        # buried inside the pipeline orchestrator.
        return cls.model_validate(data)


def _normalise_ticker(t: str) -> str:
    return t.strip().upper()


class CreateRunResponse(BaseModel):
    run_id: str
    status: Literal["created"]
    pipeline_type: str
    ticker: str
    created_at: str


class RunResult(BaseModel):
    text: str | None = None
    structured: dict[str, Any] | None = None


class RunDetail(BaseModel):
    run_id: str
    status: str
    pipeline_type: str
    ticker: str
    created_at: str
    completed_at: str | None = None
    duration_s: float | None = None
    result: RunResult | None = None
    artifacts: list[dict[str, Any]] = []
    warnings: list[str] = []
    failed_validations: list[dict[str, str]] = []
    steps: dict[str, str] | None = None
    error: str | None = None


async def spawn_run(
    request: Request,
    pipeline_type: str,
    ticker: str,
    *,
    language: str | None = None,
    source_artifact_id: str | None = None,
) -> RunRecord:
    """Create a run record and spawn its pipeline task.

    Shared by the single-run route and the Coverage batch-run endpoint so
    neither duplicates the create-record → spawn-task → register-in-run_tasks
    dance (and both inherit the same concurrency cap, since every task goes
    through ``_run_pipeline``). Raises ``ValueError`` for an unknown
    ``pipeline_type`` or blank ticker — callers map it to an HTTP error.

    Raises ``HTTPException(503)`` when ``app.state.startup_error`` is set:
    every registered pipeline (research/dcf/lbo/...) drives sub-agents that
    need a configured LLM, so a broken runtime config can't possibly produce
    a valid run. Gating HERE — before ``create_run`` — means no orphan
    "created" row is persisted, and the 503 (an HTTPException, not the
    ValueError the batch handler catches) propagates so a misconfigured box
    fails the whole Coverage batch instead of silently skipping every ticker
    (BUG-20260602-056).
    """
    startup_error = getattr(request.app.state, "startup_error", None)
    if startup_error:
        raise HTTPException(status_code=503, detail=f"Server not ready: {startup_error}")

    factories = get_pipeline_factories()
    if pipeline_type not in factories:
        raise ValueError(f"Invalid pipeline: {pipeline_type}. Valid: {sorted(factories.keys())}")
    norm = _normalise_ticker(ticker)
    if not norm:
        raise ValueError("ticker is required")

    store: RunStore = request.app.state.run_store
    record = await store.create_run(
        pipeline_type,
        norm,
        language=language,
        source_artifact_id=source_artifact_id,
    )
    task = asyncio.create_task(_run_pipeline(record.run_id, request))
    request.app.state.run_tasks[record.run_id] = task
    return record


@router.post("", response_model=CreateRunResponse)
async def create_run(request_body: CreateRunRequest, request: Request) -> CreateRunResponse:
    try:
        record = await spawn_run(
            request,
            request_body.pipeline_type,
            request_body.ticker,
            language=request_body.language,
            source_artifact_id=request_body.source_artifact_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CreateRunResponse(
        run_id=record.run_id,
        status="created",
        pipeline_type=record.pipeline_type,
        ticker=record.ticker,
        created_at=record.created_at,
    )


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(run_id: str, request: Request) -> RunDetail:
    store: RunStore = request.app.state.run_store
    record = await store.get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    artifacts = [a.model_dump() for a in await store.list_artifacts(run_id)]
    failed_validations = []
    warnings: list[str] = []
    raw = record.result_json
    # result_json must be a dict produced by _result_to_json().  Rows
    # persisted by older schema versions or corrupted writes may contain a
    # list or other non-dict type; guard with isinstance so we never let a
    # spurious AttributeError propagate as a 500.
    raw_dict = raw if isinstance(raw, dict) else None
    if raw_dict is not None:
        failed_validations = raw_dict.get("failed_validations", [])
        warnings = raw_dict.get("warnings", [])
    # Flatten: expose structured_data directly (remove redundant nesting)
    flat_structured = raw_dict.get("structured_data", {}) if raw_dict is not None else None
    result = None
    if record.result_text is not None or flat_structured is not None:
        result = RunResult(text=record.result_text, structured=flat_structured)
    steps_dict = raw_dict.get("steps") if raw_dict is not None else None
    return RunDetail(
        run_id=record.run_id,
        status=record.status,
        pipeline_type=record.pipeline_type,
        ticker=record.ticker,
        created_at=record.created_at,
        completed_at=record.completed_at,
        duration_s=record.duration_s,
        result=result,
        artifacts=artifacts,
        warnings=warnings,
        failed_validations=failed_validations,
        steps=steps_dict,
        error=record.error,
    )


@router.get("/{run_id}/events")
async def stream_run_events(run_id: str, request: Request) -> StreamingResponse:
    store: RunStore = request.app.state.run_store
    if await store.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    last_event_id = request.headers.get("last-event-id")
    last_seq = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0

    async def event_stream() -> AsyncIterator[str]:
        current_seq = last_seq
        while True:
            # Stop polling as soon as the client disconnects.  Without this
            # check the coroutine would keep polling the DB at 0.2 s intervals
            # until the pipeline finished, even though no one is reading the
            # stream.  request.is_disconnected() does not raise; it returns
            # True once the underlying transport is gone.
            if await request.is_disconnected():
                logger.debug("SSE client disconnected for run %s — stopping poll", run_id)
                return

            events = await store.get_events_after(run_id, current_seq)
            for stored in events:
                current_seq = stored.seq
                yield _format_sse(stored.seq, stored.event)

            record = await store.get_run(run_id)
            if record and record.status in {"completed", "failed"}:
                trailing = await store.get_events_after(run_id, current_seq)
                for stored in trailing:
                    current_seq = stored.seq
                    yield _format_sse(stored.seq, stored.event)
                break
            await asyncio.sleep(0.2)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


async def _run_pipeline(run_id: str, request: Request) -> None:
    with bind_run(run_id):
        semaphore = getattr(request.app.state, "run_semaphore", None)
        if semaphore is None:
            await _run_pipeline_impl(run_id, request)
        else:
            # Bound concurrent pipelines app-wide: a batch of N coverage runs
            # must not fire N LLM pipelines at once and blow provider/LLM rate
            # limits (Coverage Phase 2/M4c). The whole impl runs inside the
            # slot, so a queued run stays "created" (status reflects reality
            # for the overview) and its duration excludes queue time.
            async with semaphore:
                await _run_pipeline_impl(run_id, request)


async def _run_pipeline_impl(run_id: str, request: Request) -> None:
    store: RunStore = request.app.state.run_store
    record = await store.get_run(run_id)
    if record is None:
        return

    factories = get_pipeline_factories()
    pipeline = factories[record.pipeline_type](request.app.state.sub_agents)
    started = time.monotonic()
    await store.update_run(run_id, status="running")
    await _append(
        store,
        RunStarted(
            event="run.started",
            run_id=run_id,
            pipeline_type=record.pipeline_type,
            ticker=record.ticker,
            total_steps=len(pipeline.steps),
        ),
    )

    class RunProgress:
        async def on_step_start(self, step_index: int, total: int, name: str) -> None:
            await _append(
                store,
                StepStarted(
                    event="step.started",
                    run_id=run_id,
                    step=step_index,
                    total=total,
                    name=name,
                ),
            )

        async def on_step_end(
            self, step_index: int, total: int, name: str, duration_s: float
        ) -> None:
            await _append(
                store,
                StepCompleted(
                    event="step.completed",
                    run_id=run_id,
                    step=step_index,
                    total=total,
                    name=name,
                    duration_s=round(duration_s, 1),
                ),
            )

        async def on_step_retry(self, step_index: int, name: str, attempt: int, error: str) -> None:
            await _append(
                store,
                StepRetry(
                    event="step.retry",
                    run_id=run_id,
                    step=step_index,
                    total=len(pipeline.steps),
                    name=name,
                    attempt=attempt,
                    error=error[:500],
                ),
            )

    try:
        result = await pipeline.execute(
            request.app.state.deps,
            record.ticker,
            progress=RunProgress(),
            lang=record.language,
            source_artifact_id=record.source_artifact_id,
        )
        duration_s = round(time.monotonic() - started, 1)
        result_json = _result_to_json(result)
        artifact_id = result.artifact_id
        # Resolve the artifact's real type (dcf/lbo/comps/equity_research/...)
        # from the persisted artifact so the completion events carry true
        # identity. The run_store's artifact_type column historically held the
        # opaque "artifact" placeholder; we now store the real type so
        # list_artifacts and any consumer reflect what was actually produced.
        artifact_type: str | None = None
        if artifact_id:
            artifact_type = await _resolve_artifact_type(request, artifact_id)
            await store.add_artifact(
                run_id,
                artifact_type=artifact_type or "artifact",
                format="json",
                file_path=f"/api/artifacts/{artifact_id}",
            )
            await _append(
                store,
                ArtifactReady(
                    event="artifact.ready",
                    run_id=run_id,
                    artifact_type=artifact_type or "artifact",
                    format="json",
                    artifact_id=artifact_id,
                ),
            )
        await store.update_run(
            run_id,
            status="completed",
            completed_at=_iso_now(),
            duration_s=duration_s,
            result_text=result.format_summary(),
            result_json=result_json,
        )
        await _append(
            store,
            RunCompleted(
                event="run.completed",
                run_id=run_id,
                ticker=record.ticker,
                duration_s=duration_s,
                # Point result_url at the artifact when there is one so a plain
                # consumer of the completion event can fetch the exact product;
                # fall back to the run url when no artifact was persisted.
                result_url=(
                    f"/api/artifacts/{artifact_id}" if artifact_id else f"/api/runs/{run_id}"
                ),
                artifact_id=artifact_id,
                artifact_type=artifact_type,
            ),
        )
        if artifact_id:
            # A new artifact just landed in the store. Drop the dashboard's
            # 60s TTL caches so the landing hit-rate + recent-research strip
            # reflect this run on the next GET instead of up to a minute later
            # (BUG-20260602-030). Local import: routes.dashboard imports nothing
            # from routes.runs, but keep the dependency one-directional and
            # lazy so the module graph stays acyclic regardless of future edits.
            from finrobot.routes.dashboard import invalidate_dashboard_caches

            invalidate_dashboard_caches()
    except (
        ProviderError,
        ValidationError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RuntimeError,
        UnexpectedModelBehavior,
        AgentRunError,
        OSError,
        json.JSONDecodeError,
        httpx.HTTPError,
    ) as e:
        # Anything that escapes pipeline execution must transition the run to
        # `failed`, otherwise the SSE stream at /api/runs/{id}/events keeps
        # polling `record.status == "running"` forever (it only breaks on
        # completed/failed) and any client GETting the stream hangs. The old
        # narrower tuple silently lost TypeError/AttributeError/etc. — the
        # task died with the exception, status stayed `running`, the test
        # runner hung, the desktop UI overlay would have hung too. We catch
        # the broad-but-explicit set here (architecture audit forbids bare
        # `except Exception`); CancelledError stays unaffected so shutdown
        # still propagates cleanly.
        logger.exception("Pipeline %s failed unexpectedly", run_id)
        await store.update_run(
            run_id,
            status="failed",
            completed_at=_iso_now(),
            duration_s=round(time.monotonic() - started, 1),
            error=str(e)[:500] or type(e).__name__,
        )
        await _append(
            store,
            RunFailed(
                event="run.failed",
                run_id=run_id,
                error=str(e)[:500] or type(e).__name__,
            ),
        )
    finally:
        request.app.state.run_tasks.pop(run_id, None)


async def _resolve_artifact_type(request: Request, artifact_id: str) -> str | None:
    """Fetch the persisted artifact's real type (dcf/lbo/comps/...).

    The pipeline result only carries an ``artifact_id``; the canonical type
    lives on the saved Artifact. We read it from the artifact_store so the
    completion events name the true product instead of the opaque "artifact"
    placeholder. Returns None if the store is absent or the artifact can't be
    loaded — callers degrade to the placeholder rather than failing the run.
    """
    artifact_store = getattr(request.app.state, "artifact_store", None)
    if artifact_store is None:
        return None
    try:
        artifact = await artifact_store.get(artifact_id)
    except (OSError, ValueError, KeyError):
        logger.warning("Could not load artifact %s to resolve its type", artifact_id)
        return None
    return str(artifact.type) if artifact is not None else None


async def _append(store: RunStore, event: RunEvent) -> int:
    return await store.append_event(event["run_id"], event)


def _format_sse(seq: int, event: RunEvent) -> str:
    return f"id: {seq}\nevent: {event['event']}\ndata: {json.dumps(event)}\n\n"


def _result_to_json(result: PipelineResult) -> dict[str, Any]:
    structured: dict[str, Any] = {}
    warnings: list[str] = []
    for key, value in result.structured_data.items():
        if hasattr(value, "model_dump"):
            dumped = value.model_dump(mode="json")
        else:
            dumped = str(value)
        structured[key] = dumped
        if hasattr(value, "warnings"):
            for warning in value.warnings:
                if warning not in warnings:
                    warnings.append(warning)
    return {
        "structured_data": structured,
        "steps": result.steps,
        "failed_validations": result.failed_validations,
        "warnings": warnings,
    }


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
