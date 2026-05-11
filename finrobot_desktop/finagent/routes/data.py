from __future__ import annotations

from typing import Any

import pandas as pd

from fastapi import APIRouter, HTTPException
from starlette.requests import Request

from finagent.engine.compute.extractor import (
    extract_financial_data,
    extract_price_history,
)
from finagent.engine.compute.historical_extractor import extract_historical_from_yfinance
from finagent.engine.data.interface import ProviderError
from finagent.engine.data.types import DataType
from finagent.engine.models.financial import FinancialData, HistoricalMetrics

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


@router.get("/{ticker}/historical", response_model=HistoricalMetrics)
async def get_historical(ticker: str) -> HistoricalMetrics:
    """Multi-year historical financial metrics including cash flows."""
    try:
        metrics = await extract_historical_from_yfinance(ticker.upper())
    except (ValueError, ProviderError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return metrics


@router.get("/{ticker}/quarterly")
async def get_quarterly(ticker: str) -> dict[str, Any]:
    """Quarterly income statement + cash flow data."""
    try:
        result = await fetch_quarterly_data(ticker.upper())
    except (ValueError, ProviderError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return result


async def fetch_quarterly_data(ticker: str) -> dict[str, Any]:
    """Fetch quarterly financials from yfinance."""
    import asyncio

    import yfinance as yf

    def _fetch() -> dict[str, Any]:
        t = yf.Ticker(ticker)
        income = t.quarterly_income_stmt
        cashflow = t.quarterly_cashflow  # NOTE: attribute is 'quarterly_cashflow' NOT 'quarterly_cash_flow'

        if income is None or income.empty:
            raise ValueError(f"No quarterly data available for {ticker}")

        quarters = []
        for col in income.columns[:8]:  # Last 8 quarters
            year = col.year
            quarter = (col.month - 1) // 3 + 1
            quarter_label = f"{year}-Q{quarter}"

            revenue = _safe_get(income, col, ["Total Revenue", "Revenue"])
            op_income = _safe_get(income, col, ["Operating Income"])
            net_income = _safe_get(income, col, ["Net Income", "Net Income Common Stockholders"])

            op_cf = None
            if cashflow is not None and not cashflow.empty and col in cashflow.columns:
                op_cf = _safe_get(cashflow, col, [
                    "Operating Cash Flow",
                    "Cash Flow From Continuing Operating Activities",
                ])

            if revenue is not None:
                quarters.append({
                    "quarter": quarter_label,
                    "revenue": revenue,
                    "operating_income": op_income,
                    "net_income": net_income,
                    "operating_cash_flow": op_cf,
                })

        return {"ticker": ticker, "quarters": quarters}

    return await asyncio.to_thread(_fetch)


def _safe_get(df: pd.DataFrame, col: Any, row_names: list[str]) -> float | None:
    """Try multiple row names for a DataFrame column, return first found."""
    for name in row_names:
        if name in df.index:
            val = df.loc[name, col]
            if val is not None and not pd.isna(val):
                return float(val)
    return None


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
