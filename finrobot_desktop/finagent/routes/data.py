from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from starlette.requests import Request

from finagent.engine.compute.extractor import (
    extract_financial_data,
    extract_price_history,
)
from finagent.engine.data.interface import ProviderError
from finagent.engine.data.types import DataType
from finagent.engine.models.financial import FinancialData

router = APIRouter(prefix="/api/data", tags=["data"])


@router.get("/{ticker}/financials", response_model=FinancialData)
async def get_financials(ticker: str, request: Request) -> FinancialData:
    data_layer = request.app.state.deps.data_layer
    try:
        financials = await data_layer.fetch(DataType.FINANCIALS, ticker.upper())
        price = await data_layer.fetch(DataType.PRICE, ticker.upper())
    except (ValueError, ProviderError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    extracted = extract_financial_data(financials, price)
    if financials.warnings:
        extracted.warnings = _dedupe([*extracted.warnings, *financials.warnings])
    if price.warnings:
        extracted.warnings = _dedupe([*extracted.warnings, *price.warnings])
    return extracted


@router.get("/{ticker}/price")
async def get_price(ticker: str, request: Request) -> dict[str, Any]:
    data_layer = request.app.state.deps.data_layer
    try:
        result = await data_layer.fetch(DataType.PRICE, ticker.upper())
    except (ValueError, ProviderError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    price = extract_price_history(result)
    payload = price.model_dump()
    payload["history"] = result.data.get("price_history", [])
    payload["data_source"] = result.provider
    payload["warnings"] = result.warnings
    return payload


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
