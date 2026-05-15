"""Backtest endpoint — runs BackTrader strategies, optionally with LLM strategy selection."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.requests import Request

router = APIRouter(prefix="/api/backtest", tags=["backtest"])

logger = logging.getLogger(__name__)


class BacktestRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=20)
    strategy: str = Field(default="sma_crossover")
    start: str = Field(default="2022-01-01", description="YYYY-MM-DD")
    end: str = Field(default="2024-01-01", description="YYYY-MM-DD")
    initial_cash: float = Field(default=100_000.0, gt=0)
    strategy_params: dict[str, float | int | str] = Field(default_factory=dict)
    auto: bool = Field(default=False, description="Use LLM-guided strategy selection")


@router.post("")
async def run_backtest(request: Request, body: BacktestRequest) -> dict[str, Any]:
    """Run a backtest on a ticker.

    If ``auto=true``, uses LLM-guided iterative strategy selection.
    If ``auto=false`` (default), uses the specified strategy (default: sma_crossover).

    Returns BacktestResult as JSON plus a pre-formatted summary string.
    """
    try:
        from finagent.engine.backtest.backtrader_adapter import BackTraderAdapter
        from finagent.engine.backtest.engine import BacktestConfig
    except ImportError as exc:
        raise HTTPException(
            status_code=501,
            detail=(
                "backtrader is not installed. Install it with: pip install 'finagent[backtest]'"
            ),
        ) from exc

    deps = request.app.state.deps
    ticker = body.ticker.upper()

    if body.auto:
        from finagent.engine.backtest.strategy_agent import run_strategy_selection

        try:
            result = await run_strategy_selection(
                settings=deps.settings,
                ticker=ticker,
                start_date=body.start,
                end_date=body.end,
                initial_cash=body.initial_cash,
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    else:
        config = BacktestConfig(
            ticker=ticker,
            start_date=body.start,
            end_date=body.end,
            strategy=body.strategy,
            strategy_params=body.strategy_params,
            initial_cash=body.initial_cash,
        )
        engine = BackTraderAdapter()
        try:
            result = await engine.run(config)
        except (ValueError, ImportError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        **result.model_dump(),
        "summary": result.format_summary(),
    }
