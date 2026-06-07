"""FastAPI routes for the artifact store.

Endpoints:
  GET    /api/artifacts                        — list/filter all artifacts
  GET    /api/artifacts/studied-tickers        — distinct tickers I've analysed
  GET    /api/artifacts/{id}                   — fetch full artifact
  DELETE /api/artifacts/{id}                   — remove artifact
  GET    /api/artifacts/{a_id}/diff/{b_id}     — field-level diff
  POST   /api/artifacts/{id}/view              — update last_viewed_at
  GET    /api/artifacts/by-ticker/{ticker}/timeline — timeline for a ticker
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from starlette.requests import Request

from finrobot.artifact.semantic_diff import SemanticDelta, build_semantic_delta
from finrobot.artifact.models import Artifact, ArtifactSummary, ArtifactType
from finrobot.artifact.store import ArtifactStore
from finrobot.engine.data.layer import DataLayer
from finrobot.routes._artifact_signal import attach_signals

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


class StudiedTicker(BaseModel):
    """One row in /api/artifacts/studied-tickers — a ticker the user has run analysis on."""

    ticker: str
    run_count: int
    latest_created_at: datetime
    latest_type: str
    latest_artifact_id: str
    latest_target_price: float | None
    latest_entry_price: float | None
    latest_signal: str | None
    types: list[str]


class StudiedTickersResponse(BaseModel):
    items: list[StudiedTicker]
    generated_at: datetime


def _store(request: Request) -> ArtifactStore:
    """Extract ArtifactStore from app state; raise 503 if not configured."""
    store: ArtifactStore | None = getattr(request.app.state, "artifact_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Artifact store not initialised")
    return store


def _data_layer(request: Request) -> DataLayer | None:
    """Best-effort DataLayer for lazy signal compute; None when unavailable."""
    deps = getattr(request.app.state, "deps", None)
    return getattr(deps, "data_layer", None) if deps is not None else None


@router.get("", response_model=list[ArtifactSummary])
async def list_artifacts(
    request: Request,
    ticker: str | None = None,
    type: ArtifactType | None = None,
    archived: bool = False,
    limit: int = Query(100, ge=1, le=500),
) -> list[ArtifactSummary]:
    """List artifact summaries, optionally filtered by ticker and/or type.

    Args:
        ticker: Filter by ticker symbol (case-insensitive). Omit for all tickers.
        type: Filter by analysis type (e.g. "dcf", "lbo"). Omit for all types.
        archived: Include archived (stale) artifacts. Default False.
        limit: Maximum results to return. Default 100.

    Returns:
        List of ArtifactSummary sorted by created_at descending.
    """
    store = _store(request)
    summaries = await store.list_by_ticker(
        ticker=ticker.upper() if ticker else None,
        type=type,
        include_archived=archived,
        limit=limit,
    )
    data_layer = _data_layer(request)
    if data_layer is not None:
        summaries = await attach_signals(summaries, data_layer)
    return summaries


@router.get("/by-ticker/{ticker}/timeline", response_model=list[ArtifactSummary])
async def ticker_timeline(
    ticker: str,
    request: Request,
    limit: int = Query(50, ge=1, le=1000),
) -> list[ArtifactSummary]:
    """Return all artifacts for a ticker, newest first.

    This endpoint exists as a convenience alias for
    ``GET /api/artifacts?ticker=AAPL&include_archived=true``.
    It shows the full history including archived entries so users can
    compare across time.

    Args:
        ticker: The ticker symbol (e.g. "AAPL").
        limit: Maximum results to return. Default 50.

    Returns:
        List of ArtifactSummary (all types) for the ticker, newest first.
    """
    store = _store(request)
    summaries = await store.list_by_ticker(
        ticker=ticker.upper(),
        include_archived=True,
        limit=limit,
    )
    data_layer = _data_layer(request)
    if data_layer is not None:
        summaries = await attach_signals(summaries, data_layer)
    return summaries


@router.get("/studied-tickers", response_model=StudiedTickersResponse)
async def studied_tickers(
    request: Request,
    include_archived: bool = False,
    limit: int = 100,
) -> StudiedTickersResponse:
    """Return every ticker the user has ever run analysis on, with metadata.

    Powers the /stocks landing's "我研究过的所有股票" table. Each row carries
    the latest run's verdict, entry/target prices, and a list of all pipeline
    types that have been run for that ticker (so the UI can show DCF / LBO /
    research chips).

    Sort: by latest_created_at descending — most recently touched on top.
    """
    store = _store(request)
    # Pull a generous sample. The store re-sorts by created_at desc so the
    # head naturally biases towards recently-touched tickers.
    summaries = await store.list_by_ticker(
        ticker=None,
        include_archived=include_archived,
        limit=500,
    )
    if not summaries:
        return StudiedTickersResponse(items=[], generated_at=datetime.now(tz=timezone.utc))

    # Attach live signals so the table can show hit/watching/failed lamp.
    data_layer = _data_layer(request)
    if data_layer is not None:
        summaries = await attach_signals(summaries, data_layer)

    # Group by ticker, latest entry wins for metadata.
    grouped: dict[str, list[ArtifactSummary]] = defaultdict(list)
    for s in summaries:
        if not s.ticker:
            continue
        grouped[s.ticker].append(s)

    items: list[StudiedTicker] = []
    for ticker_sym, group in grouped.items():
        latest = max(group, key=lambda s: s.created_at)
        types: list[str] = sorted({s.type for s in group})
        items.append(
            StudiedTicker(
                ticker=ticker_sym,
                run_count=len(group),
                latest_created_at=latest.created_at,
                latest_type=latest.type,
                latest_artifact_id=latest.id,
                latest_target_price=latest.target_price,
                latest_entry_price=latest.entry_price,
                latest_signal=latest.signal,
                types=types,
            )
        )

    items.sort(key=lambda x: x.latest_created_at, reverse=True)
    items = items[:limit]

    return StudiedTickersResponse(items=items, generated_at=datetime.now(tz=timezone.utc))


@router.get("/{artifact_id}", response_model=Artifact)
async def get_artifact(artifact_id: str, request: Request) -> Artifact:
    """Return the full Artifact including inputs, assumptions, outputs, and meta.

    Args:
        artifact_id: The artifact id (e.g. "art_2026-05-13T14:32:18_AAPL_dcf").

    Returns:
        The full Artifact.

    Raises:
        404: If the artifact is not found.
    """
    store = _store(request)
    artifact = await store.get(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail=f"Artifact not found: {artifact_id}")
    return artifact


@router.delete("/{artifact_id}")
async def delete_artifact(artifact_id: str, request: Request) -> dict[str, str]:
    """Permanently delete an artifact and remove it from the index.

    Args:
        artifact_id: The artifact id to delete.

    Returns:
        ``{"status": "deleted", "id": artifact_id}``

    Raises:
        404: If the artifact is not found.
    """
    store = _store(request)
    deleted = await store.delete(artifact_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Artifact not found: {artifact_id}")
    # Removing an artifact changes the landing hit-rate buckets and may drop a
    # ticker card off the recent-research strip — bust the dashboard TTL caches
    # so it reflects the deletion immediately (BUG-20260602-030). Local import
    # keeps the routes.dashboard ← routes.artifacts edge lazy/one-directional.
    from finrobot.routes.dashboard import invalidate_dashboard_caches

    invalidate_dashboard_caches()
    return {"status": "deleted", "id": artifact_id}


@router.get("/{a_id}/diff/{b_id}", response_model=SemanticDelta)
async def diff_two(a_id: str, b_id: str, request: Request) -> SemanticDelta:
    """Return an analyst-grade semantic delta between two artifact versions.

    ``a_id`` is the older/base version, ``b_id`` the newer/compare version. The
    response answers "why did the conclusion change" — rating / target / fair
    value moves, deterministic single-factor attribution of the DCF fair-value
    change, the driver assumptions that moved, and a comparability gate that
    suppresses deltas (or disables attribution) when the two versions aren't
    like-for-like (different formula / data source / earnings season). All
    numbers arrive pre-formatted with backend-owned units — see
    ``finrobot.artifact.semantic_diff`` and ``field_registry``.

    Args:
        a_id: The "before" (base) artifact id.
        b_id: The "after" (compare) artifact id.

    Returns:
        A SemanticDelta.

    Raises:
        404: If either artifact is not found.
    """
    store = _store(request)
    a = await store.get(a_id)
    if a is None:
        raise HTTPException(status_code=404, detail=f"Artifact not found: {a_id}")
    b = await store.get(b_id)
    if b is None:
        raise HTTPException(status_code=404, detail=f"Artifact not found: {b_id}")
    return build_semantic_delta(a, b)


@router.post("/{artifact_id}/view")
async def mark_viewed(artifact_id: str, request: Request) -> dict[str, str]:
    """Record that this artifact was viewed now.

    Updating the last_viewed_at timestamp prevents the artifact from being
    automatically archived by the stale-archive background task.

    Args:
        artifact_id: The artifact id to mark as viewed.

    Returns:
        ``{"status": "ok", "id": artifact_id}``

    Raises:
        404: If the artifact is not found.
    """
    store = _store(request)
    artifact = await store.get(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail=f"Artifact not found: {artifact_id}")
    was_archived = artifact.meta.archived
    await store.mark_viewed(artifact_id)
    # mark_viewed un-archives the artifact (store sets archived=False). When it
    # was archived, viewing it brings it back into the dashboard's
    # include_archived=False window, so the landing caches must drop or the
    # resurrected report stays invisible for up to 60s (BUG-20260602-030). We
    # gate on was_archived: the desktop shell fires /view on every report open,
    # and busting the cache on already-active artifacts would defeat it for no
    # behavioural change (the strip sorts by created_at, not last_viewed_at).
    if was_archived:
        from finrobot.routes.dashboard import invalidate_dashboard_caches

        invalidate_dashboard_caches()
    return {"status": "ok", "id": artifact_id}
