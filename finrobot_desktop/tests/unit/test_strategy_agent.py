"""Tests for the LLM-driven strategy selection agent.

Verifies the iteration loop, best-result tracking, and early-stop logic
without hitting real LLM or BackTrader — both are fully mocked.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pydantic_ai.exceptions import ModelHTTPError

from finrobot.config import FinRobotSettings
from finrobot.engine.backtest.engine import BacktestConfig, BacktestResult
from finrobot.engine.backtest.strategy_agent import (
    _FALLBACK_WARNING,
    _NO_HOLDOUT_WARNING,
    IN_SAMPLE_FRACTION,
    MAX_ITERATIONS,
    _AdjustmentDecision,
    _selection_metric,
    _split_in_sample_oos,
    run_strategy_selection,
)


def _make_result(total_return: float, annualized_return: float | None = None) -> BacktestResult:
    """Helper to create a BacktestResult with a given return."""
    final = 100_000 * (1 + total_return)
    return BacktestResult(
        initial_value=100_000,
        final_value=final,
        total_return=total_return,
        annualized_return=annualized_return,
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
        """LLM stops after iter 1 -> 1 IS backtest + 1 OOS backtest reported."""
        settings = FinRobotSettings(model_name="test:test")

        config = _make_config()
        is_result = _make_result(0.15)
        oos_result = _make_result(0.04)  # held-out result is what gets returned
        decision = _AdjustmentDecision(should_continue=False, config=config)

        mock_config_run = _mock_agent_run(config)
        mock_adjust_run = _mock_agent_run(decision)
        # IS tuning run, then the final OOS holdout run.
        mock_engine_run = AsyncMock(side_effect=[is_result, oos_result])

        with (
            patch("finrobot.engine.backtest.strategy_agent.Agent") as mock_agent_cls,
            patch("finrobot.engine.backtest.strategy_agent.BackTraderAdapter") as mock_adapter_cls,
        ):
            # First Agent() call -> config agent, second -> adjustment agent
            agent_instances = [MagicMock(), MagicMock()]
            agent_instances[0].run = mock_config_run
            agent_instances[1].run = mock_adjust_run
            mock_agent_cls.side_effect = agent_instances

            mock_adapter_cls.return_value.run = mock_engine_run

            result = await run_strategy_selection(
                settings, "AAPL", "2023-01-01", "2024-01-01", MagicMock()
            )

        # The reported number is the out-of-sample holdout result, not the IS fit.
        assert result.total_return == pytest.approx(0.04)
        # One IS tuning run (early stop) + one OOS run.
        assert mock_engine_run.call_count == 2
        # Final result carries the IS/OOS validation note as the leading warning.
        assert "out-of-sample" in result.warnings[0]
        # IS tuning ran on the in-sample sub-range, OOS on the tail.
        is_config: BacktestConfig = mock_engine_run.call_args_list[0][0][0]
        oos_config: BacktestConfig = mock_engine_run.call_args_list[1][0][0]
        assert is_config.start_date == "2023-01-01"
        assert is_config.end_date < "2024-01-01"  # IS ends before the window end
        assert oos_config.start_date == is_config.end_date  # OOS picks up at boundary
        assert oos_config.end_date == "2024-01-01"

    @pytest.mark.asyncio
    async def test_full_three_iterations_then_oos(self) -> None:
        """All 3 IS tuning iterations run, then the winning params run on OOS.

        The best IS result is iteration 2 (params fast=8/slow=25); those params
        must be the ones carried into the single out-of-sample evaluation, whose
        result (not the IS fit) is returned.
        """
        settings = FinRobotSettings(model_name="test:test")

        configs = [
            _make_config(strategy_params={"fast": 10, "slow": 30}),
            _make_config(strategy_params={"fast": 8, "slow": 25}),
            _make_config(strategy_params={"fast": 12, "slow": 40}),
        ]
        # Three IS tuning results, then the OOS holdout result.
        is_results = [
            _make_result(0.10),
            _make_result(0.20),  # best IS -> its params go to OOS
            _make_result(0.05),
        ]
        oos_result = _make_result(0.06)

        # Two adjustment decisions (after iter 1 and iter 2)
        decisions = [
            _AdjustmentDecision(should_continue=True, config=configs[1]),
            _AdjustmentDecision(should_continue=True, config=configs[2]),
        ]

        mock_engine_run = AsyncMock(side_effect=[*is_results, oos_result])

        # Agent instances: 1 config_agent + 1 adjust_agent (hoisted before loop)
        config_agent_mock = MagicMock()
        config_agent_mock.run = _mock_agent_run(configs[0])

        # Single adjust_agent returns different decisions on successive calls
        adjust_agent_mock = MagicMock()
        decision_results = [MagicMock(output=d) for d in decisions]
        adjust_agent_mock.run = AsyncMock(side_effect=decision_results)

        with (
            patch("finrobot.engine.backtest.strategy_agent.Agent") as mock_agent_cls,
            patch("finrobot.engine.backtest.strategy_agent.BackTraderAdapter") as mock_adapter_cls,
        ):
            mock_agent_cls.side_effect = [
                config_agent_mock,
                adjust_agent_mock,
            ]
            mock_adapter_cls.return_value.run = mock_engine_run

            result = await run_strategy_selection(
                settings, "AAPL", "2023-01-01", "2024-01-01", MagicMock()
            )

        # Returned result is the OOS holdout run, not the best IS fit.
        assert result.total_return == pytest.approx(0.06)
        # 3 IS tuning runs + 1 OOS run.
        assert mock_engine_run.call_count == 4
        # OOS run used the best IS params (iteration 2), evaluated on the tail.
        oos_config: BacktestConfig = mock_engine_run.call_args_list[-1][0][0]
        assert oos_config.strategy_params == {"fast": 8, "slow": 25}
        assert oos_config.end_date == "2024-01-01"
        assert "out-of-sample" in result.warnings[0]

    @pytest.mark.asyncio
    async def test_best_is_params_drive_oos_not_reported_directly(self) -> None:
        """Best IS run (iter 1) selects params; OOS result is what is returned.

        The old behaviour reported the best in-sample number directly (overfit).
        Now the best IS run only *selects the params*; the reported figure is the
        out-of-sample evaluation, which is decoupled from the IS fit.
        """
        settings = FinRobotSettings(model_name="test:test")

        configs = [
            _make_config(strategy_params={"fast": 10, "slow": 30}),
            _make_config(strategy_params={"fast": 5, "slow": 15}),
        ]
        # First IS iteration is best, second is worse -> iter-1 params win.
        is_results = [
            _make_result(0.25),
            _make_result(-0.03),
        ]
        # OOS reality is far more modest than the 0.25 in-sample fit.
        oos_result = _make_result(0.02)
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

        mock_engine_run = AsyncMock(side_effect=[*is_results, oos_result])

        with (
            patch("finrobot.engine.backtest.strategy_agent.Agent") as mock_agent_cls,
            patch("finrobot.engine.backtest.strategy_agent.BackTraderAdapter") as mock_adapter_cls,
        ):
            mock_agent_cls.side_effect = [
                config_agent_mock,
                adjust_agent_mock,
            ]
            mock_adapter_cls.return_value.run = mock_engine_run

            result = await run_strategy_selection(
                settings, "AAPL", "2023-01-01", "2024-01-01", MagicMock()
            )

        # The 0.25 IS fit is NOT reported; the 0.02 OOS holdout is.
        assert result.total_return == pytest.approx(0.02)
        # OOS used the winning IS params (iteration 1: fast=10/slow=30).
        oos_config: BacktestConfig = mock_engine_run.call_args_list[-1][0][0]
        assert oos_config.strategy_params == {"fast": 10, "slow": 30}

    @pytest.mark.asyncio
    async def test_immutable_fields_enforced(self) -> None:
        """LLM cannot override ticker/dates/cash — they are forced back.

        Dates are pinned to the IS sub-range for tuning and the OOS tail for the
        final run; the LLM never widens the window. Strategy params still flow
        from the LLM.
        """
        settings = FinRobotSettings(model_name="test:test")

        # LLM tries to change the ticker and dates
        bad_config = BacktestConfig(
            ticker="MSFT",
            start_date="2020-01-01",
            end_date="2025-01-01",
            strategy="sma_crossover",
            strategy_params={"fast": 15, "slow": 45},
            initial_cash=500_000.0,
        )
        is_result = _make_result(0.10)
        oos_result = _make_result(0.03)

        config_agent_mock = MagicMock()
        config_agent_mock.run = _mock_agent_run(bad_config)

        # We need an adjust agent that stops
        decision = _AdjustmentDecision(should_continue=False, config=bad_config)
        adjust_agent_mock = MagicMock()
        adjust_agent_mock.run = _mock_agent_run(decision)

        mock_engine_run = AsyncMock(side_effect=[is_result, oos_result])

        with (
            patch("finrobot.engine.backtest.strategy_agent.Agent") as mock_agent_cls,
            patch("finrobot.engine.backtest.strategy_agent.BackTraderAdapter") as mock_adapter_cls,
        ):
            mock_agent_cls.side_effect = [config_agent_mock, adjust_agent_mock]
            mock_adapter_cls.return_value.run = mock_engine_run

            result = await run_strategy_selection(
                settings,
                "AAPL",
                "2023-01-01",
                "2024-01-01",
                MagicMock(),
                initial_cash=100_000.0,
            )

        # IS tuning run: caller's ticker/cash forced, dates pinned to IS sub-range.
        is_used: BacktestConfig = mock_engine_run.call_args_list[0][0][0]
        assert is_used.ticker == "AAPL"
        assert is_used.start_date == "2023-01-01"  # IS starts at the window start
        assert is_used.end_date < "2024-01-01"  # but ends before the window end
        assert is_used.initial_cash == 100_000.0
        # Strategy params still come from the LLM.
        assert is_used.strategy_params == {"fast": 15, "slow": 45}

        # OOS run never widens past the caller's window either.
        oos_used: BacktestConfig = mock_engine_run.call_args_list[1][0][0]
        assert oos_used.ticker == "AAPL"
        assert oos_used.end_date == "2024-01-01"
        assert oos_used.initial_cash == 100_000.0

        # Reported figure is the OOS holdout, not the IS fit.
        assert result.total_return == pytest.approx(0.03)

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_default_sma(self) -> None:
        """LLM auth/HTTP failure -> deterministic SMA backtest, not a crash.

        Uses ModelHTTPError (an AgentRunError subclass in pydantic-ai 1.73,
        modelling an auth/rate-limit failure) to confirm the except tuple
        catches real provider errors and degrades gracefully.
        """
        settings = FinRobotSettings(model_name="test:test")

        bt_result = _make_result(0.07)

        # config_agent.run blows up like an unauthorised / rate-limited provider.
        config_agent_mock = MagicMock()
        config_agent_mock.run = AsyncMock(
            side_effect=ModelHTTPError(status_code=401, model_name="test:test", body="no key")
        )
        # adjust_agent should never be reached on the fallback path.
        adjust_agent_mock = MagicMock()
        adjust_agent_mock.run = AsyncMock()

        mock_engine_run = AsyncMock(return_value=bt_result)

        with (
            patch("finrobot.engine.backtest.strategy_agent.Agent") as mock_agent_cls,
            patch("finrobot.engine.backtest.strategy_agent.BackTraderAdapter") as mock_adapter_cls,
        ):
            mock_agent_cls.side_effect = [config_agent_mock, adjust_agent_mock]
            mock_adapter_cls.return_value.run = mock_engine_run

            result = await run_strategy_selection(
                settings, "AAPL", "2023-01-01", "2024-01-01", MagicMock()
            )

        # Non-None deterministic result so downstream save_chart works.
        assert result is not None
        assert result.total_return == pytest.approx(0.07)
        # Degrade warning is present and leads the warning block.
        assert result.warnings[0] == _FALLBACK_WARNING
        assert _FALLBACK_WARNING in result.format_summary()
        # Exactly one deterministic backtest ran with the default SMA strategy.
        assert mock_engine_run.call_count == 1
        used_config: BacktestConfig = mock_engine_run.call_args[0][0]
        assert used_config.strategy == "sma_crossover"
        assert used_config.ticker == "AAPL"
        # No tuning was attempted after the initial-selection failure.
        adjust_agent_mock.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_short_window_skips_holdout_with_overfit_warning(self) -> None:
        """Window too short for an OOS tail -> single-window tune + overfit warn.

        With no holdout there is no second engine run, and the returned result
        is flagged with _NO_HOLDOUT_WARNING so the in-sample nature is explicit
        rather than silently shipped as a validated number.
        """
        settings = FinRobotSettings(model_name="test:test")

        # ~30-day window: the OOS tail (~9 days) is far below _MIN_OOS_DAYS,
        # so _split_in_sample_oos returns None and we tune on the whole window.
        config = _make_config(start_date="2023-01-01", end_date="2023-01-31")
        is_result = _make_result(0.12)
        decision = _AdjustmentDecision(should_continue=False, config=config)

        config_agent_mock = MagicMock()
        config_agent_mock.run = _mock_agent_run(config)
        adjust_agent_mock = MagicMock()
        adjust_agent_mock.run = _mock_agent_run(decision)

        mock_engine_run = AsyncMock(return_value=is_result)

        with (
            patch("finrobot.engine.backtest.strategy_agent.Agent") as mock_agent_cls,
            patch("finrobot.engine.backtest.strategy_agent.BackTraderAdapter") as mock_adapter_cls,
        ):
            mock_agent_cls.side_effect = [config_agent_mock, adjust_agent_mock]
            mock_adapter_cls.return_value.run = mock_engine_run

            result = await run_strategy_selection(
                settings, "AAPL", "2023-01-01", "2023-01-31", MagicMock()
            )

        # No OOS run was added (only the single IS tuning run).
        assert mock_engine_run.call_count == 1
        # Tuning ran on the FULL window (no IS/OOS split).
        used: BacktestConfig = mock_engine_run.call_args_list[0][0][0]
        assert used.start_date == "2023-01-01"
        assert used.end_date == "2023-01-31"
        # The result is honestly flagged as in-sample / likely overfit.
        assert result.warnings[0] == _NO_HOLDOUT_WARNING
        assert result.total_return == pytest.approx(0.12)


class TestSplitInSampleOos:
    """Unit tests for the IS/OOS date-window partitioning helper."""

    def test_one_year_window_splits_70_30(self) -> None:
        split = _split_in_sample_oos("2023-01-01", "2024-01-01")
        assert split is not None
        is_start, is_end, oos_start, oos_end = split
        # IS starts at the window start, OOS ends at the window end.
        assert is_start == "2023-01-01"
        assert oos_end == "2024-01-01"
        # Boundary is shared (no day lost) and lands near the 70% mark.
        assert is_end == oos_start
        # 365 days * 0.70 = 255.5 -> int 255 -> 2023-09-13.
        assert is_end == "2023-09-13"

    def test_boundary_respects_fraction(self) -> None:
        # The IS span should be ~IN_SAMPLE_FRACTION of the total span.
        split = _split_in_sample_oos("2020-01-01", "2022-01-01")
        assert split is not None
        is_start, is_end, _oos_start, oos_end = split
        is_span = (
            datetime.strptime(is_end, "%Y-%m-%d") - datetime.strptime(is_start, "%Y-%m-%d")
        ).days
        total_span = (
            datetime.strptime(oos_end, "%Y-%m-%d") - datetime.strptime(is_start, "%Y-%m-%d")
        ).days
        assert is_span / total_span == pytest.approx(IN_SAMPLE_FRACTION, abs=0.01)

    def test_short_window_returns_none(self) -> None:
        # A ~30-day window has too short an OOS tail for the SMA warm-up.
        assert _split_in_sample_oos("2023-01-01", "2023-01-31") is None

    def test_inverted_or_equal_window_returns_none(self) -> None:
        assert _split_in_sample_oos("2024-01-01", "2024-01-01") is None
        assert _split_in_sample_oos("2024-06-01", "2024-01-01") is None


class TestSelectionMetric:
    """The IS ranking metric prefers annualized_return, falls back to total."""

    def test_prefers_annualized_when_present(self) -> None:
        r = _make_result(total_return=0.50, annualized_return=0.12)
        assert _selection_metric(r) == pytest.approx(0.12)

    def test_falls_back_to_total_return_when_annualized_missing(self) -> None:
        r = _make_result(total_return=0.18, annualized_return=None)
        assert _selection_metric(r) == pytest.approx(0.18)


class TestMaxIterationsConstant:
    def test_max_iterations_is_three(self) -> None:
        assert MAX_ITERATIONS == 3
