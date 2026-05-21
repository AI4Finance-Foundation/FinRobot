"""FastAPI routes for the artifact store.

Endpoints:
  GET    /api/artifacts                        — list/filter all artifacts
  GET    /api/artifacts/{id}                   — fetch full artifact
  DELETE /api/artifacts/{id}                   — remove artifact
  GET    /api/artifacts/{a_id}/diff/{b_id}     — field-level diff
  POST   /api/artifacts/{id}/view              — update last_viewed_at
  GET    /api/artifacts/by-ticker/{ticker}/timeline — timeline for a ticker
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from starlette.requests import Request

from finagent.artifact.diff import FieldDiff, diff_artifacts
from finagent.artifact.models import Artifact, ArtifactSummary, ArtifactType
from finagent.artifact.store import ArtifactStore
from finagent.engine.data.layer import DataLayer
from finagent.routes._artifact_signal import attach_signals

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


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
    limit: int = 100,
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
    limit: int = 50,
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
    return {"status": "deleted", "id": artifact_id}


@router.get("/{a_id}/diff/{b_id}", response_model=list[FieldDiff])
async def diff_two(a_id: str, b_id: str, request: Request) -> list[FieldDiff]:
    """Return field-level differences between two artifacts.

    Diffs the assumptions, outputs, compute_version, and inputs (excluding
    raw_data). Meta fields like id and created_at are skipped because they
    always differ.

    Numeric diffs include abs_change and pct_change for convenience.

    Args:
        a_id: The "before" artifact id.
        b_id: The "after" artifact id.

    Returns:
        List of FieldDiff, sorted by path.

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
    return diff_artifacts(a, b)


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
    await store.mark_viewed(artifact_id)
    return {"status": "ok", "id": artifact_id}
