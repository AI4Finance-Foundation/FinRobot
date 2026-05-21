"""Per-artifact export endpoints (v5 PR5 §12.2).

The existing ``GET /api/report/pdf?ticker=NVDA`` route only works for the
currently cached pipeline (i.e. the last run in this server process). v5
"我的研究" needs to download the PDF of any historic artifact by id, even
weeks later — which means the export route has to reconstruct the report
context from the persisted Artifact, not from the in-memory report_cache.

This module exposes ``POST /api/exports/pdf/{artifact_id}`` that:
  1. Loads the full Artifact by id (404 if missing).
  2. Picks the matching HTML renderer by artifact.type.
  3. Builds the context dict from artifact.outputs.structured.
  4. Renders HTML → PDF via the existing weasyprint pipeline (501 if
     weasyprint not installed — caller can still grab the source artifact).

We deliberately keep this small. The 1,555-line FinRobot
``professional_pdf_report.py`` carries its own formatting / charting layer
that overlaps with finagent's templates; a full port would be a separate
project. ADR-D records that decision.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Response
from starlette.requests import Request

from finagent.artifact.models import Artifact, ArtifactType
from finagent.artifact.store import ArtifactStore
from finagent.engine.reports.html_renderer import (
    render_comps_report,
    render_dcf_report,
    render_earnings_report,
    render_equity_report,
    render_ic_memo_report,
    render_lbo_report,
)
from finagent.engine.reports.pdf_renderer import render_pdf

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/exports", tags=["exports"])


# Map artifact_type → (renderer, context-builder). Keep this thin: each
# context-builder takes the full Artifact and returns the dict the matching
# renderer expects.

_Renderer = Callable[[dict[str, object]], str]
_ContextBuilder = Callable[[Artifact], dict[str, object]]


def _context_with(extra: dict[str, Any], artifact: Artifact) -> dict[str, object]:
    """Common context base: ticker + headline + any artifact-type extras."""
    return {
        "ticker": (artifact.ticker or "").upper(),
        "company_name": (artifact.ticker or "").upper(),
        "headline": artifact.outputs.summary_text or artifact.id,
        **extra,
    }


def _equity_research_context(artifact: Artifact) -> dict[str, object]:
    s = artifact.outputs.structured
    return _context_with(
        {
            "dcf_result": s.get("financial_modeling") or s.get("dcf_calc") or {},
            "peer_comps": s.get("peer_analysis") or {},
            "catalyst_analysis": s.get("catalyst_analysis") or {},
            "thesis": s.get("thesis") or {},
            "charts": {},
        },
        artifact,
    )


def _dcf_context(artifact: Artifact) -> dict[str, object]:
    return _context_with(
        {"dcf_result": artifact.outputs.structured.get("dcf_calc") or {}, "charts": {}},
        artifact,
    )


def _comps_context(artifact: Artifact) -> dict[str, object]:
    return _context_with(
        {
            "peer_comps": artifact.outputs.structured.get("statistical_bench") or {},
            "charts": {},
        },
        artifact,
    )


def _lbo_context(artifact: Artifact) -> dict[str, object]:
    return _context_with(
        {"lbo_result": artifact.outputs.structured.get("lbo_calculation") or {}},
        artifact,
    )


def _earnings_context(artifact: Artifact) -> dict[str, object]:
    return _context_with(
        {"earnings_result": artifact.outputs.structured.get("earnings_data") or {}},
        artifact,
    )


def _ic_memo_context(artifact: Artifact) -> dict[str, object]:
    return _context_with(
        {
            "ic_financials": artifact.outputs.structured.get("financial_analysis") or {},
            "steps": artifact.outputs.structured,
        },
        artifact,
    )


_RENDERERS: dict[ArtifactType, tuple[_Renderer, _ContextBuilder]] = {
    "equity_research": (render_equity_report, _equity_research_context),
    "dcf": (render_dcf_report, _dcf_context),
    "comps": (render_comps_report, _comps_context),
    "lbo": (render_lbo_report, _lbo_context),
    "earnings": (render_earnings_report, _earnings_context),
    "ic_memo": (render_ic_memo_report, _ic_memo_context),
}


@router.post("/pdf/{artifact_id}")
async def export_pdf(artifact_id: str, request: Request) -> Response:
    """Render the named artifact to PDF and stream it back to the caller.

    Per spec §12.2 the v5 "我的研究" section needs to download a PDF of any
    historic artifact — not just the latest cached pipeline.

    Returns:
        ``application/pdf`` bytes with a Content-Disposition matching the
        artifact id, or 404 if the id is unknown, 415 if the artifact type
        has no PDF template, 501 if weasyprint isn't installed.
    """
    store = _store(request)
    artifact = await store.get(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail=f"Artifact not found: {artifact_id}")

    entry = _RENDERERS.get(artifact.type)
    if entry is None:
        raise HTTPException(
            status_code=415,
            detail=(
                f"PDF export not yet wired for artifact type '{artifact.type}'. "
                "Supported: " + ", ".join(sorted(_RENDERERS.keys()))
            ),
        )
    renderer, builder = entry
    try:
        html = renderer(builder(artifact))
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        # Artifact missing fields the template expects (older schemas, partial
        # pipelines). Better to 422 than 500 — the caller can re-run the
        # pipeline to refresh the artifact.
        logger.info("PDF render context build failed for %s: %s", artifact_id, exc)
        raise HTTPException(
            status_code=422,
            detail=f"Artifact incomplete for PDF render: {exc}",
        ) from exc

    try:
        pdf_bytes = render_pdf(html)
    except RuntimeError as exc:
        logger.warning("PDF export failed (weasyprint missing): %s", exc)
        raise HTTPException(status_code=501, detail=str(exc)) from exc

    filename = f"{artifact_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _store(request: Request) -> ArtifactStore:
    store: ArtifactStore | None = getattr(request.app.state, "artifact_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Artifact store not initialised")
    return store
