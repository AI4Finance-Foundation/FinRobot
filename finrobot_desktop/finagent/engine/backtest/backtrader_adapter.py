"""BackTrader adapter for the backtest engine.

What this code does that raw LLM cannot: wraps BackTrader's synchronous,
callback-heavy API into a clean async interface with typed config/result.
Handles SMA crossover strategy (built-in), dynamic strategy loading via
module:ClassName, 4 analyzers (Sharpe, DrawDown, Returns, TradeAnalyzer),
and equity curve PNG generation — all deterministic computation.
"""

from __future__ import annotations

import asyncio
import base64
import functools
import importlib
import io
import logging
from typing import Any

from finagent.engine.backtest.engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
)

logger = logging.getLogger(__name__)

try:
    import matplotlib

    matplotlib.use("Agg")
except ImportError:
    pass


def _check_backtrader() -> None:
    """Raise ImportError with a helpful message if backtrader is not installed."""
    try:
        import backtrader  # noqa: F401
    except ImportError:
        raise ImportError(
            "backtrader is required for backtesting. "
            "Install it with: pip install 'finagent[backtest]'"
        ) from None


@functools.cache
def _get_sma_crossover() -> type:
    """Create and cache the built-in SMA crossover strategy class.

    Deferred to avoid importing backtrader at module load time.
    functools.cache is thread-safe under CPython's GIL.
    """
    import backtrader as bt

    class SMACrossOver(bt.Strategy):
        params = (
            ("fast", 10),
            ("slow", 30),
        )

        def __init__(self) -> None:
            sma_fast = bt.indicators.SMA(self.data.close, period=self.p.fast)
            sma_slow = bt.indicators.SMA(self.data.close, period=self.p.slow)
            self.crossover = bt.indicators.CrossOver(sma_fast, sma_slow)

        def next(self) -> None:
            if not self.position:
                if self.crossover > 0:
                    self.buy()
            elif self.crossover < 0:
                self.close()

    return SMACrossOver


class BackTraderAdapter(BacktestEngine):
    """BacktestEngine implementation using BackTrader."""

    async def run(self, config: BacktestConfig) -> BacktestResult:
        """Execute backtest using BackTrader in a thread pool."""
        _check_backtrader()
        return await asyncio.to_thread(self._run_sync, config)

    def _run_sync(self, config: BacktestConfig) -> BacktestResult:
        """Synchronous backtest execution."""
        import backtrader as bt

        # Validate SMA params before any I/O
        if config.strategy == "sma_crossover":
            fast = config.strategy_params.get("fast", 10)
            slow = config.strategy_params.get("slow", 30)
            if isinstance(fast, (int, float)) and isinstance(slow, (int, float)):
                if fast >= slow:
                    raise ValueError(
                        f"SMA crossover requires fast ({fast}) < slow ({slow}). "
                        f"Swap the values or adjust parameters."
                    )

        cerebro = bt.Cerebro()
        cerebro.broker.setcash(config.initial_cash)

        # Load price data via yfinance
        data = self._load_data(config)
        cerebro.adddata(data)

        # Add strategy
        strategy_cls = self._resolve_strategy(config.strategy)
        cerebro.addstrategy(strategy_cls, **config.strategy_params)

        # Add analyzers
        cerebro.addanalyzer(
            bt.analyzers.SharpeRatio,
            _name="sharpe",
            riskfreerate=config.risk_free_rate,
        )
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
        cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

        # Run
        initial_value = cerebro.broker.getvalue()
        results = cerebro.run()
        final_value = cerebro.broker.getvalue()
        strat = results[0]

        # Extract analyzer results
        warnings: list[str] = []
        sharpe = self._extract_sharpe(strat, warnings)
        max_dd = self._extract_drawdown(strat, warnings)
        total_trades, winning, losing = self._extract_trades(strat, warnings)

        # Generate equity curve chart
        chart_b64 = self._render_chart(cerebro, config, warnings)

        total_return = (final_value - initial_value) / initial_value

        # Financial assumption warnings
        warnings.append(
            f"Sharpe ratio assumes risk-free rate of {config.risk_free_rate:.1%}."
        )
        warnings.append(
            "Backtest assumes zero commission and zero slippage. "
            "Real trading returns will be lower."
        )

        return BacktestResult(
            initial_value=initial_value,
            final_value=final_value,
            total_return=total_return,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            total_trades=total_trades,
            winning_trades=winning,
            losing_trades=losing,
            chart_base64=chart_b64,
            warnings=warnings,
        )

    def _load_data(self, config: BacktestConfig) -> Any:
        """Load price data using yfinance via backtrader's feed."""
        import backtrader as bt
        import yfinance as yf

        df = yf.download(
            config.ticker,
            start=config.start_date,
            end=config.end_date,
            auto_adjust=True,
            progress=False,
        )
        if df.empty:
            raise ValueError(
                f"No price data available for {config.ticker} "
                f"between {config.start_date} and {config.end_date}"
            )

        # yfinance may return MultiIndex columns; flatten if needed
        if hasattr(df.columns, "levels") and len(df.columns.levels) > 1:
            df.columns = df.columns.droplevel(1)

        return bt.feeds.PandasData(dataname=df)

    def _resolve_strategy(self, strategy_name: str) -> type:
        """Resolve strategy name to a BackTrader Strategy class.

        Built-in: "sma_crossover"
        Custom: "module.path:ClassName"
        """
        import backtrader as bt

        if strategy_name == "sma_crossover":
            return _get_sma_crossover()

        if ":" in strategy_name:
            module_path, class_name = strategy_name.rsplit(":", 1)
            module = importlib.import_module(module_path)
            cls: type = getattr(module, class_name)
            if not issubclass(cls, bt.Strategy):
                raise ValueError(
                    f"{class_name} from {module_path} is not a bt.Strategy subclass"
                )
            return cls

        raise ValueError(
            f"Unknown strategy '{strategy_name}'. "
            "Use 'sma_crossover' or 'module:ClassName' format."
        )

    def _extract_sharpe(
        self, strat: Any, warnings: list[str]
    ) -> float | None:
        analysis = strat.analyzers.sharpe.get_analysis()
        ratio: float | None = analysis.get("sharperatio")
        if ratio is None:
            warnings.append("Insufficient data for Sharpe ratio calculation")
        return ratio

    def _extract_drawdown(
        self, strat: Any, warnings: list[str]
    ) -> float | None:
        analysis = strat.analyzers.drawdown.get_analysis()
        max_dd: float | None = analysis.get("max", {}).get("drawdown")
        if max_dd is not None:
            return -abs(max_dd) / 100  # convert to negative fraction
        return None

    def _extract_trades(
        self, strat: Any, warnings: list[str]
    ) -> tuple[int, int, int]:
        analysis = strat.analyzers.trades.get_analysis()
        total_info = analysis.get("total", {})
        total = total_info.get("closed", total_info.get("total", 0))
        if "closed" not in total_info and total > 0:
            warnings.append(
                "Trade count may include open positions at backtest end."
            )
        won = analysis.get("won", {}).get("total", 0)
        lost = analysis.get("lost", {}).get("total", 0)
        return total, won, lost

    def _render_chart(
        self, cerebro: Any, config: BacktestConfig, warnings: list[str]
    ) -> str | None:
        """Render equity curve to base64 PNG."""
        try:
            import matplotlib.pyplot as plt

            fig = cerebro.plot(
                style="candlestick", iplot=False, start=None, end=None
            )[0][0]
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
            plt.close(fig)
            buf.seek(0)
            return base64.b64encode(buf.read()).decode("ascii")
        except (ImportError, RuntimeError, OSError, ValueError, TypeError) as e:
            warnings.append(f"Chart generation failed: {e}")
            logger.warning("Chart render failed", exc_info=True)
            return None
