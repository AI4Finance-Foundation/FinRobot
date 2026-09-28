from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ValidationError
from starlette.requests import Request
from starlette.responses import StreamingResponse

from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.ticker import validate_ticker
from finrobot.llm_probe import LlmProbeGate

# registry is import-cheap by design (lazy per-pipeline factory via importlib —
# see its module docstring), so this does NOT pull the pydantic_ai stack onto the
# cold-start path; only pipelines.base (Pipeline/PipelineResult, below) does, and
# that is annotation-only here → TYPE_CHECKING.
from finrobot.engine.pipelines.registry import get_pipeline_factories
from finrobot.events import (
    ArtifactReady,
    RunCancelled,
    RunCompleted,
    RunEvent,
    RunFailed,
    RunStarted,
    StepCompleted,
    StepRetry,
    StepStarted,
)
from finrobot.obs import bind_run
from finrobot.run_store import TERMINAL_RUN_STATUSES, RunRecord, RunStore
from finrobot.warning_text import safe_error_text

if TYPE_CHECKING:
    # Annotation-only: pipelines.base pulls the pydantic_ai stack. Kept out of the
    # runtime import path for the sidecar cold start (tests/unit/test_cold_import.py).
    from finrobot.engine.pipelines.base import Pipeline, PipelineResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/runs", tags=["runs"])

# SSE idle-poll backoff. Both event streams poll the single shared RunStore
# connection; under a Coverage batch that means N coroutines hammering one
# aiosqlite worker. While events are flowing we poll fast (responsive UI); once
# a poll comes back empty we back off exponentially to a 1s ceiling, then snap
# back to the floor the instant new events appear. This keeps live latency low
# but collapses the steady-state QPS of idle/long-running streams (BUG-050).
_SSE_POLL_MIN_INTERVAL = 0.2
_SSE_POLL_MAX_INTERVAL = 1.0
_SSE_POLL_BACKOFF_FACTOR = 2.0

# Max run ids one aggregated /api/runs/events stream may multiplex — see the
# cap check in stream_runs_events.
_MAX_MULTIPLEX_IDS = 50


async def ensure_llm_reachable(request: Request) -> None:
    """503 unless the configured (model, key) has passed one live probe.

    Shared by every endpoint that spawns multi-step LLM work (runs).
    ``is_model_configured`` only proves a key EXISTS; this proves it can
    authenticate, so a garbage key is rejected at submit time with the same
    classified reason the Settings ✗ shows — instead of burning minutes of data
    collection and dying inside the first agent step. ``LlmProbeGate`` caches
    success per (model, key) fingerprint (pre-seeded by a green Settings
    auto-test), so steady-state submits make no extra LLM calls.
    """
    # getattr tolerance mirrors run_rate_limiter: unit-test apps skip the server
    # lifespan that normally creates the gate. Unlike the limiter we don't skip
    # enforcement — attach a fresh gate so the probe always runs.
    gate: LlmProbeGate | None = getattr(request.app.state, "llm_probe_gate", None)
    if gate is None:
        gate = LlmProbeGate()
        request.app.state.llm_probe_gate = gate
    ok, code, detail = await gate.ensure(request.app.state.deps.settings)
    if not ok:
        raise HTTPException(
            status_code=503,
            detail=(
                f"AI model connection check failed ({code}): "
                f"{detail or 'provider unreachable'} — fix the API key in Settings → AI Model."
            ),
        )


def _next_poll_interval(interval: float, *, had_events: bool) -> float:
    """Floor the interval when events arrived, else grow it toward the ceiling."""
    if had_events:
        return _SSE_POLL_MIN_INTERVAL
    return min(interval * _SSE_POLL_BACKOFF_FACTOR, _SSE_POLL_MAX_INTERVAL)


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
    # Shared validator: strips + upper-cases + rejects junk. The ValueError it
    # raises on a bad symbol is mapped to a 400 at create_run().
    return validate_ticker(t)


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
    # First-run guard: an empty model_name carries no startup_error (it's not an
    # error, it's onboarding), so it slips past the check above — but agents were
    # never built, so this run would crash. 503 with an actionable message that
    # the desktop preflight (AIZone) turns into a "去配置模型" affordance.
    if not request.app.state.deps.settings.is_model_configured:
        raise HTTPException(
            status_code=503,
            detail="No AI model configured. Choose one in Settings → AI Model.",
        )
    # Cold-start warming guard: sub_agents are built in a post-yield background
    # task (server lifespan), so a configured model can momentarily be un-built
    # right after boot — a run dispatched now would hand empty sub_agents to the
    # pipeline factory. agents_ready defaults True for test harnesses that wire
    # app.state without a lifespan, and a bad key is still caught by the probe gate
    # below; this only fires during the brief real cold-start window.
    if not getattr(request.app.state, "agents_ready", True):
        raise HTTPException(
            status_code=503,
            detail="AI engine is still starting — retry in a moment.",
        )
    # Key-validity gate: is_model_configured only proves a key EXISTS. A key
    # that cannot authenticate used to be accepted here, burn minutes of data
    # collection, then die inside the first agent LLM step — exactly the "假成功
    # 等到跑研报才炸" the Settings auto-test was added to kill. Probe once per
    # (model, key) fingerprint; success is cached (and pre-seeded by a green
    # Settings test), so steady-state submits stay free.
    await ensure_llm_reachable(request)

    factories = get_pipeline_factories()
    if pipeline_type not in factories:
        raise ValueError(f"Invalid pipeline: {pipeline_type}. Valid: {sorted(factories.keys())}")
    # Raises ValueError (→ 400) on blank or syntactically invalid ticker; the
    # shared validator subsumes the old `if not norm: raise` blank check.
    norm = _normalise_ticker(ticker)

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
    # Inbound rate-limit guard (BUG-043): every run spends real LLM money. This
    # token bucket is defense-in-depth, orthogonal to the concurrency cap
    # (run_semaphore, BUG-017) — it bounds runs STARTED per minute so a runaway
    # loop can't drain credits by keeping the queue full. One run → one token.
    limiter = getattr(request.app.state, "run_rate_limiter", None)
    if limiter is not None and not limiter.allow_runs(1):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded — too many runs started. Retry shortly.",
        )
    try:
        record = await spawn_run(
            request,
            request_body.pipeline_type,
            request_body.ticker,
            language=request_body.language,
            source_artifact_id=request_body.source_artifact_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=safe_error_text(exc, limit=500)) from exc
    return CreateRunResponse(
        run_id=record.run_id,
        status="created",
        pipeline_type=record.pipeline_type,
        ticker=record.ticker,
        created_at=record.created_at,
    )


_VALID_RUN_STATUSES = {"created", "running", *TERMINAL_RUN_STATUSES}


class RunSummary(BaseModel):
    """One GET /api/runs row — the run registry view, no result payload."""

    run_id: str
    status: str
    pipeline_type: str
    ticker: str
    created_at: str
    completed_at: str | None = None
    error: str | None = None


@router.get("", response_model=list[RunSummary])
async def list_runs(
    request: Request,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> list[RunSummary]:
    """Recent runs, newest first.

    ``status`` filters to a comma-separated status set — the desktop's
    restart-reattach asks for ``created,running`` on startup to find pipelines
    still executing after a webview reload and re-subscribe their SSE streams.
    Unknown status values are a 400, not a silent empty match.
    """
    statuses: list[str] | None = None
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        unknown = sorted(set(statuses) - _VALID_RUN_STATUSES)
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unknown run status(es): {', '.join(unknown)}. "
                    f"Valid: {', '.join(sorted(_VALID_RUN_STATUSES))}"
                ),
            )
    store: RunStore = request.app.state.run_store
    records = await store.list_runs(limit=limit, statuses=statuses)
    return [
        RunSummary(
            run_id=r.run_id,
            status=r.status,
            pipeline_type=r.pipeline_type,
            ticker=r.ticker,
            created_at=r.created_at,
            completed_at=r.completed_at,
            error=r.error,
        )
        for r in records
    ]


def _parse_multiplex_cursor(header: str | None) -> dict[str, int]:
    """Decode the aggregated stream's Last-Event-ID into per-id cursors.

    The single-run stream uses a bare integer seq as its event id. The
    aggregated stream multiplexes N runs, so a single integer can't express
    "where each run is up to". We encode the cursor as ``id:seq`` pairs joined
    by commas (``aaa:5,bbb:3``) and emit that same shape as each SSE event's
    ``id:`` line, so browser-native EventSource resume (Last-Event-ID) hands it
    straight back on reconnect and every run resumes from its own last seq —
    preserving the single-run stream's resume parity, per id. Malformed pairs
    are skipped (treated as "from the start") rather than raising, so a stale
    or truncated header can never 500 the stream.
    """
    cursors: dict[str, int] = {}
    if not header:
        return cursors
    for pair in header.split(","):
        run_id, _, raw_seq = pair.partition(":")
        run_id = run_id.strip()
        if run_id and raw_seq.strip().isdigit():
            cursors[run_id] = int(raw_seq.strip())
    return cursors


def _encode_multiplex_cursor(cursors: dict[str, int]) -> str:
    return ",".join(f"{rid}:{seq}" for rid, seq in cursors.items())


def _format_multiplex_sse(
    cursors: dict[str, int], run_id: str, ticker: str, event: RunEvent
) -> str:
    """Render one aggregated SSE frame.

    The ``id:`` line carries the FULL per-id cursor snapshot (so reconnect
    resumes every run, not just the one that emitted last). The data payload
    wraps the stored event with its routing keys (``run_id`` + ``ticker``) so
    the client can dispatch it to the right ticker's reducer without re-reading
    the run. The SSE ``event:`` type stays the original event name
    (run.started / step.completed / …) so the client reuses the exact same
    per-event listeners the single-run path uses.
    """
    payload = {"run_id": run_id, "ticker": ticker, "event": event}
    return (
        f"id: {_encode_multiplex_cursor(cursors)}\n"
        f"event: {event['event']}\n"
        f"data: {json.dumps(payload)}\n\n"
    )


@router.get("/events")
async def stream_runs_events(ids: str, request: Request) -> StreamingResponse:
    """Aggregated SSE stream multiplexing the events of several runs.

    ONE EventSource for a whole Coverage batch instead of one per run. The
    browser caps ~6 concurrent HTTP/1.1 connections per origin, so opening an
    EventSource per run for a 10-ticker batch saturated the pool: runs 7-10
    never streamed AND ordinary polling (price/health/overview) was blocked, so
    the app looked frozen (BUG-031). This route reuses the per-run read API
    (``get_events_after`` / ``get_run``) but interleaves all ids over a single
    connection, tagging each frame with its ``run_id`` + ``ticker`` for
    client-side routing.

    Registered BEFORE ``/{run_id}`` so the literal ``/events`` path wins over
    the ``{run_id}`` capture (FastAPI matches in declaration order).

    Resume: mirrors the single-run cursor handling, but per id — see
    ``_parse_multiplex_cursor``. Terminal: the stream closes once EVERY id has
    reached a terminal status (completed/failed) and its trailing events have
    been flushed; an unknown id (treated as already-terminal) can't hold the
    stream open forever.
    """
    raw_ids = [i.strip() for i in ids.split(",") if i.strip()]
    # De-dup while preserving order — a caller passing the same id twice must
    # not get double events or an inconsistent cursor.
    run_ids = list(dict.fromkeys(raw_ids))
    if not run_ids:
        raise HTTPException(status_code=400, detail="No run ids provided")
    # Cap the multiplex width. Every id costs a get_run + get_events_after per
    # poll round on the single shared aiosqlite worker; an unbounded ?ids= list
    # (script-built URL, not the UI) could wedge the store for every other
    # consumer. 50 is double the largest Coverage batch the UI can launch.
    if len(run_ids) > _MAX_MULTIPLEX_IDS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Too many run ids: {len(run_ids)} > {_MAX_MULTIPLEX_IDS}. "
                "Split the request into smaller batches."
            ),
        )

    store: RunStore = request.app.state.run_store

    # Resolve each id's ticker up front (for routing) and which ids actually
    # exist. A missing id is dropped from polling and counts as terminal.
    tickers: dict[str, str] = {}
    known_ids: list[str] = []
    for run_id in run_ids:
        record = await store.get_run(run_id)
        if record is not None:
            tickers[run_id] = record.ticker
            known_ids.append(run_id)
    if not known_ids:
        raise HTTPException(status_code=404, detail=f"No runs found for ids: {ids}")

    cursors = _parse_multiplex_cursor(request.headers.get("last-event-id"))
    # Seed cursors for every known id (default 0 = from the start) so the id:
    # line always carries a complete snapshot.
    for run_id in known_ids:
        cursors.setdefault(run_id, 0)

    async def event_stream() -> AsyncIterator[str]:
        terminal: set[str] = set()
        poll_interval = _SSE_POLL_MIN_INTERVAL
        while True:
            if await request.is_disconnected():
                logger.debug("Aggregated SSE client disconnected — stopping poll")
                return

            had_events = False
            for run_id in known_ids:
                if run_id in terminal:
                    continue
                events = await store.get_events_after(run_id, cursors[run_id])
                for stored in events:
                    had_events = True
                    cursors[run_id] = stored.seq
                    yield _format_multiplex_sse(cursors, run_id, tickers[run_id], stored.event)

                record = await store.get_run(run_id)
                if record is None or record.status in TERMINAL_RUN_STATUSES:
                    # Flush any trailing events that landed between the read
                    # above and the status read, then mark this id done.
                    trailing = await store.get_events_after(run_id, cursors[run_id])
                    for stored in trailing:
                        had_events = True
                        cursors[run_id] = stored.seq
                        yield _format_multiplex_sse(cursors, run_id, tickers[run_id], stored.event)
                    terminal.add(run_id)

            if len(terminal) == len(known_ids):
                break
            poll_interval = _next_poll_interval(poll_interval, had_events=had_events)
            await asyncio.sleep(poll_interval)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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


class CancelRunResponse(BaseModel):
    run_id: str
    status: str
    """``cancelling`` when the cancel was delivered to a live task (the
    terminal ``cancelled`` state lands moments later via SSE / re-poll),
    ``cancelled`` when this call itself finalised an orphaned record, or the
    run's existing terminal status when it had already finished (idempotent
    no-op — cancelling a completed run does not rewrite history)."""


@router.post("/{run_id}/cancel", response_model=CancelRunResponse)
async def cancel_run(run_id: str, request: Request) -> CancelRunResponse:
    """Cancel an in-flight run — the stop button for money-burning pipelines.

    Works for every task registered in app.state.run_tasks (research/dcf/lbo
    pipelines). Cancellation
    is asyncio-native: the task unwinds at its next await (LLM/provider calls
    are httpx awaits, so spend stops within one chunk), its CancelledError
    handler persists the ``cancelled`` terminal state, and the SSE stream
    closes like any other terminal path. A run whose task is gone (e.g. the
    record was orphaned by a crash between restarts) is finalised directly so
    the row can't stay wedged in "running" with nothing left to cancel.
    """
    store: RunStore = request.app.state.run_store
    record = await store.get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    if record.status in TERMINAL_RUN_STATUSES:
        return CancelRunResponse(run_id=run_id, status=record.status)

    task = request.app.state.run_tasks.get(run_id)
    if task is not None and not task.done():
        # Record user intent BEFORE delivering the cancel so the task's
        # CancelledError handler can distinguish this from a shutdown cancel.
        cancel_requested_set(request).add(run_id)
        if task.cancel():
            return CancelRunResponse(run_id=run_id, status="cancelling")
        # cancel() returned False: the task finished in the race window.
        cancel_requested_set(request).discard(run_id)
        refreshed = await store.get_run(run_id)
        if refreshed is not None and refreshed.status in TERMINAL_RUN_STATUSES:
            return CancelRunResponse(run_id=run_id, status=refreshed.status)

    # No live task but the record is non-terminal: an orphan (in-memory task
    # map lost in a crash, or a row the reconciler hasn't collected). Re-read
    # the status first — the task may have finished normally between the
    # record read and the task-map read, and finalising then would overwrite a
    # legitimate `completed` with `cancelled`. Then finalise here — same
    # event-before-status contract via finish_run.
    refreshed = await store.get_run(run_id)
    if refreshed is not None and refreshed.status in TERMINAL_RUN_STATUSES:
        return CancelRunResponse(run_id=run_id, status=refreshed.status)
    await store.finish_run(
        run_id,
        RunCancelled(event="run.cancelled", run_id=run_id, ticker=record.ticker),
        status="cancelled",
        completed_at=_iso_now(),
    )
    return CancelRunResponse(run_id=run_id, status="cancelled")


@router.get("/{run_id}/events")
async def stream_run_events(run_id: str, request: Request) -> StreamingResponse:
    store: RunStore = request.app.state.run_store
    if await store.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    last_event_id = request.headers.get("last-event-id")
    last_seq = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0

    async def event_stream() -> AsyncIterator[str]:
        current_seq = last_seq
        poll_interval = _SSE_POLL_MIN_INTERVAL
        while True:
            # Stop polling as soon as the client disconnects.  Without this
            # check the coroutine would keep polling the DB until the pipeline
            # finished, even though no one is reading the stream.
            # request.is_disconnected() does not raise; it returns True once
            # the underlying transport is gone.
            if await request.is_disconnected():
                logger.debug("SSE client disconnected for run %s — stopping poll", run_id)
                return

            had_events = False
            events = await store.get_events_after(run_id, current_seq)
            for stored in events:
                had_events = True
                current_seq = stored.seq
                yield _format_sse(stored.seq, stored.event)

            record = await store.get_run(run_id)
            if record and record.status in TERMINAL_RUN_STATUSES:
                trailing = await store.get_events_after(run_id, current_seq)
                for stored in trailing:
                    current_seq = stored.seq
                    yield _format_sse(stored.seq, stored.event)
                break
            poll_interval = _next_poll_interval(poll_interval, had_events=had_events)
            await asyncio.sleep(poll_interval)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


async def _run_pipeline(run_id: str, request: Request) -> None:
    # Concurrency is no longer gated here. The app-wide cap (Semaphore(4),
    # built in server.lifespan) is carried on app.state.deps.run_semaphore and
    # acquired INSIDE Pipeline.execute, so every run path — REST, chat
    # orchestrator, Coverage batch — acquires it exactly once with no risk of a
    # single run grabbing two slots (BUG-017). Acquiring inside execute means
    # the run is marked "running" by _run_pipeline_impl BEFORE it blocks on the
    # slot, so the "created → running" window now INCLUDES the queue wait while
    # the run waits for a free slot; only the per-step pipeline work follows.
    with bind_run(run_id):
        await _run_pipeline_impl(run_id, request)


async def _run_pipeline_impl(run_id: str, request: Request) -> None:
    store: RunStore = request.app.state.run_store
    record = await store.get_run(run_id)
    if record is None:
        return

    # Lazy: these pydantic_ai exception classes are named in the except tuple
    # below; importing here (not at module top) keeps the pydantic_ai stack off
    # the sidecar cold-start import path (tests/unit/test_cold_import.py).
    from pydantic_ai import UnexpectedModelBehavior
    from pydantic_ai.exceptions import AgentRunError

    started = time.monotonic()
    try:
        # Everything from here lives inside the try: the factory lookup
        # (KeyError when a pipeline was deregistered across a version bump),
        # the status flip and the RunStarted write (sqlite3.Error) used to
        # run BEFORE any handler existed — the task died with no terminal
        # state, the run sat at created/running forever and the SSE stream
        # never broke until the next restart's reconciler.
        factories = get_pipeline_factories()
        pipeline = factories[record.pipeline_type](request.app.state.sub_agents)
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
        await _execute_pipeline_run(run_id, request, store, record, pipeline, started)
    except asyncio.CancelledError:
        # Two callers cancel run tasks: POST /api/runs/{id}/cancel (records
        # intent in app.state.cancel_requested first) and server shutdown
        # (doesn't). Only the user-requested path persists the `cancelled`
        # terminal state here — event-before-status via finish_run, same
        # BUG-034 invariant as every terminal point — so the SSE stream closes
        # cleanly and the UI flips to a neutral "cancelled" card. On shutdown
        # we re-raise untouched: the store is being torn down, and the next
        # startup's reconciler marks the orphan failed("interrupted by server
        # restart"). Re-raise unconditionally — swallowing CancelledError
        # would break asyncio's cancellation contract.
        if run_id in cancel_requested_set(request):
            try:
                await store.finish_run(
                    run_id,
                    RunCancelled(event="run.cancelled", run_id=run_id, ticker=record.ticker),
                    status="cancelled",
                    completed_at=_iso_now(),
                    duration_s=round(time.monotonic() - started, 1),
                )
            except sqlite3.Error:
                logger.exception("Run %s: failed to persist cancelled state", run_id)
        raise
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
        sqlite3.Error,
        json.JSONDecodeError,
        httpx.HTTPError,
    ) as e:
        # Anything that escapes pipeline execution must transition the run to
        # `failed`, otherwise the SSE stream at /api/runs/{id}/events keeps
        # polling `record.status == "running"` forever (it only breaks on
        # completed/failed) and any client GETting the stream hangs. The
        # broad-but-explicit set (architecture audit forbids bare `except
        # Exception`) now includes sqlite3.Error — aiosqlite re-raises the
        # stdlib classes, which are NOT under OSError, and run_store's own
        # append_event re-raises OperationalError after logging.
        # CancelledError stays unaffected so shutdown still propagates.
        logger.exception("Pipeline %s failed unexpectedly", run_id)
        # finish_run appends run.failed BEFORE flipping status — same BUG-034
        # ordering invariant as the success branch, now mechanical.
        safe_error = safe_error_text(e, limit=500)
        try:
            await store.finish_run(
                run_id,
                RunFailed(
                    event="run.failed",
                    run_id=run_id,
                    error=safe_error,
                ),
                status="failed",
                completed_at=_iso_now(),
                duration_s=round(time.monotonic() - started, 1),
                error=safe_error,
            )
        except sqlite3.Error:
            # The store itself is down — nothing more to persist; the restart
            # reconciler collects the orphan.
            logger.exception("Run %s: failed to persist terminal state", run_id)
    finally:
        request.app.state.run_tasks.pop(run_id, None)
        cancel_requested_set(request).discard(run_id)


def cancel_requested_set(request: Request) -> set[str]:
    """The run_ids whose cancellation was user-requested (vs shutdown).

    Lives on app.state next to run_tasks; lazily created so test apps that
    build the router without the full server lifespan still work.
    """
    existing: set[str] | None = getattr(request.app.state, "cancel_requested", None)
    if existing is None:
        existing = set()
        request.app.state.cancel_requested = existing
    return existing


async def _execute_pipeline_run(
    run_id: str,
    request: Request,
    store: RunStore,
    record: RunRecord,
    pipeline: Pipeline,
    started: float,
) -> None:
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
            self,
            step_index: int,
            total: int,
            name: str,
            duration_s: float,
            error: str | None = None,
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
                    # A non-None error means the step DEGRADED (finished but
                    # failed validation after all retries on a non-critical
                    # step). The client renders amber instead of a green ✓
                    # (BUG-058). Truncate to match the step.retry error cap.
                    degraded=error is not None,
                    error=safe_error_text(error, limit=500) if error is not None else None,
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
                    error=safe_error_text(error, limit=500),
                ),
            )

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
    # finish_run appends run.completed BEFORE flipping the status (BUG-034,
    # now mechanical in RunStore): any reader that sees a terminal status is
    # guaranteed the terminal event already exists in run_events.
    await store.finish_run(
        run_id,
        RunCompleted(
            event="run.completed",
            run_id=run_id,
            ticker=record.ticker,
            duration_s=duration_s,
            # Point result_url at the artifact when there is one so a plain
            # consumer of the completion event can fetch the exact product;
            # fall back to the run url when no artifact was persisted.
            result_url=(f"/api/artifacts/{artifact_id}" if artifact_id else f"/api/runs/{run_id}"),
            artifact_id=artifact_id,
            artifact_type=artifact_type,
        ),
        status="completed",
        completed_at=_iso_now(),
        duration_s=duration_s,
        result_text=result.format_summary(),
        result_json=result_json,
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
    for key, value in result.structured_data.items():
        if hasattr(value, "model_dump"):
            dumped = value.model_dump(mode="json")
        else:
            dumped = str(value)
        structured[key] = dumped
    return {
        "structured_data": structured,
        "steps": result.steps,
        "failed_validations": result.failed_validations,
        # Same authoritative haul the artifact builder uses (run-level degrades
        # + failed-validation lines + structured warnings) so the /runs view and
        # the artifact view can never disagree about whether a run degraded.
        "warnings": result.collect_warnings(),
    }


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
