"""LLM-driven strategy selection and parameter tuning for backtests.

What this code does that raw LLM cannot: implements a closed-loop
optimisation cycle where each backtest iteration feeds typed, quantitative
results (Sharpe, drawdown, win-rate) back to the LLM so it can make an
informed parameter adjustment.  A raw LLM call can *suggest* parameters but
cannot *evaluate* them — this module couples LLM reasoning with deterministic
BackTrader execution.

Anti-overfitting discipline: the caller's date window is split into an
in-sample (IS) tuning sub-range and an out-of-sample (OOS) holdout tail.
The 3 LLM tuning iterations only ever see the IS window; the parameter set
with the best IS metric is then evaluated ONCE on the untouched OOS tail and
THAT result is returned.  This is what separates a validated strategy from a
curve-fit number: tuning and reporting never happen on the same data.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from pydantic import BaseModel, ValidationError
from pydantic_ai import Agent
from pydantic_ai.exceptions import AgentRunError

from finrobot.config import FinRobotSettings
from finrobot.engine.backtest.backtrader_adapter import BackTraderAdapter
from finrobot.engine.backtest.engine import BacktestConfig, BacktestResult
from finrobot.engine.data.layer import DataLayer

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 3

# Fraction of the caller's window used for in-sample tuning; the remaining tail
# is the out-of-sample holdout the final result is reported on. 70/30 is the
# conventional split for walk-forward-style validation.
IN_SAMPLE_FRACTION = 0.70

# Minimum number of calendar days the OOS tail must span. Below this the SMA
# slow period (default 30 *trading* days) cannot warm up and the OOS run yields
# zero trades, making the holdout result meaningless. 60 calendar days ≈ ~42
# trading days, enough headroom over the default slow=30 warm-up.
_MIN_OOS_DAYS = 60

# Surfaced at the top of the summary when the LLM is unreachable and we degrade
# to a single deterministic backtest instead of crashing.
_FALLBACK_WARNING = "LLM unavailable, fell back to default SMA strategy"

# Surfaced when the window is too short to carve out an honest OOS holdout, so
# we tune and report on the same window — an in-sample, likely-overfit number.
_NO_HOLDOUT_WARNING = (
    "Window too short for an out-of-sample holdout; parameters were tuned and "
    "evaluated on the same window. This result is in-sample and likely overfit "
    "— treat it as a fit, not a validated strategy."
)

# LLM-failure exceptions we degrade on. In pydantic-ai 1.73 both ModelAPIError
# and ModelHTTPError (auth / rate-limit / HTTP) subclass AgentRunError, so the
# base class covers all transport/provider failures; ValidationError (pydantic)
# is separate and fires when the model's structured output fails schema checks.
_LLM_FAILURES = (AgentRunError, ValidationError)

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


async def _deterministic_fallback(
    engine: BackTraderAdapter,
    ticker: str,
    start_date: str,
    end_date: str,
    initial_cash: float,
) -> BacktestResult:
    """Run one default SMA-crossover backtest when the LLM is unavailable.

    Honours the project's deterministic-fallback creed: a flaky / unauthorised /
    rate-limited LLM degrades to a real (non-None) backtest result with a
    clearly-labelled warning, rather than surfacing a bare traceback.
    """
    config = BacktestConfig(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        strategy="sma_crossover",
        initial_cash=initial_cash,
    )
    result = await engine.run(config)
    # Prepend so the degrade notice leads the summary's warning block.
    return result.model_copy(update={"warnings": [_FALLBACK_WARNING, *result.warnings]})


def _split_in_sample_oos(start_date: str, end_date: str) -> tuple[str, str, str, str] | None:
    """Partition [start_date, end_date] into IS tuning vs OOS holdout sub-ranges.

    Returns (is_start, is_end, oos_start, oos_end) where the IS range is the
    first ``IN_SAMPLE_FRACTION`` of the span and OOS is the remaining tail; the
    boundary day belongs to both edges (is_end == oos_start) so no day is lost.

    Returns ``None`` when the OOS tail would be shorter than ``_MIN_OOS_DAYS``
    (so the SMA slow period cannot warm up) — the caller then falls back to
    single-window tuning with an explicit overfit warning rather than reporting
    a holdout that produced zero trades.
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    total_days = (end - start).days
    if total_days <= 0:
        return None

    boundary = start + timedelta(days=int(total_days * IN_SAMPLE_FRACTION))
    oos_days = (end - boundary).days
    if oos_days < _MIN_OOS_DAYS:
        return None

    boundary_str = boundary.strftime("%Y-%m-%d")
    # Guard the degenerate edge where the boundary collapses onto start (IS would
    # be empty / start >= end fails BacktestConfig's date-order validator).
    if boundary_str <= start_date or boundary_str >= end_date:
        return None
    return start_date, boundary_str, boundary_str, end_date


def _selection_metric(result: BacktestResult) -> float:
    """In-sample ranking metric for choosing the best tuned parameter set.

    Prefers annualized_return (length-normalised, comparable across the IS
    sub-windows the LLM may implicitly explore) and falls back to raw
    total_return only when annualized is unavailable. Sharpe would be the ideal
    risk-adjusted choice but is blocked on the separate Sharpe-fix finding;
    annualized_return is the honest interim metric per the review.
    """
    if result.annualized_return is not None:
        return result.annualized_return
    return result.total_return


async def run_strategy_selection(
    settings: FinRobotSettings,
    ticker: str,
    start_date: str,
    end_date: str,
    data_layer: DataLayer,
    initial_cash: float = 100_000.0,
) -> BacktestResult:
    """Run LLM-guided strategy selection with in-sample/out-of-sample validation.

    1. Split the caller's window into an in-sample (IS) tuning sub-range (first
       ``IN_SAMPLE_FRACTION``) and an out-of-sample (OOS) holdout tail.
    2. Ask the LLM to pick an initial BacktestConfig; backtest it on IS only.
    3. Show IS results to the LLM and tune parameters (up to MAX_ITERATIONS),
       selecting the parameter set with the best IS ``_selection_metric``.
    4. Run the winning parameters ONCE on the untouched OOS tail and return that
       BacktestResult, annotated with the IS/OOS ranges it was validated over.

    The returned numbers therefore reflect generalisation on held-out data, not
    a curve fit. When the window is too short to carve out an honest OOS tail
    (see ``_MIN_OOS_DAYS``) the function degrades to single-window tuning and
    attaches ``_NO_HOLDOUT_WARNING`` so the in-sample nature is never hidden.
    """
    model = settings.create_model()
    engine = BackTraderAdapter(data_layer)

    split = _split_in_sample_oos(start_date, end_date)
    if split is not None:
        is_start, is_end, oos_start, oos_end = split
    else:
        # Window too short for a holdout: tune and report on the same window,
        # but never silently — the overfit warning rides on the final result.
        is_start, is_end, oos_start, oos_end = start_date, end_date, start_date, end_date

    # --- Initial config selection ---
    config_agent: Agent[None, BacktestConfig] = Agent(
        model,
        output_type=BacktestConfig,
        instructions=_SYSTEM_PROMPT,
        defer_model_check=True,
    )

    # Tuning happens on the in-sample window only — the LLM never sees OOS data.
    initial_prompt = (
        f"Select a backtest strategy for {ticker} "
        f"from {is_start} to {is_end} with initial cash ${initial_cash:,.0f}."
    )

    try:
        config_result = await config_agent.run(initial_prompt)
    except _LLM_FAILURES as e:
        logger.warning("LLM strategy selection failed (%s); using default SMA strategy.", e)
        # No tuning occurred, so there is nothing to overfit: report the single
        # deterministic run over the caller's full window.
        return await _deterministic_fallback(engine, ticker, start_date, end_date, initial_cash)
    config = config_result.output

    # Force the immutable fields onto the LLM-chosen config, pinning the dates to
    # the in-sample sub-range so every tuning backtest runs on IS only.
    config = config.model_copy(
        update={
            "ticker": ticker,
            "start_date": is_start,
            "end_date": is_end,
            "initial_cash": initial_cash,
        }
    )

    # Best IS run, ranked by _selection_metric, and the params that produced it.
    best_is_result: BacktestResult | None = None
    best_params: dict[str, float | int | str] = config.strategy_params
    best_strategy: str = config.strategy

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

        # Rank IS runs by the (length-normalised) selection metric, not raw
        # total_return, and remember the params that produced the best one.
        if best_is_result is None or _selection_metric(result) > _selection_metric(best_is_result):
            best_is_result = result
            best_params = config.strategy_params
            best_strategy = config.strategy

        # Last iteration — no adjustment needed.
        if iteration == MAX_ITERATIONS:
            break

        adjust_prompt = _ADJUSTMENT_TEMPLATE.format(
            iteration=iteration,
            max_iter=MAX_ITERATIONS,
            ticker=ticker,
            summary=result.format_summary(),
            best_return=best_is_result.total_return,
        )

        try:
            decision_result = await adjust_agent.run(adjust_prompt)
        except _LLM_FAILURES as e:
            # We already have a real IS backtest; the LLM just can't tune
            # further. Stop iterating and keep the best run rather than crash.
            logger.warning("LLM parameter tuning failed (%s); keeping best result so far.", e)
            break
        decision = decision_result.output

        if not decision.should_continue:
            logger.info("LLM decided no further adjustments needed.")
            break

        # Apply new config, forcing immutable fields and pinning IS dates.
        config = decision.config.model_copy(
            update={
                "ticker": ticker,
                "start_date": is_start,
                "end_date": is_end,
                "initial_cash": initial_cash,
            }
        )

    if best_is_result is None:
        raise RuntimeError("No successful backtest result after all iterations")

    if split is None:
        # No holdout was possible: the IS result IS the reported result, but it
        # was tuned and evaluated on the same window — flag it as overfit.
        return best_is_result.model_copy(
            update={"warnings": [_NO_HOLDOUT_WARNING, *best_is_result.warnings]}
        )

    # Honest report: run the winning params ONCE on the untouched OOS holdout
    # and return THAT result, annotated with the IS/OOS validation ranges.
    oos_config = BacktestConfig(
        ticker=ticker,
        start_date=oos_start,
        end_date=oos_end,
        strategy=best_strategy,
        strategy_params=best_params,
        initial_cash=initial_cash,
    )
    oos_result = await engine.run(oos_config)
    validation_note = (
        f"Parameters tuned on in-sample {is_start}..{is_end}; this result is "
        f"reported on the out-of-sample holdout {oos_start}..{oos_end}."
    )
    return oos_result.model_copy(update={"warnings": [validation_note, *oos_result.warnings]})
