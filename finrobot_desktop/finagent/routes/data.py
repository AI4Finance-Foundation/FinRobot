"""Data routes -- thin handlers that parse params, call services, return responses."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from starlette.requests import Request

from finagent.engine.compute.extractor import extract_financial_data
from finagent.engine.compute.historical_extractor import extract_historical_from_yfinance
from finagent.engine.data.interface import ProviderError
from finagent.engine.data.types import DataType
from finagent.engine.models.financial import FinancialData, HistoricalMetrics
from finagent.engine.services.market_data import (
    fetch_performance_data,
    fetch_price_history,
    fetch_quarterly_data,
)

router = APIRouter(prefix="/api/data", tags=["data"])


# MUST be before /{ticker}/ routes to avoid FastAPI matching ticker="performance"
@router.get("/performance")
async def get_performance(
    tickers: str = "AAPL",
    benchmark: str = "SPY",
    period: str = "1y",
) -> dict[str, Any]:
    """Multi-ticker normalized price performance."""
    try:
        result = await fetch_performance_data(
            tickers=tickers.split(","),
            benchmark=benchmark,
            period=period,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return result


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
async def get_price(ticker: str, period: str = "1y") -> dict[str, Any]:
    """Price data with configurable time period."""
    try:
        result = await fetch_price_history(ticker.upper(), period)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return result


@router.get("/{ticker}/historical", response_model=HistoricalMetrics)
async def get_historical(ticker: str) -> HistoricalMetrics:
    """Multi-year historical financial metrics including cash flows."""
    try:
        metrics = await extract_historical_from_yfinance(ticker.upper())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return metrics


@router.get("/{ticker}/quarterly")
async def get_quarterly(ticker: str) -> dict[str, Any]:
    """Quarterly income statement + cash flow data."""
    try:
        result = await fetch_quarterly_data(ticker.upper())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return result


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
