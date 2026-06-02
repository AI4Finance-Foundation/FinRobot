"""FastAPI routes for Coverage Desk — the user's research coverage universe.

Endpoints:
  GET    /api/coverage/groups                         — list groups (+ counts)
  POST   /api/coverage/groups                         — create a group
  GET    /api/coverage/groups/{id}                    — group + members
  PATCH  /api/coverage/groups/{id}                    — rename / re-describe
  DELETE /api/coverage/groups/{id}                    — delete a group
  POST   /api/coverage/groups/{id}/members            — add tickers (batch)
  DELETE /api/coverage/groups/{id}/members/{ticker}   — remove a ticker
  GET    /api/coverage/groups/{id}/overview           — Coverage Table payload

Orchestration lives in :mod:`finrobot.coverage.service`; this layer only wires
HTTP ↔ store/service and owns the short-TTL overview cache (M1). The list
endpoint seeds the State-D ``Studied Tickers`` group on first visit.
"""

from __future__ import annotations

import logging
import re
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
from finrobot.coverage.service import build_overview, ensure_system_group
from finrobot.coverage.sqlite_store import CoverageStore
from finrobot.engine.data.layer import DataLayer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/coverage", tags=["coverage"])

# Single backend source of truth for a coverage ticker symbol. MIRROR of
# ui/src/utils/ticker.ts TICKER_RE — keep the two in sync. 1–12 chars,
# upper-case A–Z / digits / '.' / '-' (BRK-B, BRK.B, RDS.A…). Stops junk like
# "苹果", "AAPL;MSFT", or over-long strings from being persisted and then
# fanned out to providers forever (BUG-053).
_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,12}$")


def _clean_tickers(raw: list[str]) -> list[str]:
    """Upper-case + dedupe valid symbols; raise ValueError listing any invalid."""
    cleaned: list[str] = []
    bad: list[str] = []
    seen: set[str] = set()
    for t in raw:
        s = t.strip().upper()
        if not s:
            continue
        if not _TICKER_RE.match(s):
            bad.append(t)
        elif s not in seen:
            seen.add(s)
            cleaned.append(s)
    if bad:
        raise ValueError(f"Invalid ticker symbol(s): {', '.join(bad)}")
    if not cleaned:
        raise ValueError("No valid tickers provided")
    return cleaned


# ── Request bodies ───────────────────────────────────────────────────────────


class CreateGroupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None


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
# Keyed by (group_id, fast) — the fast skeleton and the full table are distinct
# payloads, cached independently.
_OVERVIEW_CACHE: dict[tuple[str, bool], tuple[float, CoverageOverview]] = {}
_OVERVIEW_TTL_S = 60.0


def _invalidate(group_id: str) -> None:
    # Drop both phases — a membership/name edit invalidates skeleton and full.
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


# ── Overview (Coverage Table) ────────────────────────────────────────────────


@router.get("/groups/{group_id}/overview", response_model=CoverageOverview)
async def group_overview(
    group_id: str, request: Request, refresh: bool = False, fast: bool = False
) -> CoverageOverview:
    """Assembled Coverage Table for a group (60s L1 cache; ``refresh=true`` bypasses).

    Needs the data layer + artifact store; per-ticker fetch failures degrade
    individual rows (``partial=true``) rather than failing the request.

    ``fast=true`` returns the skeleton (research + run state only, no market
    fan-out) so the client paints the table instantly on cold start, then
    backfills with a full fetch. The two phases are cached separately.
    """
    store = _store(request)
    now_ts = time.time()
    key = (group_id, fast)
    if not refresh:
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
        fast=fast,
    )
    _OVERVIEW_CACHE[key] = (now_ts, overview)
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
