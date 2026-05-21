"""Valuation aggregation endpoints (v5 §6.4 Football Field)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from starlette.requests import Request

from finagent.artifact.models import Artifact
from finagent.artifact.store import ArtifactStore
from finagent.engine.compute.valuation_aggregator import aggregate_valuation
from finagent.engine.data.interface import ProviderError
from finagent.engine.data.layer import DataLayer
from finagent.engine.data.types import DataType
from finagent.engine.models.financial import (
    DCFResult,
    DDMResult,
    LBOResult,
    PeerComps,
    ValuationAggregate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/valuation", tags=["valuation"])


@router.get("/aggregate/{ticker}", response_model=ValuationAggregate)
async def aggregate_for_ticker(ticker: str, request: Request) -> ValuationAggregate:
    """Build the Football Field payload for a ticker (v5 §6.4).

    Pulls the latest equity_research / dcf / ddm / lbo / comps artifacts the
    store has for the ticker and aggregates them via the pure aggregator.
    Missing artifact types simply drop out of the response with a warning.
    """
    store = _store(request)
    data_layer = _data_layer(request)

    ticker = ticker.upper()
    current_price = await _current_price(ticker, data_layer)

    dcf, peer_comps, ddm, lbo = await _gather_latest_results(store, ticker)
    shares = _shares_outstanding(dcf, lbo)
    as_of = datetime.now(tz=timezone.utc)

    return aggregate_valuation(
        ticker=ticker,
        current_price=current_price,
        dcf=dcf,
        peer_comps=peer_comps,
        ddm=ddm,
        lbo=lbo,
        shares_outstanding=shares,
        forward_eps=None,
        forward_ebitda=None,
        forward_fcf=None,
        historical_ev_ebitda_band=None,
        historical_p_fcf_band=None,
        as_of=as_of,
    )


def _store(request: Request) -> ArtifactStore:
    store: ArtifactStore | None = getattr(request.app.state, "artifact_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Artifact store not initialised")
    return store


def _data_layer(request: Request) -> DataLayer | None:
    deps = getattr(request.app.state, "deps", None)
    return getattr(deps, "data_layer", None) if deps is not None else None


async def _current_price(ticker: str, data_layer: DataLayer | None) -> float | None:
    if data_layer is None:
        return None
    try:
        result = await data_layer.fetch(DataType.PRICE, ticker)
    except (ProviderError, ValueError, KeyError) as exc:
        logger.info("current_price fetch failed for %s: %s", ticker, exc)
        return None
    raw = result.data.get("current_price") if isinstance(result.data, dict) else None
    try:
        price = float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None
    return price if price and price > 0 else None


async def _gather_latest_results(
    store: ArtifactStore, ticker: str
) -> tuple[DCFResult | None, PeerComps | None, DDMResult | None, LBOResult | None]:
    """Load the most recent artifact of each pipeline type and parse its result."""
    summaries = await store.list_by_ticker(ticker=ticker, include_archived=True, limit=200)
    latest_by_type: dict[str, Artifact] = {}
    for summary in summaries:
        if summary.type in latest_by_type:
            continue
        artifact = await store.get(summary.id)
        if artifact is not None:
            latest_by_type.setdefault(summary.type, artifact)

    dcf = _parse_dcf(latest_by_type)
    peer_comps = _parse_peers(latest_by_type)
    ddm = _parse_ddm(latest_by_type)
    lbo = _parse_lbo(latest_by_type)
    return dcf, peer_comps, ddm, lbo


def _parse_dcf(latest: dict[str, Artifact]) -> DCFResult | None:
    artifact = latest.get("dcf") or latest.get("equity_research") or latest.get("ic_memo")
    if artifact is None:
        return None
    structured = artifact.outputs.structured
    # equity_research nests DCF under financial_modeling; dcf pipeline stores at dcf_calc;
    # ic_memo stores at dcf_result. Try each in order.
    for key in ("dcf_calc", "financial_modeling", "dcf_result"):
        candidate = structured.get(key)
        if isinstance(candidate, dict):
            try:
                return DCFResult.model_validate(candidate)
            except (TypeError, ValueError) as exc:
                logger.debug("DCFResult parse failed at %s: %s", key, exc)
                continue
    return None


def _parse_peers(latest: dict[str, Artifact]) -> PeerComps | None:
    artifact = latest.get("comps") or latest.get("equity_research")
    if artifact is None:
        return None
    structured = artifact.outputs.structured
    for key in ("statistical_bench", "peer_analysis"):
        candidate = structured.get(key)
        if isinstance(candidate, dict):
            try:
                return PeerComps.model_validate(candidate)
            except (TypeError, ValueError) as exc:
                logger.debug("PeerComps parse failed at %s: %s", key, exc)
                continue
    return None


def _parse_ddm(latest: dict[str, Artifact]) -> DDMResult | None:
    artifact = latest.get("ddm")
    if artifact is None:
        return None
    candidate = artifact.outputs.structured.get("ddm_calc")
    if isinstance(candidate, dict):
        try:
            return DDMResult.model_validate(candidate)
        except (TypeError, ValueError) as exc:
            logger.debug("DDMResult parse failed: %s", exc)
    return None


def _parse_lbo(latest: dict[str, Artifact]) -> LBOResult | None:
    artifact = latest.get("lbo") or latest.get("ic_memo")
    if artifact is None:
        return None
    structured = artifact.outputs.structured
    for key in ("lbo_calculation", "lbo_result"):
        candidate = structured.get(key)
        if isinstance(candidate, dict):
            try:
                return LBOResult.model_validate(candidate)
            except (TypeError, ValueError) as exc:
                logger.debug("LBOResult parse failed at %s: %s", key, exc)
                continue
    return None


def _shares_outstanding(dcf: DCFResult | None, lbo: LBOResult | None) -> float | None:
    """Best-effort shares lookup from whichever artifact carries it.

    DCFInputs.shares_outstanding is the cleanest source. LBO doesn't carry it
    natively, so DCF wins. Future enhancement: pull from FinancialData snapshot.
    """
    if dcf is not None and dcf.inputs.shares_outstanding > 0:
        return dcf.inputs.shares_outstanding
    _ = lbo  # reserved for future shares-from-LBO fallback when LBOInputs grows the field
    return None
