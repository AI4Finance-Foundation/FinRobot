"""POST /api/debate — create an IC debate run backed by an existing artifact.

SSE decision: Option A — the generic /api/runs/{run_id}/events endpoint in
runs.py is run_id-universal; it only verifies that the run_id exists in
RunStore, then polls run_events.  Creating a run via RunStore.create_run
registers the run_id, so debate runs are served by the same SSE machinery
with no duplication.

Structured-data contract:
  artifact.outputs.structured  is the dict produced by the equity_research
  pipeline (valuation_synthesis + method breakdown).
  build_evidence_set() expects that exact shape — see engine/debate/evidence.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from typing import Any, cast

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError, field_validator
from pydantic_ai import UnexpectedModelBehavior
from pydantic_ai.exceptions import AgentRunError
from starlette.requests import Request

from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.ticker import validate_ticker
from finrobot.engine.debate.agents import build_debate_agents
from finrobot.engine.debate.evidence import build_evidence_set
from finrobot.engine.debate.service import run_debate
from finrobot.events import RunCancelled, RunCompleted, RunEvent, RunFailed, RunStarted
from finrobot.routes.runs import cancel_requested_set
from finrobot.run_store import RunStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/debate", tags=["debate"])


class DebateRequest(BaseModel):
    # Reject empty/oversized input at validation time (422) rather than storing a
    # malformed run — same constraint as the compute routes (BUG-032 / BUG-040).
    ticker: str = Field(min_length=1, max_length=12)
    artifact_id: str = Field(min_length=1)

    @field_validator("ticker")
    @classmethod
    def _validate_ticker(cls, value: str) -> str:
        return validate_ticker(value)


class DebateResponse(BaseModel):
    run_id: str


@router.post("", response_model=DebateResponse)
async def create_debate(body: DebateRequest, request: Request) -> DebateResponse:
    """Launch an IC debate run for an existing equity_research artifact.

    Steps:
      1. Fetch the artifact from ArtifactStore; 404 if absent.
      2. Extract deterministic evidence from artifact.outputs.structured.
      3. Create a run in RunStore (pipeline_type="debate").
      4. Build debate agents from settings.
      5. Fire off background task; return run_id immediately.

    The caller streams debate.point / debate.verdict events via the existing
    generic SSE endpoint:  GET /api/runs/{run_id}/events
    """
    # Same three money-gates as POST /api/runs — debate drives THREE LLM agents
    # (bull/bear → verify → judge) and was the only LLM-spending endpoint
    # outside all of them (the ratelimit module docstring even counted "three
    # endpoints spend real LLM money" — this was the uncounted fourth).
    startup_error = getattr(request.app.state, "startup_error", None)
    if startup_error:
        raise HTTPException(status_code=503, detail=f"Server not ready: {startup_error}")
    limiter = getattr(request.app.state, "run_rate_limiter", None)
    if limiter is not None and not limiter.allow_runs(1):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded — too many runs started. Retry shortly.",
        )

    artifact_store = request.app.state.artifact_store
    artifact = await artifact_store.get(body.artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail=f"Artifact not found: {body.artifact_id}")

    structured_data: dict[str, Any] = artifact.outputs.structured
    # build_evidence_set float()s current_price / upside_downside / weighted_price
    # / method mids straight off the artifact. A malformed or incomplete artifact
    # (non-numeric field, wrong shape) would otherwise escape here as a raw 500 —
    # this is the sync path before the background task, so _run_debate_task's
    # try/except can't catch it. Surface a client-facing 422 instead (BUG-021).
    try:
        evidence_set = build_evidence_set(structured_data, body.artifact_id)
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Artifact {body.artifact_id} has structured data unfit for debate: {exc}",
        ) from exc

    # Build agents BEFORE create_run: provider construction raises when the
    # runtime config broke after boot (revoked key), and failing here leaves
    # no orphan "created" row behind.
    settings = request.app.state.deps.settings
    agents = build_debate_agents(settings)

    run_store: RunStore = request.app.state.run_store
    record = await run_store.create_run("debate", body.ticker)
    run_id = record.run_id

    # Debate language follows the debated artifact, not the viewer's UI locale —
    # an English report must produce an English debate (ADR-0008). Legacy
    # artifacts (no language field) default to 'zh' via ArtifactMeta.
    lang = artifact.meta.language

    task = asyncio.create_task(
        _run_debate_task(run_id, evidence_set, agents, run_store, request, lang)
    )
    request.app.state.run_tasks[run_id] = task

    return DebateResponse(run_id=run_id)


async def _run_debate_task(
    run_id: str,
    evidence_set: Any,
    agents: dict[str, Any],
    run_store: RunStore,
    request: Request,
    lang: str = "zh",
) -> None:
    """Background task: orchestrate debate, mark run completed/failed.

    Exception handling mirrors runs.py::_run_pipeline_impl — we catch the
    broad-but-explicit set that can escape debate orchestration so that the
    run transitions to 'failed' and the SSE stream breaks cleanly.  Bare
    blanket catches are forbidden (CLAUDE.md N2 / P3 audit D1); CancelledError
    is intentionally NOT caught so Ctrl-C / server shutdown propagates normally.

    Emit: async closure that writes each event to RunStore immediately as
    run_debate produces it, matching runs.py's RunProgress pattern.  Events
    are injected with run_id before writing so RunStore.append_event can find
    event["run_id"] (see runs.py::_append).  cast(RunEvent, ...) is the
    sanctioned assertion that the runtime dict satisfies the TypedDict union —
    the shape is guaranteed by service.py's emit call sites.
    """
    from datetime import datetime, timezone

    started = time.monotonic()

    async def _emit(ev: dict[str, Any]) -> None:
        await run_store.append_event(run_id, cast(RunEvent, {**ev, "run_id": run_id}))

    try:
        # The status flip / RunStarted writes live INSIDE the try: a sqlite
        # error here used to kill the task before any handler existed, leaving
        # the run stuck at "created" forever (SSE polls a run that will never
        # finish until the next restart's reconciler).
        await run_store.update_run(run_id, status="running")
        await run_store.append_event(
            run_id,
            RunStarted(
                event="run.started",
                run_id=run_id,
                pipeline_type="debate",
                ticker=evidence_set.ticker,
                total_steps=3,  # bull/bear → verify → judge
            ),
        )
        deps = request.app.state.deps
        # Debate shares the app-wide LLM concurrency cap with every pipeline
        # run (BUG-017's Semaphore). It was the only LLM path outside the cap:
        # N debates + 4 pipelines used to run 3·N+4 concurrent agent streams.
        # Acquired AFTER the "running" flip so the queue wait is visible as
        # running, same as Pipeline.execute.
        async with deps.run_semaphore:
            await run_debate(evidence_set, agents, emit=_emit, deps=deps, lang=lang)

        duration_s = round(time.monotonic() - started, 1)
        # finish_run appends run.completed BEFORE flipping status (BUG-034) —
        # this path used to do it backwards: a poll landing between the two
        # commits saw "completed", fetched trailing events without
        # run.completed, broke, and the client EventSource reconnect-stormed
        # into the "请检查后端服务" banner this file's own comment describes.
        await run_store.finish_run(
            run_id,
            RunCompleted(
                event="run.completed",
                run_id=run_id,
                ticker=evidence_set.ticker,
                duration_s=duration_s,
                result_url=f"/api/runs/{run_id}",
            ),
            status="completed",
            completed_at=datetime.now(tz=timezone.utc).isoformat(),
            duration_s=duration_s,
        )
    except asyncio.CancelledError:
        # Mirrors runs.py::_run_pipeline_impl — POST /api/runs/{id}/cancel
        # works for debate runs too (they register in the same
        # app.state.run_tasks). User-requested cancels (recorded in
        # app.state.cancel_requested before task.cancel()) persist the
        # `cancelled` terminal state; shutdown cancels re-raise untouched and
        # the next startup's reconciler collects the orphan.
        if run_id in cancel_requested_set(request):
            try:
                await run_store.finish_run(
                    run_id,
                    RunCancelled(event="run.cancelled", run_id=run_id, ticker=evidence_set.ticker),
                    status="cancelled",
                    completed_at=datetime.now(tz=timezone.utc).isoformat(),
                    duration_s=round(time.monotonic() - started, 1),
                )
            except sqlite3.Error:
                logger.exception("Debate run %s: failed to persist cancelled state", run_id)
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
    ) as exc:
        # Task-boundary exception handler: mirrors runs.py::_run_pipeline_impl.
        # The set is broad-but-explicit — covers every concrete failure mode
        # that can escape run_debate: LLM API errors (AgentRunError,
        # UnexpectedModelBehavior, httpx.HTTPError), output schema failures
        # (ValidationError), data provider errors (ProviderError), store errors
        # (sqlite3.Error — aiosqlite re-raises the stdlib classes, which are
        # NOT under OSError), and standard Python/IO errors. CancelledError is
        # intentionally omitted so server shutdown propagates cleanly. Without
        # this full set a failing LLM agent would leave the run at
        # status="running" and the SSE stream would hang forever.
        logger.exception("Debate run %s failed", run_id)
        error_msg = str(exc)[:500] or type(exc).__name__
        try:
            await run_store.finish_run(
                run_id,
                RunFailed(event="run.failed", run_id=run_id, error=error_msg),
                status="failed",
                completed_at=datetime.now(tz=timezone.utc).isoformat(),
                duration_s=round(time.monotonic() - started, 1),
                error=error_msg,
            )
        except sqlite3.Error:
            # The store itself is down — nothing more we can persist; the
            # restart reconciler will collect the orphan.
            logger.exception("Debate run %s: failed to persist terminal state", run_id)
    finally:
        request.app.state.run_tasks.pop(run_id, None)
        cancel_requested_set(request).discard(run_id)
