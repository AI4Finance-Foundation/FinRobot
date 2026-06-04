"""FastAPI route for multi-ticker DCF comparison.

``GET /api/compare?tickers=AAPL,MSFT`` assembles a side-by-side comparison from
each ticker's latest stored DCF artifact + live market fields. It runs **no**
pipeline (no LLM) — the expensive DCF generation happens via the async
batch-run path (``POST /api/coverage/groups/{id}/runs`` with pipeline_type=dcf),
so this read stays fast (H1 / ADR-0012). Tickers without a DCF artifact come
back flagged so the UI can prompt "run DCF first".
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from starlette.requests import Request

from finrobot.coverage.service import build_comparison
from finrobot.engine.compute.operators.compare import ComparisonResult

router = APIRouter(prefix="/api/compare", tags=["compare"])

_MIN_TICKERS = 2
_MAX_TICKERS = 10


@router.get("", response_model=ComparisonResult)
async def compare(request: Request, tickers: str) -> ComparisonResult:
    """Compare DCF valuation across 2–10 tickers (comma-separated)."""
    syms: list[str] = []
    for raw in tickers.split(","):
        sym = raw.strip().upper()
        if sym and sym not in syms:
            syms.append(sym)
    if not (_MIN_TICKERS <= len(syms) <= _MAX_TICKERS):
        raise HTTPException(
            status_code=400,
            detail=f"compare needs {_MIN_TICKERS}–{_MAX_TICKERS} distinct tickers, got {len(syms)}",
        )

    artifact_store = getattr(request.app.state, "artifact_store", None)
    deps = getattr(request.app.state, "deps", None)
    data_layer = getattr(deps, "data_layer", None) if deps is not None else None
    if artifact_store is None or data_layer is None:
        raise HTTPException(status_code=503, detail="Backend deps not initialized")

    return await build_comparison(syms, artifact_store=artifact_store, data_layer=data_layer)
