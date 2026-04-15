"""Shared execute_fn factories for pipeline steps that fetch + extract financial data."""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent

from finagent.engine.compute.extractor import extract_financial_data
from finagent.engine.data.types import DataType
from finagent.engine.deps import FinAgentDeps
from finagent.engine.models.financial import StepOutput


async def execute_financial_data_step(
    agent: Agent[Any, Any],
    deps: FinAgentDeps,
    prompt: str,
    structured_context: dict[str, object],
    ticker: str,
) -> StepOutput:
    """Standard data-collection step: run agent + fetch financials/price + extract.

    Used by equity_research, dcf, lbo, comps pipelines.  Centralised here so
    changes to extraction logic propagate everywhere.
    """
    step_result = await agent.run(prompt, deps=deps)  # type: ignore[call-overload]
    financials_result = await deps.data_layer.fetch(DataType.FINANCIALS, ticker)
    price_result = await deps.data_layer.fetch(DataType.PRICE, ticker)
    financial_data = extract_financial_data(financials_result, price_result)
    return StepOutput(text=step_result.output, structured=financial_data)
