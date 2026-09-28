"""Tests for backtest engine abstraction layer.

Verifies BacktestConfig validation, BacktestResult formatting,
and computed properties.
"""

from __future__ import annotations

import importlib.util

import pytest

from finrobot.engine.backtest.engine import BacktestConfig, BacktestResult

# Config/result tests below are pure logic and run anywhere. The A-share gate
# tests drive ``adapter.run()``, which calls ``_check_backtrader()`` first, so
# they need the optional ``[backtest]`` extra installed; skip just that class
# when it is absent rather than hard-failing.
_HAS_BACKTRADER = importlib.util.find_spec("backtrader") is not None


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

    def test_ticker_is_normalized(self) -> None:
        config = BacktestConfig(
            ticker=" brk.b ",
            start_date="2023-01-01",
            end_date="2024-01-01",
        )
        # Stripped + upper-cased, and the US share-class dot folded to the hyphen
        # form providers require (yfinance returns no data for "BRK.B").
        assert config.ticker == "BRK-B"

    @pytest.mark.parametrize("ticker", ["苹果", "AAPL;DROP", "$"])
    def test_invalid_ticker_rejected(self, ticker: str) -> None:
        with pytest.raises(ValueError, match="Invalid ticker"):
            BacktestConfig(
                ticker=ticker,
                start_date="2023-01-01",
                end_date="2024-01-01",
            )

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

    @pytest.mark.parametrize("initial_cash", [float("nan"), float("inf"), float("-inf")])
    def test_nonfinite_cash_rejected(self, initial_cash: float) -> None:
        with pytest.raises(ValueError, match="positive"):
            BacktestConfig(
                ticker="AAPL",
                start_date="2023-01-01",
                end_date="2024-01-01",
                initial_cash=initial_cash,
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

    @pytest.mark.parametrize("risk_free_rate", [-2.0, 2.0, float("nan"), float("inf")])
    def test_risk_free_rate_outside_contract_rejected(self, risk_free_rate: float) -> None:
        with pytest.raises(ValueError):
            BacktestConfig(
                ticker="AAPL",
                start_date="2023-01-01",
                end_date="2024-01-01",
                risk_free_rate=risk_free_rate,
            )


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
            annualized_return=0.11,
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
        # Cumulative and annualized returns are labelled on explicit, distinct
        # bases so the +20% total can't be confused with the annualized Sharpe.
        assert "Total Return (cumulative): +20.00%" in summary
        assert "Annualized Return: +11.00%" in summary

    def test_format_summary_annualized_return_omitted_when_none(self) -> None:
        result = BacktestResult(
            initial_value=100_000,
            final_value=120_000,
            total_return=0.20,
        )
        summary = result.format_summary()
        assert "Total Return (cumulative): +20.00%" in summary
        assert "Annualized Return" not in summary

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


class _NullDataLayer:
    """DataLayer stub — run() must reject A-shares BEFORE any data fetch."""

    async def fetch_price_range(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("data fetch must not run for a rejected ticker")

    async def close(self) -> None:  # pragma: no cover - never reached here
        return None


@pytest.mark.skipif(not _HAS_BACKTRADER, reason="backtrader [backtest] extra not installed")
class TestBacktestAShareRejection:
    """BUG-068: A-share / HK tickers are rejected at the backtest entry.

    The engine only models US-equity T+0 zero-friction execution; for CN/HK
    names (T+1, price limits, stamp duty, halts unmodeled) it must raise rather
    than emit an untrustworthy equity curve. The reject happens in run() before
    any provider I/O.
    """

    @pytest.mark.parametrize(
        "ticker",
        ["600519", "000001", "600519.SS", "000001.SZ", "0700.HK", "688981.SH"],
    )
    def test_a_share_and_hk_tickers_rejected(self, ticker: str) -> None:
        import asyncio

        from finrobot.engine.backtest.backtrader_adapter import BackTraderAdapter

        adapter = BackTraderAdapter(_NullDataLayer())  # type: ignore[arg-type]
        config = BacktestConfig(
            ticker=ticker,
            start_date="2023-01-01",
            end_date="2024-01-01",
        )
        with pytest.raises(ValueError, match="US-equity"):
            asyncio.run(adapter.run(config))

    @pytest.mark.parametrize("ticker", ["AAPL", "BRK.B", "BRK-B", "MSFT"])
    def test_us_equity_tickers_pass_the_gate(self, ticker: str) -> None:
        """US symbols clear the gate (proven by hitting the next stage's I/O)."""
        import asyncio

        from finrobot.engine.backtest.backtrader_adapter import BackTraderAdapter

        adapter = BackTraderAdapter(_NullDataLayer())  # type: ignore[arg-type]
        config = BacktestConfig(
            ticker=ticker,
            start_date="2023-01-01",
            end_date="2024-01-01",
        )
        # Passes the A-share gate, then trips the stub's AssertionError at the
        # first data fetch — i.e. it was NOT rejected up front.
        with pytest.raises(AssertionError, match="data fetch must not run"):
            asyncio.run(adapter.run(config))
