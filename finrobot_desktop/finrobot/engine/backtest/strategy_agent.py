"""LLM-driven strategy selection and parameter tuning for backtests.

What this code does that raw LLM cannot: implements a closed-loop
optimisation cycle where each backtest iteration feeds typed, quantitative
results (Sharpe, drawdown, win-rate) back to the LLM so it can make an
informed parameter adjustment.  A raw LLM call can *suggest* parameters but
cannot *evaluate* them — this module couples LLM reasoning with deterministic
BackTrader execution and keeps the best result across up to 3 iterations.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel
from pydantic_ai import Agent

from finrobot.config import FinRobotSettings
from finrobot.engine.backtest.backtrader_adapter import BackTraderAdapter
from finrobot.engine.backtest.engine import BacktestConfig, BacktestResult
from finrobot.engine.data.layer import DataLayer

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 3

_SYSTEM_PROMPT = """\
You are a quantitative strategy selector for backtesting.

Available strategies:
1. "sma_crossover" — Simple Moving Average crossover.
   Parameters:
     - fast (int): fast SMA period, typical range 5–50, default 10
     - slow (int): slow SMA period, typical range 20–200, default 30
   Constraint: fast < slow.

Given a ticker and date range, choose a strategy and parameters that are
likely to perform well.  Output a BacktestConfig with the ticker, dates,
strategy name, strategy_params dict, and initial_cash provided to you.
"""

_ADJUSTMENT_TEMPLATE = """\
Iteration {iteration}/{max_iter} complete for {ticker}.

Results:
{summary}

Best result so far: total_return={best_return:+.2%}

Based on these results, adjust the strategy parameters to try to improve
performance.  You may change the strategy or its parameters.
Return a new BacktestConfig.  Keep ticker, dates, and initial_cash the same.
"""


class _AdjustmentDecision(BaseModel):
    """Whether the LLM wants to continue tuning."""

    should_continue: bool
    config: BacktestConfig


async def run_strategy_selection(
    settings: FinRobotSettings,
    ticker: str,
    start_date: str,
    end_date: str,
    data_layer: DataLayer,
    initial_cash: float = 100_000.0,
) -> BacktestResult:
    """Run LLM-guided strategy selection with iterative parameter tuning.

    1. Ask the LLM to pick an initial BacktestConfig.
    2. Execute the backtest via BackTraderAdapter (price data via ``data_layer``).
    3. Show results to LLM and ask for adjustments (up to MAX_ITERATIONS).
    4. Return the BacktestResult with the highest total_return.
    """
    model = settings.create_model()
    engine = BackTraderAdapter(data_layer)

    # --- Initial config selection ---
    config_agent: Agent[None, BacktestConfig] = Agent(
        model,
        output_type=BacktestConfig,
        instructions=_SYSTEM_PROMPT,
        defer_model_check=True,
    )

    initial_prompt = (
        f"Select a backtest strategy for {ticker} "
        f"from {start_date} to {end_date} with initial cash ${initial_cash:,.0f}."
    )

    config_result = await config_agent.run(initial_prompt)
    config = config_result.output

    # Force the caller's immutable fields onto the LLM-chosen config.
    config = config.model_copy(
        update={
            "ticker": ticker,
            "start_date": start_date,
            "end_date": end_date,
            "initial_cash": initial_cash,
        }
    )

    best_result: BacktestResult | None = None

    # Pre-build the adjustment agent outside the loop to avoid
    # redundant Agent construction on each iteration.
    adjust_agent: Agent[None, _AdjustmentDecision] = Agent(
        model,
        output_type=_AdjustmentDecision,
        instructions=_SYSTEM_PROMPT,
        defer_model_check=True,
    )

    for iteration in range(1, MAX_ITERATIONS + 1):
        logger.info(
            "Backtest iteration %d/%d: strategy=%s params=%s",
            iteration,
            MAX_ITERATIONS,
            config.strategy,
            config.strategy_params,
        )

        result = await engine.run(config)

        if best_result is None or result.total_return > best_result.total_return:
            best_result = result

        # Last iteration — no adjustment needed.
        if iteration == MAX_ITERATIONS:
            break

        adjust_prompt = _ADJUSTMENT_TEMPLATE.format(
            iteration=iteration,
            max_iter=MAX_ITERATIONS,
            ticker=ticker,
            summary=result.format_summary(),
            best_return=best_result.total_return,
        )

        decision_result = await adjust_agent.run(adjust_prompt)
        decision = decision_result.output

        if not decision.should_continue:
            logger.info("LLM decided no further adjustments needed.")
            break

        # Apply new config, forcing immutable fields.
        config = decision.config.model_copy(
            update={
                "ticker": ticker,
                "start_date": start_date,
                "end_date": end_date,
                "initial_cash": initial_cash,
            }
        )

    if best_result is None:
        raise RuntimeError("No successful backtest result after all iterations")
    return best_result
