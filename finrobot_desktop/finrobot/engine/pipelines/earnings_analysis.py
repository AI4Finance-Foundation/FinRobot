"""Earnings Analysis pipeline.

4 steps:
  1. earnings_data     — fetch + calculate EarningsResult (deterministic)
  2. financial_context — fetch financials for trend context
  3. earnings_analysis — LLM interprets beat/miss patterns
  4. forward_outlook   — LLM generates earnings outlook

What code does that LLM cannot:
  - Deterministic beat/miss/inline classification at ±2% threshold
  - Exact beat_rate computation over N quarters
  - Consecutive streak arithmetic
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import Agent

from finrobot.engine.compute.operators.earnings import calculate_earnings_surprises
from finrobot.engine.data.types import DataType
from finrobot.engine.deps import FinRobotDeps
from finrobot.engine.models.financial import EarningsResult, StepOutput
from finrobot.engine.pipelines.base import (
    Pipeline,
    PipelineStep,
    StructuredValidator,
    TextValidator,
)
from finrobot.engine.pipelines.validators import (
    ValidationResult,
    validate_has_fields,
    validate_is_non_empty,
)
from finrobot.engine.data.interface import ProviderError

logger = logging.getLogger(__name__)


async def _execute_earnings_data(
    agent: Agent[Any, Any],
    deps: FinRobotDeps,
    prompt: str,
    structured_context: dict[str, object],
    ticker: str,
    **_kwargs: object,
) -> StepOutput:
    """Fetch earnings history and compute surprise statistics."""
    try:
        earnings_result = await deps.data_layer.fetch(DataType.EARNINGS, ticker)
        history = earnings_result.data.get("earnings_history", [])
    except (ProviderError, ValueError, KeyError) as e:
        logger.warning(f"Could not fetch earnings data for {ticker}: {e}. Using empty history.")
        history = []

    calculated: EarningsResult = calculate_earnings_surprises(ticker, history)
    text = (
        f"Beat rate: {calculated.beat_rate:.0%}. "
        f"Avg EPS surprise: {calculated.avg_eps_surprise_pct:+.1f}%. "
        f"Avg revenue surprise: {calculated.avg_revenue_surprise_pct:+.1f}%. "
        f"Consecutive beats: {calculated.consecutive_beats}. "
        f"Quarters analyzed: {len(calculated.surprises)}."
    )
    return StepOutput(text=text, structured=calculated)


def _validate_earnings_result(result: EarningsResult) -> ValidationResult:
    if result.beat_rate < 0 or result.beat_rate > 1:
        return ValidationResult(passed=False, error=f"beat_rate {result.beat_rate} out of [0,1]")
    return ValidationResult(passed=True)


def create_earnings_analysis_pipeline(agents: dict[str, Agent]) -> Pipeline:
    """4-step earnings analysis pipeline factory."""
    from finrobot.artifact.builders import build_earnings_artifact

    return Pipeline(
        artifact_builder=build_earnings_artifact,
        steps=[
            PipelineStep(
                name="earnings_data",
                skill_section=None,
                agent=agents["data"],
                required_data=[],
                validator=StructuredValidator(_validate_earnings_result, validate_is_non_empty),
                executor=_execute_earnings_data,
                # Pure surprise-statistics compute, zero LLM calls; a fetch
                # miss degrades to empty history INSIDE the executor (and then
                # passes validation), so a validation failure here is always a
                # pure-compute fact a retry cannot change (BUG-059).
                deterministic=True,
            ),
            PipelineStep(
                name="financial_context",
                skill_section=None,
                agent=agents["data"],
                required_data=[DataType.FINANCIALS],
                validator=TextValidator(
                    lambda out: validate_has_fields(out, ["revenue", "ebitda"])
                ),
            ),
            PipelineStep(
                name="earnings_analysis",
                skill_section=None,
                agent=agents["analysis"],
                required_data=[],
                validator=TextValidator(validate_is_non_empty),
            ),
            PipelineStep(
                name="forward_outlook",
                skill_section=None,
                agent=agents["synthesis"],
                required_data=[],
                validator=TextValidator(validate_is_non_empty),
            ),
        ],
    )
