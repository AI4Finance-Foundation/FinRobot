"""BackTrader adapter for the backtest engine.

What this code does that raw LLM cannot: wraps BackTrader's synchronous,
callback-heavy API into a clean async interface with typed config/result.
Handles SMA crossover strategy (built-in), dynamic strategy loading via
module:ClassName, 4 analyzers (Sharpe, DrawDown, Returns, TradeAnalyzer),
and equity curve PNG generation — all deterministic computation.

The SharpeRatio analyzer is configured for DAILY bars (timeframe=Days,
annualize=True, factor=252). backtrader's default timeframe=Years resamples
daily returns to yearly before computing Sharpe, which yields ~1 point (and
thus None) on a ~1yr window — see BUG-019. The explicit daily config produces
a proper annualized Sharpe consistent with the annual risk-free framing.
"""

from __future__ import annotations

import asyncio
import base64
import functools
import importlib
import io
import logging
from typing import TYPE_CHECKING, Any

from finrobot.engine.backtest.engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
)
from finrobot.engine.data.interface import ProviderError

if TYPE_CHECKING:
    from finrobot.engine.data.layer import DataLayer

logger = logging.getLogger(__name__)

try:
    import matplotlib

    matplotlib.use("Agg")
except ImportError:
    pass


def _reject_non_us_equity(ticker: str) -> None:
    """Reject A-share / HK tickers at the backtest entry (BUG-068).

    This engine only models US-equity T+0 zero-friction execution. For A-share
    / HK names none of the four core constraints are modeled — T+1 settlement,
    daily price limits (涨跌停), the 0.05% sell-side stamp duty (印花税), or
    trading halts (停牌) — so it would still emit a clean-looking but
    fundamentally untrustworthy equity curve. Per the "宁可说我需要核对、绝不
    编一个数字" creed we raise rather than warn: a warning gets skimmed past, a
    raise makes the fabricated curve physically impossible to obtain.
    """
    from finrobot.engine.data.ticker import is_us_equity_ticker

    if not is_us_equity_ticker(ticker):
        raise ValueError(
            "Backtest models US-equity T+0 zero-friction execution only; "
            "A-share/HK tickers (T+1, price limits, stamp duty, halts unmodeled) "
            f"are rejected to avoid producing untrustworthy curves. ticker={ticker!r}"
        )


def _check_backtrader() -> None:
    """Raise ImportError with a helpful message if backtrader is not installed."""
    try:
        import backtrader  # noqa: F401
    except ImportError:
        raise ImportError(
            "backtrader is required for backtesting. "
            "Install it with: pip install 'finrobot[backtest]'"
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
    """BacktestEngine implementation using BackTrader.

    Price bars come from the injected ``DataLayer`` (BUG-022) — the backtest no
    longer calls yfinance directly, so it shares the provider fallback chain,
    circuit-breaker and cache like every other data path.
    """

    def __init__(self, data_layer: DataLayer) -> None:
        self._data_layer = data_layer

    async def run(self, config: BacktestConfig) -> BacktestResult:
        """Execute backtest using BackTrader in a thread pool."""
        _check_backtrader()
        _reject_non_us_equity(config.ticker)
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
            timeframe=bt.TimeFrame.Days,
            compression=1,
            annualize=True,
            factor=252,
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
        annualized_return = self._extract_returns(strat, warnings)
        total_trades, winning, losing = self._extract_trades(strat, warnings)

        # Generate equity curve chart
        chart_b64 = self._render_chart(cerebro, config, warnings)

        total_return = (final_value - initial_value) / initial_value

        # Financial assumption warnings
        warnings.append(f"Sharpe ratio assumes risk-free rate of {config.risk_free_rate:.1%}.")
        warnings.append(
            "Backtest assumes zero commission and zero slippage. "
            "Real trading returns will be lower."
        )

        return BacktestResult(
            initial_value=initial_value,
            final_value=final_value,
            total_return=total_return,
            annualized_return=annualized_return,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            total_trades=total_trades,
            winning_trades=winning,
            losing_trades=losing,
            chart_base64=chart_b64,
            warnings=warnings,
        )

    def _load_data(self, config: BacktestConfig) -> Any:
        """Load split/dividend-adjusted price bars via the DataLayer (BUG-022).

        Runs inside ``_run_sync``, which executes in a worker thread (``run`` →
        ``asyncio.to_thread``), so this thread owns no event loop and ``asyncio.run``
        is the correct bridge to the async DataLayer. A provider failure or an empty
        window degrades to the same ``ValueError("No price data …")`` the caller
        already handles.
        """
        import backtrader as bt
        import pandas as pd

        try:
            bars = asyncio.run(
                self._data_layer.fetch_price_range(
                    config.ticker, config.start_date, config.end_date
                )
            )
        except ProviderError as e:
            raise ValueError(
                f"No price data available for {config.ticker} "
                f"between {config.start_date} and {config.end_date}: {e}"
            ) from e
        if not bars:
            raise ValueError(
                f"No price data available for {config.ticker} "
                f"between {config.start_date} and {config.end_date}"
            )

        # PriceBar carries an adjusted close always; O/H/L may be None for a
        # close-only feed — fall back to close so backtrader's PandasData has a
        # full OHLC even on degraded bars.
        df = pd.DataFrame(
            [
                {
                    "datetime": pd.Timestamp(b.date),
                    "open": b.open if b.open is not None else b.close,
                    "high": b.high if b.high is not None else b.close,
                    "low": b.low if b.low is not None else b.close,
                    "close": b.close,
                    "volume": b.volume if b.volume is not None else 0.0,
                }
                for b in bars
            ]
        ).set_index("datetime")

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
                raise ValueError(f"{class_name} from {module_path} is not a bt.Strategy subclass")
            return cls

        raise ValueError(
            f"Unknown strategy '{strategy_name}'. Use 'sma_crossover' or 'module:ClassName' format."
        )

    def _extract_sharpe(self, strat: Any, warnings: list[str]) -> float | None:
        analysis = strat.analyzers.sharpe.get_analysis()
        ratio: float | None = analysis.get("sharperatio")
        if ratio is None:
            # With daily timeframe + annualization (BUG-019), None means the
            # window is too short to have any daily returns (zero/one bar) or
            # returns had zero variance — not the old Years-resampling artifact.
            warnings.append(
                "Sharpe ratio unavailable: too few daily bars or zero-variance returns."
            )
        return ratio

    def _extract_drawdown(self, strat: Any, warnings: list[str]) -> float | None:
        analysis = strat.analyzers.drawdown.get_analysis()
        max_dd: float | None = analysis.get("max", {}).get("drawdown")
        if max_dd is not None:
            return -abs(max_dd) / 100  # convert to negative fraction
        warnings.append("Insufficient data for max drawdown calculation")
        return None

    def _extract_returns(self, strat: Any, warnings: list[str]) -> float | None:
        """Annualized normalized return (rnorm) from the Returns analyzer.

        backtrader's Returns analyzer exposes ``rnorm100`` as the annualized
        return expressed as a percent; divide by 100 to return a fraction so it
        sits on the same basis as ``total_return`` (also a fraction). This makes
        the cumulative-vs-annualized distinction explicit instead of leaving the
        analyzer wired but unread (BUG-040).
        """
        analysis = strat.analyzers.returns.get_analysis()
        rnorm100: float | None = analysis.get("rnorm100")
        if rnorm100 is None:
            warnings.append("Insufficient data for annualized return calculation")
            return None
        return rnorm100 / 100

    def _extract_trades(self, strat: Any, warnings: list[str]) -> tuple[int, int, int]:
        analysis = strat.analyzers.trades.get_analysis()
        total_info = analysis.get("total", {})
        total = total_info.get("closed", total_info.get("total", 0))
        if "closed" not in total_info and total > 0:
            warnings.append("Trade count may include open positions at backtest end.")
        won = analysis.get("won", {}).get("total", 0)
        lost = analysis.get("lost", {}).get("total", 0)
        return total, won, lost

    def _render_chart(
        self, cerebro: Any, config: BacktestConfig, warnings: list[str]
    ) -> str | None:
        """Render equity curve to base64 PNG."""
        try:
            import matplotlib.pyplot as plt

            fig = cerebro.plot(style="candlestick", iplot=False, start=None, end=None)[0][0]
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
            plt.close(fig)
            buf.seek(0)
            return base64.b64encode(buf.read()).decode("ascii")
        except (ImportError, RuntimeError, OSError, ValueError, TypeError) as e:
            warnings.append(f"Chart generation failed: {e}")
            logger.warning("Chart render failed", exc_info=True)
            return None
