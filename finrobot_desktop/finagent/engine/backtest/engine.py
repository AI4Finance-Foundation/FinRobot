"""Backtest engine abstraction layer.

What this code does that raw LLM cannot: defines a typed, engine-agnostic
interface for backtesting. BacktestConfig validates inputs (dates, cash > 0),
BacktestResult provides computed metrics (Sharpe, drawdown, win rate).
The abstract BacktestEngine decouples strategy execution from any specific
backtesting library (BackTrader, Zipline, vectorbt).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, field_validator


class BacktestConfig(BaseModel):
    """Configuration for a backtest run."""

    ticker: str
    start_date: str  # YYYY-MM-DD
    end_date: str  # YYYY-MM-DD
    strategy: str = "sma_crossover"  # built-in or "module:ClassName"
    strategy_params: dict[str, float | int | str] = {}
    initial_cash: float = 100_000.0

    @field_validator("start_date", "end_date")
    @classmethod
    def _validate_date_format(cls, v: str) -> str:
        from datetime import datetime

        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"Date must be YYYY-MM-DD format, got '{v}'") from None
        return v

    @field_validator("initial_cash")
    @classmethod
    def _validate_cash(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"initial_cash must be positive, got {v}")
        return v


class BacktestResult(BaseModel):
    """Results from a completed backtest."""

    initial_value: float
    final_value: float
    total_return: float
    sharpe_ratio: float | None = None
    max_drawdown: float | None = None
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    chart_base64: str | None = None  # PNG of equity curve
    warnings: list[str] = []

    @property
    def win_rate(self) -> float | None:
        """Win rate as a fraction (0-1). None if no trades."""
        if self.total_trades == 0:
            return None
        return self.winning_trades / self.total_trades

    def format_summary(self) -> str:
        """Human-readable summary of backtest results."""
        lines = [
            f"Initial Value:  ${self.initial_value:,.2f}",
            f"Final Value:    ${self.final_value:,.2f}",
            f"Total Return:   {self.total_return:+.2%}",
        ]
        if self.sharpe_ratio is not None:
            lines.append(f"Sharpe Ratio:   {self.sharpe_ratio:.3f}")
        if self.max_drawdown is not None:
            lines.append(f"Max Drawdown:   {self.max_drawdown:.2%}")
        if self.total_trades > 0:
            lines.append(f"Total Trades:   {self.total_trades}")
            lines.append(f"Win/Loss:       {self.winning_trades}/{self.losing_trades}")
            if self.win_rate is not None:
                lines.append(f"Win Rate:       {self.win_rate:.1%}")
        if self.warnings:
            lines.append("")
            for w in self.warnings:
                lines.append(f"  Warning: {w}")
        return "\n".join(lines)


class BacktestEngine(ABC):
    """Abstract base class for backtesting engines."""

    @abstractmethod
    async def run(self, config: BacktestConfig) -> BacktestResult:
        """Execute a backtest and return results."""
        ...
