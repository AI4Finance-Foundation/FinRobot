"""Financial analysis endpoint — wraps the standalone analysis pipeline."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.requests import Request

from finagent.engine.data.interface import ProviderError

router = APIRouter(prefix="/api/analyze", tags=["analyze"])

logger = logging.getLogger(__name__)

# Kept in sync with finagent/engine/analysis/prompts.py::ANALYSIS_TYPES.
# A runtime check against the live set is performed inside the handler.
_KNOWN_TYPES = frozenset({"balance", "cashflow", "competitors", "income", "overview", "risk"})


class AnalyzeRequest(BaseModel):
    analysis_type: str = Field(
        min_length=1,
        description="One of: balance | cashflow | competitors | income | overview | risk",
    )


class AnalyzeResponse(BaseModel):
    ticker: str
    analysis_type: str
    result: str


@router.post("/{ticker}", response_model=AnalyzeResponse)
async def analyze_ticker(
    ticker: str,
    request: Request,
    body: AnalyzeRequest,
) -> AnalyzeResponse:
    """Run a standalone financial analysis for a ticker.

    ``analysis_type`` must be one of the types exposed by the analysis engine.
    Fetches financial data from the configured provider chain, builds a
    structured prompt, and returns the LLM-generated analysis text.
    """
    from finagent.engine.analysis.prompts import ANALYSIS_TYPES, run_analysis

    analysis_type = body.analysis_type.lower().strip()

    if analysis_type not in ANALYSIS_TYPES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown analysis_type '{analysis_type}'. Valid types: {sorted(ANALYSIS_TYPES)}"
            ),
        )

    deps = request.app.state.deps
    ticker_upper = ticker.upper()

    try:
        result = await run_analysis(
            data_layer=deps.data_layer,
            settings=deps.settings,
            ticker=ticker_upper,
            analysis_type=analysis_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except (RuntimeError, OSError) as exc:
        logger.exception("analyze_ticker failed for %s/%s", ticker_upper, analysis_type)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return AnalyzeResponse(
        ticker=ticker_upper,
        analysis_type=analysis_type,
        result=result,
    )
