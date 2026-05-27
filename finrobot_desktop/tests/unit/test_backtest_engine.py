"""Tests for backtest engine abstraction layer.

Verifies BacktestConfig validation, BacktestResult formatting,
and computed properties.
"""

from __future__ import annotations

import pytest

from finrobot.engine.backtest.engine import BacktestConfig, BacktestResult


class TestBacktestConfig:
    def test_valid_config(self) -> None:
        config = BacktestConfig(
            ticker="AAPL",
            start_date="2023-01-01",
            end_date="2024-01-01",
            strategy="sma_crossover",
            strategy_params={"fast": 10, "slow": 30},
        )
        assert config.ticker == "AAPL"
        assert config.initial_cash == 100_000.0

    def test_invalid_date_format(self) -> None:
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            BacktestConfig(
                ticker="AAPL",
                start_date="01-01-2023",
                end_date="2024-01-01",
            )

    def test_negative_cash(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            BacktestConfig(
                ticker="AAPL",
                start_date="2023-01-01",
                end_date="2024-01-01",
                initial_cash=-1000,
            )

    def test_custom_strategy(self) -> None:
        config = BacktestConfig(
            ticker="MSFT",
            start_date="2023-01-01",
            end_date="2024-01-01",
            strategy="my_module:MyStrategy",
        )
        assert config.strategy == "my_module:MyStrategy"

    def test_start_after_end_raises(self) -> None:
        with pytest.raises(ValueError, match="must be before"):
            BacktestConfig(
                ticker="AAPL",
                start_date="2024-01-01",
                end_date="2023-01-01",
            )

    def test_start_equals_end_raises(self) -> None:
        with pytest.raises(ValueError, match="must be before"):
            BacktestConfig(
                ticker="AAPL",
                start_date="2024-01-01",
                end_date="2024-01-01",
            )

    def test_risk_free_rate_default(self) -> None:
        config = BacktestConfig(
            ticker="AAPL",
            start_date="2023-01-01",
            end_date="2024-01-01",
        )
        assert config.risk_free_rate == pytest.approx(0.04)

    def test_risk_free_rate_custom(self) -> None:
        config = BacktestConfig(
            ticker="AAPL",
            start_date="2023-01-01",
            end_date="2024-01-01",
            risk_free_rate=0.05,
        )
        assert config.risk_free_rate == pytest.approx(0.05)


class TestBacktestResult:
    def test_win_rate(self) -> None:
        result = BacktestResult(
            initial_value=100_000,
            final_value=115_000,
            total_return=0.15,
            total_trades=20,
            winning_trades=12,
            losing_trades=8,
        )
        assert result.win_rate == pytest.approx(0.6)

    def test_win_rate_no_trades(self) -> None:
        result = BacktestResult(
            initial_value=100_000,
            final_value=100_000,
            total_return=0.0,
        )
        assert result.win_rate is None

    def test_format_summary_basic(self) -> None:
        result = BacktestResult(
            initial_value=100_000,
            final_value=120_000,
            total_return=0.20,
            sharpe_ratio=1.5,
            max_drawdown=-0.08,
            total_trades=15,
            winning_trades=10,
            losing_trades=5,
        )
        summary = result.format_summary()
        assert "$100,000.00" in summary
        assert "$120,000.00" in summary
        assert "+20.00%" in summary
        assert "1.500" in summary
        assert "8.00%" in summary
        assert "10/5" in summary

    def test_format_summary_minimal(self) -> None:
        result = BacktestResult(
            initial_value=100_000,
            final_value=95_000,
            total_return=-0.05,
        )
        summary = result.format_summary()
        assert "-5.00%" in summary
        assert "Sharpe" not in summary
        assert "Trades" not in summary

    def test_format_summary_with_warnings(self) -> None:
        result = BacktestResult(
            initial_value=100_000,
            final_value=100_000,
            total_return=0.0,
            warnings=["Insufficient data for Sharpe ratio"],
        )
        summary = result.format_summary()
        assert "Warning:" in summary
        assert "Insufficient data" in summary
