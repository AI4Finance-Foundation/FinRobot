"""Backtest engine abstraction layer.

What this code does that raw LLM cannot: defines a typed, engine-agnostic
interface for backtesting. BacktestConfig validates inputs (dates, cash > 0),
BacktestResult provides computed metrics (Sharpe, drawdown, win rate).
The abstract BacktestEngine decouples strategy execution from any specific
backtesting library (BackTrader, Zipline, vectorbt).
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field, field_validator, model_validator

from finrobot.engine.data.ticker import validate_ticker


class BacktestConfig(BaseModel):
    """Configuration for a backtest run."""

    ticker: str
    start_date: str  # YYYY-MM-DD
    end_date: str  # YYYY-MM-DD
    strategy: str = "sma_crossover"  # built-in or "module:ClassName"
    strategy_params: dict[str, float | int | str] = Field(default_factory=dict)
    initial_cash: float = 100_000.0
    risk_free_rate: float = Field(
        default=0.04,
        ge=0,
        le=0.15,
        allow_inf_nan=False,
        description="Annual risk-free rate for Sharpe ratio calculation",
    )

    @field_validator("start_date", "end_date")
    @classmethod
    def _validate_date_format(cls, v: str) -> str:
        from datetime import datetime

        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"Date must be YYYY-MM-DD format, got '{v}'") from None
        return v

    @field_validator("ticker")
    @classmethod
    def _validate_ticker(cls, v: str) -> str:
        return validate_ticker(v)

    @field_validator("initial_cash")
    @classmethod
    def _validate_cash(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0:
            raise ValueError(f"initial_cash must be positive, got {v}")
        return v

    @model_validator(mode="after")
    def _check_date_order(self) -> BacktestConfig:
        if self.start_date >= self.end_date:
            raise ValueError(
                f"start_date ({self.start_date}) must be before end_date ({self.end_date})"
            )
        return self


class BacktestResult(BaseModel):
    """Results from a completed backtest."""

    initial_value: float
    final_value: float
    total_return: float  # cumulative return over the entire window
    annualized_return: float | None = None  # rnorm, comparable to the annualized Sharpe
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
            f"Total Return (cumulative): {self.total_return:+.2%}",
        ]
        if self.annualized_return is not None:
            lines.append(f"Annualized Return: {self.annualized_return:+.2%}")
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
