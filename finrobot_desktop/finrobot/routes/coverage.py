"""FastAPI routes for Coverage Desk — the user's research coverage universe.

Endpoints:
  GET    /api/coverage/groups                         — list groups (+ counts)
  POST   /api/coverage/groups                         — create a group
  GET    /api/coverage/groups/{id}                    — group + members
  PATCH  /api/coverage/groups/{id}                    — rename / re-describe
  DELETE /api/coverage/groups/{id}                    — delete a group
  POST   /api/coverage/groups/{id}/members            — add tickers (batch)
  DELETE /api/coverage/groups/{id}/members/{ticker}   — remove a ticker
  POST   /api/coverage/studied-tickers/members        — auto-add opened ticker
  GET    /api/coverage/groups/{id}/overview           — Coverage Table payload

Orchestration lives in :mod:`finrobot.coverage.service`; this layer only wires
HTTP ↔ store/service and owns the short-TTL overview cache (M1). The list
endpoint seeds the State-D ``Studied Tickers`` group on first visit.
"""

from __future__ import annotations

import logging
import time
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from starlette.requests import Request

from finrobot.artifact.store import ArtifactStore
from finrobot.coverage.models import (
    CoverageGroupDetail,
    CoverageGroupSummary,
    CoverageOverview,
)
from finrobot.coverage.service import (
    build_overview,
    ensure_studied_membership,
    ensure_system_group,
)
from finrobot.coverage.sqlite_store import CoverageStore
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.data.ticker import validate_ticker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/coverage", tags=["coverage"])


def _clean_tickers(raw: list[str]) -> list[str]:
    """Upper-case + dedupe valid symbols; raise ValueError listing any invalid.

    Per-symbol syntax is the shared :func:`validate_ticker` (the one backend
    source of truth); this wrapper adds the batch concerns: dedupe, skip
    blanks, and collect every bad symbol into one message.
    """
    cleaned: list[str] = []
    bad: list[str] = []
    seen: set[str] = set()
    for t in raw:
        if not t.strip():
            continue
        try:
            s = validate_ticker(t)
        except ValueError:
            bad.append(t)
            continue
        if s not in seen:
            seen.add(s)
            cleaned.append(s)
    if bad:
        raise ValueError(f"Invalid ticker symbol(s): {', '.join(bad)}")
    if not cleaned:
        raise ValueError("No valid tickers provided")
    return cleaned


def _clean_group_name(raw: str) -> str:
    name = raw.strip()
    if not name:
        raise ValueError("Coverage group name must not be blank")
    return name


# ── Request bodies ───────────────────────────────────────────────────────────


class CreateGroupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        return _clean_group_name(v)


class UpdateGroupRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None


class AddMembersRequest(BaseModel):
    tickers: list[str] = Field(min_length=1)
    note: str | None = None

    @field_validator("tickers")
    @classmethod
    def _validate(cls, v: list[str]) -> list[str]:
        return _clean_tickers(v)


class StudiedMemberRequest(BaseModel):
    """Auto-add one opened ticker to the default ``Studied Tickers`` workspace.

    Single ticker (not the batch ``AddMembersRequest``): this is the write side
    of "opening /stocks/:ticker enrols it", fired once per successful open.
    """

    ticker: str

    @field_validator("ticker")
    @classmethod
    def _validate(cls, v: str) -> str:
        return validate_ticker(v)


class BatchRunRequest(BaseModel):
    # Must be a pipeline-registry key (engine/pipelines/registry.py), NOT an
    # artifact type. "research" → equity research; the artifact it produces is
    # typed "equity_research", but the run key is "research". Defaulting to
    # "equity_research" here used to make every batch run skip with
    # "Invalid pipeline" while still returning 200 (BUG-049).
    tickers: list[str] = Field(min_length=1)
    pipeline_type: str = "research"
    language: Literal["en", "zh"] | None = None


class BatchRunItem(BaseModel):
    ticker: str
    run_id: str


class BatchRunResponse(BaseModel):
    group_id: str
    pipeline_type: str
    runs: list[BatchRunItem]
    skipped: list[dict[str, str]] = Field(default_factory=list)
    """Tickers that couldn't be started (bad symbol / unknown pipeline), each
    {ticker, reason} — the rest still launch."""


# ── Overview L1 cache (M1) ───────────────────────────────────────────────────
# The Coverage Table is the desktop's first screen — opened constantly. One
# overview = an N-ticker canonical fan-out; a short TTL absorbs refresh storms
# while staying live. Keyed by group_id; invalidated on any membership/name
# mutation so an edit is reflected immediately.
# Keyed by (group_id, cache_only) — the instant cache-only paint and the
# network-revalidated table are distinct payloads, cached independently.
_OVERVIEW_CACHE: dict[tuple[str, bool], tuple[float, CoverageOverview]] = {}
_OVERVIEW_TTL_S = 60.0


def _invalidate(group_id: str) -> None:
    # Drop both phases — a membership/name edit invalidates the cache-only paint
    # and the network table.
    _OVERVIEW_CACHE.pop((group_id, True), None)
    _OVERVIEW_CACHE.pop((group_id, False), None)


# ── Dependency accessors ─────────────────────────────────────────────────────


def _store(request: Request) -> CoverageStore:
    store: CoverageStore | None = getattr(request.app.state, "coverage_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Coverage store not initialised")
    return store


def _artifact_store(request: Request) -> ArtifactStore | None:
    return getattr(request.app.state, "artifact_store", None)


def _data_layer(request: Request) -> DataLayer | None:
    deps = getattr(request.app.state, "deps", None)
    return getattr(deps, "data_layer", None) if deps is not None else None


# ── Groups ───────────────────────────────────────────────────────────────────


@router.get("/groups", response_model=list[CoverageGroupSummary])
async def list_groups(request: Request) -> list[CoverageGroupSummary]:
    """List coverage groups with member counts.

    On first visit (no groups yet) seeds a ``Studied Tickers`` group from the
    artifact store so an existing user lands on their real research universe
    rather than an empty desk (State D). The seed is a one-time projection;
    once any group exists this never re-fires.
    """
    store = _store(request)
    artifact_store = _artifact_store(request)
    if artifact_store is not None:
        try:
            await ensure_system_group(store, artifact_store)
        except (RuntimeError, OSError, ValueError) as exc:
            # Seeding is best-effort onboarding — never block the group list.
            logger.warning("System coverage group seeding skipped: %s", exc)
    return await store.list_groups()


@router.post("/groups", response_model=CoverageGroupDetail, status_code=201)
async def create_group(request: Request, body: CreateGroupRequest) -> CoverageGroupDetail:
    store = _store(request)
    group = await store.create_group(body.name.strip(), body.description)
    detail = await store.get_group(group.id)
    assert detail is not None  # just created
    return detail


@router.get("/groups/{group_id}", response_model=CoverageGroupDetail)
async def get_group(group_id: str, request: Request) -> CoverageGroupDetail:
    group = await _store(request).get_group(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail=f"Coverage group not found: {group_id}")
    return group


@router.patch("/groups/{group_id}", response_model=CoverageGroupDetail)
async def update_group(
    group_id: str, request: Request, body: UpdateGroupRequest
) -> CoverageGroupDetail:
    updated = await _store(request).update_group(
        group_id,
        name=body.name.strip() if body.name else None,
        description=body.description,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Coverage group not found: {group_id}")
    _invalidate(group_id)
    return updated


@router.delete("/groups/{group_id}", status_code=204)
async def delete_group(group_id: str, request: Request) -> None:
    deleted = await _store(request).delete_group(group_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Coverage group not found: {group_id}")
    _invalidate(group_id)


# ── Members ──────────────────────────────────────────────────────────────────


@router.post("/groups/{group_id}/members", response_model=CoverageGroupDetail)
async def add_members(
    group_id: str, request: Request, body: AddMembersRequest
) -> CoverageGroupDetail:
    detail = await _store(request).add_members(group_id, body.tickers, note=body.note)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Coverage group not found: {group_id}")
    _invalidate(group_id)
    return detail


@router.delete("/groups/{group_id}/members/{ticker}", response_model=CoverageGroupDetail)
async def remove_member(group_id: str, ticker: str, request: Request) -> CoverageGroupDetail:
    store = _store(request)
    removed = await store.remove_member(group_id, ticker)
    if not removed:
        # Distinguish "no such group" from "ticker wasn't in it" for the client.
        if await store.get_group(group_id) is None:
            raise HTTPException(status_code=404, detail=f"Coverage group not found: {group_id}")
        raise HTTPException(
            status_code=404, detail=f"{ticker.upper()} not in coverage group {group_id}"
        )
    _invalidate(group_id)
    detail = await store.get_group(group_id)
    assert detail is not None  # group existed (remove succeeded)
    return detail


# ── Studied Tickers auto-add (search → workspace) ────────────────────────────


@router.post("/studied-tickers/members", response_model=CoverageGroupDetail)
async def add_studied_member(request: Request, body: StudiedMemberRequest) -> CoverageGroupDetail:
    """Enrol a ticker into the default ``Studied Tickers`` workspace.

    Idempotent find-or-create: opening ``/stocks/:ticker`` calls this so the
    name joins the default group (Coverage redesign §2). Re-opening is a no-op;
    a name the user removed re-enters on the next open. Never the batch path —
    one ticker, already validated.
    """
    detail = await ensure_studied_membership(_store(request), body.ticker)
    # A new member changes the studied group's overview — drop its cache so the
    # desk shows the freshly-opened card on next render.
    _invalidate(detail.id)
    return detail


# ── Overview (Coverage Table) ────────────────────────────────────────────────


@router.get("/groups/{group_id}/overview", response_model=CoverageOverview)
async def group_overview(
    group_id: str, request: Request, refresh: bool = False
) -> CoverageOverview:
    """Assembled Coverage Table for a group.

    Needs the data layer + artifact store; per-ticker fetch failures degrade
    individual rows (``partial=true``) rather than failing the request.

    Two modes, both 60s L1-cached under distinct keys (stale-while-revalidate):

    * ``refresh=false`` (default) — **instant first paint**: market cells read
      from the canonical cache (allow-stale), NO network. ~ms at any N (measured
      5ms/6t, 4ms/100t). Rows past their TTL carry ``market_stale=true``; cold
      rows leave market ``None``. This is what the desk opens with — no more
      waiting on the cold provider fan-out (6.6s/6t, >180s/100t).
    * ``refresh=true`` — **network revalidate**: bounded per-ticker fan-out
      repopulates the canonical cache and returns fresh numbers. The client
      fires this in the background after the instant paint, then swaps it in.
    """
    store = _store(request)
    now_ts = time.time()
    cache_only = not refresh
    key = (group_id, cache_only)
    cached = _OVERVIEW_CACHE.get(key)
    if cached and now_ts - cached[0] < _OVERVIEW_TTL_S:
        return cached[1]

    group = await store.get_group(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail=f"Coverage group not found: {group_id}")

    data_layer = _data_layer(request)
    artifact_store = _artifact_store(request)
    if data_layer is None or artifact_store is None:
        raise HTTPException(status_code=503, detail="Backend deps not initialized")

    overview = await build_overview(
        group,
        artifact_store=artifact_store,
        data_layer=data_layer,
        run_store=getattr(request.app.state, "run_store", None),
        cache_only=cache_only,
    )
    _OVERVIEW_CACHE[key] = (now_ts, overview)
    # A network revalidate just rewrote the canonical cache; drop the stale
    # cache-only L1 so the next instant paint re-reads the fresh snapshot
    # rather than serving a pre-revalidate copy for up to 60s.
    if refresh:
        _OVERVIEW_CACHE.pop((group_id, True), None)
    return overview


# ── Batch runs (M4) ──────────────────────────────────────────────────────────


@router.post("/groups/{group_id}/runs", response_model=BatchRunResponse)
async def batch_run(group_id: str, request: Request, body: BatchRunRequest) -> BatchRunResponse:
    """Kick off a pipeline run for each selected ticker in the group.

    Reuses the single-run machinery (``spawn_run`` → same concurrency cap +
    SSE), so the frontend tracks aggregate progress by connecting one SSE
    stream per returned ``run_id``. A bad ticker / pipeline lands in
    ``skipped`` instead of failing the whole batch. The overview's cache is
    invalidated so an in-flight / failed run shows on next render.
    """
    from finrobot.routes.runs import spawn_run

    store = _store(request)
    if await store.get_group(group_id) is None:
        raise HTTPException(status_code=404, detail=f"Coverage group not found: {group_id}")

    # Inbound rate-limit guard (BUG-043): a batch spawns one metered pipeline
    # per ticker. Charge the WHOLE batch atomically — the bucket is sized above
    # the largest legitimate batch, so a normal coverage fan-out passes, but a
    # runaway loop firing batch after batch is throttled. Charging the batch as
    # one unit (not per spawn_run) means we never admit half a batch. Orthogonal
    # to the concurrency cap (run_semaphore, BUG-017).
    limiter = getattr(request.app.state, "run_rate_limiter", None)
    if limiter is not None and not limiter.allow_runs(len(body.tickers)):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded — too many runs started. Retry shortly.",
        )

    runs: list[BatchRunItem] = []
    skipped: list[dict[str, str]] = []
    for ticker in body.tickers:
        try:
            record = await spawn_run(request, body.pipeline_type, ticker, language=body.language)
        except ValueError as exc:
            skipped.append({"ticker": ticker.strip().upper(), "reason": str(exc)})
            continue
        runs.append(BatchRunItem(ticker=record.ticker, run_id=record.run_id))

    _invalidate(group_id)
    return BatchRunResponse(
        group_id=group_id,
        pipeline_type=body.pipeline_type,
        runs=runs,
        skipped=skipped,
    )
