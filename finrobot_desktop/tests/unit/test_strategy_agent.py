"""Tests for the LLM-driven strategy selection agent.

Verifies the iteration loop, best-result tracking, and early-stop logic
without hitting real LLM or BackTrader — both are fully mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from finagent.config import FinAgentSettings
from finagent.engine.backtest.engine import BacktestConfig, BacktestResult
from finagent.engine.backtest.strategy_agent import (
    MAX_ITERATIONS,
    _AdjustmentDecision,
    run_strategy_selection,
)


def _make_result(total_return: float) -> BacktestResult:
    """Helper to create a BacktestResult with a given return."""
    final = 100_000 * (1 + total_return)
    return BacktestResult(
        initial_value=100_000,
        final_value=final,
        total_return=total_return,
        sharpe_ratio=1.0,
        max_drawdown=-0.05,
        total_trades=10,
        winning_trades=6,
        losing_trades=4,
    )


def _make_config(**overrides: object) -> BacktestConfig:
    base = {
        "ticker": "AAPL",
        "start_date": "2023-01-01",
        "end_date": "2024-01-01",
        "strategy": "sma_crossover",
        "strategy_params": {"fast": 10, "slow": 30},
        "initial_cash": 100_000.0,
    }
    base.update(overrides)
    return BacktestConfig(**base)  # type: ignore[arg-type]


def _mock_agent_run(output: object) -> AsyncMock:
    """Create an AsyncMock that behaves like Agent.run() returning .output."""
    result = MagicMock()
    result.output = output
    return AsyncMock(return_value=result)


class TestRunStrategySelection:
    """Tests for run_strategy_selection."""

    @pytest.mark.asyncio
    async def test_single_iteration_early_stop(self) -> None:
        """LLM says should_continue=False after first run -> 1 backtest."""
        settings = FinAgentSettings(model_name="test:test")

        config = _make_config()
        bt_result = _make_result(0.15)
        decision = _AdjustmentDecision(should_continue=False, config=config)

        mock_config_run = _mock_agent_run(config)
        mock_adjust_run = _mock_agent_run(decision)
        mock_engine_run = AsyncMock(return_value=bt_result)

        with (
            patch("finagent.engine.backtest.strategy_agent.Agent") as mock_agent_cls,
            patch("finagent.engine.backtest.strategy_agent.BackTraderAdapter") as mock_adapter_cls,
        ):
            # First Agent() call -> config agent, second -> adjustment agent
            agent_instances = [MagicMock(), MagicMock()]
            agent_instances[0].run = mock_config_run
            agent_instances[1].run = mock_adjust_run
            mock_agent_cls.side_effect = agent_instances

            mock_adapter_cls.return_value.run = mock_engine_run

            result = await run_strategy_selection(settings, "AAPL", "2023-01-01", "2024-01-01")

        assert result.total_return == pytest.approx(0.15)
        # Engine should run exactly once (early stop after iter 1)
        assert mock_engine_run.call_count == 1

    @pytest.mark.asyncio
    async def test_full_three_iterations(self) -> None:
        """LLM keeps adjusting for all 3 iterations."""
        settings = FinAgentSettings(model_name="test:test")

        configs = [
            _make_config(strategy_params={"fast": 10, "slow": 30}),
            _make_config(strategy_params={"fast": 8, "slow": 25}),
            _make_config(strategy_params={"fast": 12, "slow": 40}),
        ]
        results = [
            _make_result(0.10),
            _make_result(0.20),
            _make_result(0.05),
        ]

        # Two adjustment decisions (after iter 1 and iter 2)
        decisions = [
            _AdjustmentDecision(should_continue=True, config=configs[1]),
            _AdjustmentDecision(should_continue=True, config=configs[2]),
        ]

        mock_engine_run = AsyncMock(side_effect=results)

        # Agent instances: 1 config_agent + 1 adjust_agent (hoisted before loop)
        config_agent_mock = MagicMock()
        config_agent_mock.run = _mock_agent_run(configs[0])

        # Single adjust_agent returns different decisions on successive calls
        adjust_agent_mock = MagicMock()
        decision_results = [MagicMock(output=d) for d in decisions]
        adjust_agent_mock.run = AsyncMock(side_effect=decision_results)

        with (
            patch("finagent.engine.backtest.strategy_agent.Agent") as mock_agent_cls,
            patch("finagent.engine.backtest.strategy_agent.BackTraderAdapter") as mock_adapter_cls,
        ):
            mock_agent_cls.side_effect = [
                config_agent_mock,
                adjust_agent_mock,
            ]
            mock_adapter_cls.return_value.run = mock_engine_run

            result = await run_strategy_selection(settings, "AAPL", "2023-01-01", "2024-01-01")

        # Best is iteration 2 with 0.20 return
        assert result.total_return == pytest.approx(0.20)
        assert mock_engine_run.call_count == 3

    @pytest.mark.asyncio
    async def test_returns_best_across_iterations(self) -> None:
        """Best result is from iteration 1, not the last one."""
        settings = FinAgentSettings(model_name="test:test")

        configs = [
            _make_config(strategy_params={"fast": 10, "slow": 30}),
            _make_config(strategy_params={"fast": 5, "slow": 15}),
        ]
        # First iteration is best, second is worse
        results = [
            _make_result(0.25),
            _make_result(-0.03),
        ]
        decision1 = _AdjustmentDecision(should_continue=True, config=configs[1])
        decision2 = _AdjustmentDecision(should_continue=False, config=configs[1])

        config_agent_mock = MagicMock()
        config_agent_mock.run = _mock_agent_run(configs[0])

        # Single adjust_agent returns different decisions on successive calls
        adjust_agent_mock = MagicMock()
        adjust_agent_mock.run = AsyncMock(
            side_effect=[
                MagicMock(output=decision1),
                MagicMock(output=decision2),
            ]
        )

        mock_engine_run = AsyncMock(side_effect=results)

        with (
            patch("finagent.engine.backtest.strategy_agent.Agent") as mock_agent_cls,
            patch("finagent.engine.backtest.strategy_agent.BackTraderAdapter") as mock_adapter_cls,
        ):
            mock_agent_cls.side_effect = [
                config_agent_mock,
                adjust_agent_mock,
            ]
            mock_adapter_cls.return_value.run = mock_engine_run

            result = await run_strategy_selection(settings, "AAPL", "2023-01-01", "2024-01-01")

        # Best result is 0.25 from iteration 1
        assert result.total_return == pytest.approx(0.25)

    @pytest.mark.asyncio
    async def test_immutable_fields_enforced(self) -> None:
        """LLM cannot override ticker/dates/cash — they are forced back."""
        settings = FinAgentSettings(model_name="test:test")

        # LLM tries to change the ticker and dates
        bad_config = BacktestConfig(
            ticker="MSFT",
            start_date="2020-01-01",
            end_date="2025-01-01",
            strategy="sma_crossover",
            strategy_params={"fast": 15, "slow": 45},
            initial_cash=500_000.0,
        )
        bt_result = _make_result(0.10)

        config_agent_mock = MagicMock()
        config_agent_mock.run = _mock_agent_run(bad_config)

        # We need an adjust agent that stops
        decision = _AdjustmentDecision(should_continue=False, config=bad_config)
        adjust_agent_mock = MagicMock()
        adjust_agent_mock.run = _mock_agent_run(decision)

        mock_engine_run = AsyncMock(return_value=bt_result)

        with (
            patch("finagent.engine.backtest.strategy_agent.Agent") as mock_agent_cls,
            patch("finagent.engine.backtest.strategy_agent.BackTraderAdapter") as mock_adapter_cls,
        ):
            mock_agent_cls.side_effect = [config_agent_mock, adjust_agent_mock]
            mock_adapter_cls.return_value.run = mock_engine_run

            result = await run_strategy_selection(
                settings,
                "AAPL",
                "2023-01-01",
                "2024-01-01",
                initial_cash=100_000.0,
            )

        # Verify the engine was called with the CALLER's fields, not LLM's
        call_args = mock_engine_run.call_args
        used_config: BacktestConfig = call_args[0][0]
        assert used_config.ticker == "AAPL"
        assert used_config.start_date == "2023-01-01"
        assert used_config.end_date == "2024-01-01"
        assert used_config.initial_cash == 100_000.0
        # But strategy params should come from LLM
        assert used_config.strategy_params == {"fast": 15, "slow": 45}
        assert result.total_return == pytest.approx(0.10)


class TestMaxIterationsConstant:
    def test_max_iterations_is_three(self) -> None:
        assert MAX_ITERATIONS == 3
