from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError
from pydantic_ai import UnexpectedModelBehavior
from starlette.requests import Request
from starlette.responses import StreamingResponse

from finagent.engine.data.interface import ProviderError
from finagent.engine.orchestrator import build_report_context
from finagent.engine.pipelines.base import PipelineResult
from finagent.engine.pipelines.registry import get_pipeline_factories
from finagent.events import (
    ArtifactReady,
    RunCompleted,
    RunEvent,
    RunFailed,
    RunStarted,
    StepCompleted,
    StepRetry,
    StepStarted,
)
from finagent.run_store import RunRecord, RunStore

router = APIRouter(prefix="/api/runs", tags=["runs"])


class CreateRunRequest(BaseModel):
    pipeline_type: str
    ticker: str

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


class RunListResponse(BaseModel):
    runs: list[RunRecord]


@router.post("", response_model=CreateRunResponse)
async def create_run(request_body: CreateRunRequest, request: Request) -> CreateRunResponse:
    factories = get_pipeline_factories()
    if request_body.pipeline_type not in factories:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid pipeline: {request_body.pipeline_type}. Valid: {sorted(factories.keys())}"
            ),
        )

    ticker = _normalise_ticker(request_body.ticker)
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker is required")

    store: RunStore = request.app.state.run_store
    record = await store.create_run(request_body.pipeline_type, ticker)
    task = asyncio.create_task(_run_pipeline(record.run_id, request))
    request.app.state.run_tasks[record.run_id] = task
    return CreateRunResponse(
        run_id=record.run_id,
        status="created",
        pipeline_type=record.pipeline_type,
        ticker=record.ticker,
        created_at=record.created_at,
    )


@router.get("", response_model=RunListResponse)
async def list_runs(request: Request) -> RunListResponse:
    store: RunStore = request.app.state.run_store
    return RunListResponse(runs=await store.list_runs())


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
    if raw:
        failed_validations = raw.get("failed_validations", [])
        warnings = raw.get("warnings", [])
    # Flatten: expose structured_data directly (remove redundant nesting)
    flat_structured = raw.get("structured_data", {}) if raw else None
    result = None
    if record.result_text is not None or flat_structured is not None:
        result = RunResult(text=record.result_text, structured=flat_structured)
    steps_dict = raw.get("steps") if raw else None
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
        )
        request.app.state.deps.report_cache[record.ticker] = build_report_context(
            record.ticker, result
        )
        duration_s = round(time.monotonic() - started, 1)
        result_json = _result_to_json(result)
        await store.add_artifact(
            run_id,
            artifact_type="report",
            format="html",
            file_path=f"/api/report/html?ticker={record.ticker}",
        )
        await _append(
            store,
            ArtifactReady(
                event="artifact.ready",
                run_id=run_id,
                artifact_type="report",
                format="html",
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
                result_url=f"/api/runs/{run_id}",
            ),
        )
    except (ProviderError, ValidationError, ValueError, RuntimeError, UnexpectedModelBehavior) as e:
        await store.update_run(
            run_id,
            status="failed",
            completed_at=_iso_now(),
            duration_s=round(time.monotonic() - started, 1),
            error=str(e)[:500],
        )
        await _append(
            store,
            RunFailed(
                event="run.failed",
                run_id=run_id,
                error=str(e)[:500],
            ),
        )
    finally:
        request.app.state.run_tasks.pop(run_id, None)


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
