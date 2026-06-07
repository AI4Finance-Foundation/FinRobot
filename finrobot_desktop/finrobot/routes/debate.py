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
from finrobot.events import RunCompleted, RunEvent, RunFailed, RunStarted
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

    run_store: RunStore = request.app.state.run_store
    record = await run_store.create_run("debate", body.ticker)
    run_id = record.run_id

    settings = request.app.state.deps.settings
    agents = build_debate_agents(settings)

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

    async def _emit(ev: dict[str, Any]) -> None:
        await run_store.append_event(run_id, cast(RunEvent, {**ev, "run_id": run_id}))

    try:
        deps = request.app.state.deps
        await run_debate(evidence_set, agents, emit=_emit, deps=deps, lang=lang)

        duration_s = round(time.monotonic() - started, 1)
        await run_store.update_run(
            run_id,
            status="completed",
            completed_at=datetime.now(tz=timezone.utc).isoformat(),
            duration_s=duration_s,
        )
        # Emit the terminal run.completed event — symmetric with the failure
        # path's run.failed below and with runs.py::_run_pipeline_impl.  Without
        # it the frontend debateStore never leaves 'running': the server closes
        # the SSE stream once status flips to completed, EventSource reads the
        # close as an error, auto-reconnects, the server immediately closes
        # again (already completed) → repeat → 8 errors → the catastrophic
        # "请检查后端服务" banner fires even though the verdict already arrived.
        await run_store.append_event(
            run_id,
            RunCompleted(
                event="run.completed",
                run_id=run_id,
                ticker=evidence_set.ticker,
                duration_s=duration_s,
                result_url=f"/api/runs/{run_id}",
            ),
        )
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
    ) as exc:
        # Task-boundary exception handler: mirrors runs.py::_run_pipeline_impl
        # (runs.py:302-325).  The set is broad-but-explicit — covers every
        # concrete failure mode that can escape run_debate: LLM API errors
        # (AgentRunError, UnexpectedModelBehavior, httpx.HTTPError), output
        # schema failures (ValidationError), data provider errors (ProviderError),
        # and standard Python/IO errors.  CancelledError is intentionally omitted
        # so server shutdown propagates cleanly.  Without this full set a failing
        # LLM agent would leave the run at status="running" and the SSE stream at
        # GET /api/runs/{id}/events would hang forever polling a run that will
        # never complete.
        logger.exception("Debate run %s failed", run_id)
        error_msg = str(exc)[:500] or type(exc).__name__
        await run_store.update_run(
            run_id,
            status="failed",
            completed_at=datetime.now(tz=timezone.utc).isoformat(),
            duration_s=round(time.monotonic() - started, 1),
            error=error_msg,
        )
        await run_store.append_event(
            run_id,
            RunFailed(event="run.failed", run_id=run_id, error=error_msg),
        )
    finally:
        request.app.state.run_tasks.pop(run_id, None)
