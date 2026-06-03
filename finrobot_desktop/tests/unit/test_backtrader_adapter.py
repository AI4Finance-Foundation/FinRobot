"""Tests for BackTrader adapter.

Tests strategy resolution, analyzer extraction, and the adapter interface
without hitting yfinance (mock data loading).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from finrobot.engine.backtest.backtrader_adapter import (
    BackTraderAdapter,
    _check_backtrader,
    _get_sma_crossover,
)
from finrobot.engine.backtest.engine import BacktestConfig

try:
    import backtrader as _bt

    class FullyInvestedStrategy(_bt.Strategy):  # type: ignore[misc]  # backtrader is untyped
        """Buy ~95% of equity once and hold (regression fixture for BUG-019).

        Resolved via this module's import path so the portfolio's daily-return
        series actually tracks the asset; the default 1-share sizer would leave
        ~99% in cash, making account-value returns a near-constant risk-free
        drag and the Sharpe meaningless.
        """

        def __init__(self) -> None:
            self.sizer = _bt.sizers.PercentSizer(percents=95)
            self._entered = False

        def next(self) -> None:
            if not self._entered:
                self.buy()
                self._entered = True

except ImportError:  # pragma: no cover - backtrader is a hard test dep
    FullyInvestedStrategy = None  # type: ignore[assignment,misc]


class TestCheckBacktrader:
    def test_available(self) -> None:
        _check_backtrader()  # should not raise — backtrader is installed

    def test_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import builtins

        real_import = builtins.__import__

        def mock_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if name == "backtrader":
                raise ImportError("mocked")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        with pytest.raises(ImportError, match="finrobot\\[backtest\\]"):
            _check_backtrader()


class TestSMAStrategy:
    def test_creates_bt_strategy(self) -> None:
        import backtrader as bt

        cls = _get_sma_crossover()
        assert issubclass(cls, bt.Strategy)

    def test_cached(self) -> None:
        cls1 = _get_sma_crossover()
        cls2 = _get_sma_crossover()
        assert cls1 is cls2


class TestResolveStrategy:
    def test_sma_crossover(self) -> None:
        import backtrader as bt

        adapter = BackTraderAdapter(MagicMock())
        cls = adapter._resolve_strategy("sma_crossover")
        assert issubclass(cls, bt.Strategy)

    def test_unknown_strategy_raises(self) -> None:
        adapter = BackTraderAdapter(MagicMock())
        with pytest.raises(ValueError, match="Unknown strategy"):
            adapter._resolve_strategy("nonexistent")

    def test_custom_strategy_bad_module(self) -> None:
        adapter = BackTraderAdapter(MagicMock())
        with pytest.raises((ModuleNotFoundError, ValueError)):
            adapter._resolve_strategy("nonexistent_module:MyStrategy")


class TestExtractAnalyzers:
    def test_extract_sharpe(self) -> None:
        adapter = BackTraderAdapter(MagicMock())
        strat = MagicMock()
        strat.analyzers.sharpe.get_analysis.return_value = {"sharperatio": 1.5}
        warnings: list[str] = []
        assert adapter._extract_sharpe(strat, warnings) == 1.5
        assert not warnings

    def test_extract_sharpe_none(self) -> None:
        adapter = BackTraderAdapter(MagicMock())
        strat = MagicMock()
        strat.analyzers.sharpe.get_analysis.return_value = {"sharperatio": None}
        warnings: list[str] = []
        assert adapter._extract_sharpe(strat, warnings) is None
        assert len(warnings) == 1

    def test_extract_drawdown(self) -> None:
        adapter = BackTraderAdapter(MagicMock())
        strat = MagicMock()
        strat.analyzers.drawdown.get_analysis.return_value = {"max": {"drawdown": 15.5}}
        warnings: list[str] = []
        result = adapter._extract_drawdown(strat, warnings)
        assert result == pytest.approx(-0.155)

    def test_extract_trades_closed(self) -> None:
        adapter = BackTraderAdapter(MagicMock())
        strat = MagicMock()
        strat.analyzers.trades.get_analysis.return_value = {
            "total": {"total": 22, "closed": 20},
            "won": {"total": 12},
            "lost": {"total": 8},
        }
        warnings: list[str] = []
        total, won, lost = adapter._extract_trades(strat, warnings)
        assert total == 20  # uses closed, not total
        assert won == 12
        assert lost == 8
        assert not any("open positions" in w for w in warnings)

    def test_extract_trades_fallback_to_total(self) -> None:
        """When 'closed' key is absent, falls back to 'total' with a warning."""
        adapter = BackTraderAdapter(MagicMock())
        strat = MagicMock()
        strat.analyzers.trades.get_analysis.return_value = {
            "total": {"total": 20},
            "won": {"total": 12},
            "lost": {"total": 8},
        }
        warnings: list[str] = []
        total, won, lost = adapter._extract_trades(strat, warnings)
        assert total == 20
        assert any("open positions" in w for w in warnings)

    def test_extract_trades_empty(self) -> None:
        adapter = BackTraderAdapter(MagicMock())
        strat = MagicMock()
        strat.analyzers.trades.get_analysis.return_value = {}
        warnings: list[str] = []
        total, won, lost = adapter._extract_trades(strat, warnings)
        assert total == 0
        assert won == 0
        assert lost == 0


class TestSMAValidation:
    def test_fast_gte_slow_raises(self) -> None:
        adapter = BackTraderAdapter(MagicMock())
        config = BacktestConfig(
            ticker="AAPL",
            start_date="2023-01-01",
            end_date="2024-01-01",
            strategy="sma_crossover",
            strategy_params={"fast": 50, "slow": 10},
        )
        with pytest.raises(ValueError, match="fast.*< slow"):
            adapter._run_sync(config)

    def test_fast_equals_slow_raises(self) -> None:
        adapter = BackTraderAdapter(MagicMock())
        config = BacktestConfig(
            ticker="AAPL",
            start_date="2023-01-01",
            end_date="2024-01-01",
            strategy="sma_crossover",
            strategy_params={"fast": 20, "slow": 20},
        )
        with pytest.raises(ValueError, match="fast.*< slow"):
            adapter._run_sync(config)


class TestLoadData:
    def _adapter_with_bars(self, bars: list) -> BackTraderAdapter:
        """Adapter whose injected DataLayer.fetch_price_range returns `bars`."""
        data_layer = MagicMock()
        data_layer.fetch_price_range = AsyncMock(return_value=bars)
        return BackTraderAdapter(data_layer)

    def test_empty_data_raises(self) -> None:
        adapter = self._adapter_with_bars([])
        config = BacktestConfig(ticker="FAKE", start_date="2023-01-01", end_date="2024-01-01")
        with pytest.raises(ValueError, match="No price data"):
            adapter._load_data(config)

    def test_provider_error_becomes_no_price_data(self) -> None:
        from finrobot.engine.data.interface import ProviderError

        data_layer = MagicMock()
        data_layer.fetch_price_range = AsyncMock(side_effect=ProviderError("all down"))
        adapter = BackTraderAdapter(data_layer)
        config = BacktestConfig(ticker="FAKE", start_date="2023-01-01", end_date="2024-01-01")
        with pytest.raises(ValueError, match="No price data"):
            adapter._load_data(config)

    def test_builds_feed_from_typed_bars(self) -> None:
        from datetime import date

        from finrobot.engine.data.normalize import PriceBar

        bars = [
            PriceBar(
                date=date(2023, 1, 3),
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=1_000_000.0,
            ),
            PriceBar(
                date=date(2023, 1, 4),
                open=101.0,
                high=103.0,
                low=100.0,
                close=102.5,
                volume=1_100_000.0,
            ),
        ]
        adapter = self._adapter_with_bars(bars)
        config = BacktestConfig(ticker="AAPL", start_date="2023-01-01", end_date="2023-02-01")
        feed = adapter._load_data(config)
        # backtrader PandasData feed built from the typed bars (not yfinance).
        assert feed is not None
        adapter._data_layer.fetch_price_range.assert_awaited_once_with(
            "AAPL", "2023-01-01", "2023-02-01"
        )


def _one_year_daily_bars(seed: int, mu: float = 0.0004, sigma: float = 0.012) -> list:
    """~1yr of realistic daily bars: geometric random walk with drift.

    A seeded GBM (≈10%/yr drift, ≈19%/yr vol) mimics a real equity's return
    distribution — deterministic per ``seed`` so the resulting Sharpe is
    reproducible. Deliberately NOT pure tiny noise: annualizing a near-zero-
    variance series produces absurd Sharpe magnitudes.
    """
    import math
    import random
    from datetime import date, timedelta

    from finrobot.engine.data.normalize import PriceBar

    rng = random.Random(seed)
    bars = []
    d = date(2023, 1, 2)
    price = 100.0
    while d < date(2024, 1, 2):
        # Skip weekends to mimic a trading calendar.
        if d.weekday() < 5:
            price *= math.exp(mu + sigma * rng.gauss(0.0, 1.0))
            bars.append(
                PriceBar(
                    date=d,
                    open=price,
                    high=price * 1.005,
                    low=price * 0.995,
                    close=price,
                    volume=1_000_000.0,
                )
            )
        d += timedelta(days=1)
    return bars


class TestSharpeOnDailyBars:
    """Regression for BUG-019: daily-timeframe annualized Sharpe.

    Before the fix, SharpeRatio used backtrader's default timeframe=Years,
    which resampled a ~1yr daily series to a single yearly return → Sharpe
    undefined → None → misleading "insufficient data" warning. The fix
    registers the analyzer with timeframe=Days, annualize=True, factor=252.
    """

    def test_sharpe_is_finite_on_one_year_daily(self) -> None:
        import math

        bars = _one_year_daily_bars(seed=42)
        assert len(bars) > 200  # ~252 trading days

        data_layer = MagicMock()
        data_layer.fetch_price_range = AsyncMock(return_value=bars)
        adapter = BackTraderAdapter(data_layer)
        # Skip the matplotlib equity-curve render: it is slow on a 1yr candlestick
        # and irrelevant to the Sharpe regression under test.
        adapter._render_chart = lambda *a, **k: None  # type: ignore[method-assign]
        # Resolve a fully-invested strategy via this module's import path so the
        # portfolio carries real exposure (see FullyInvestedStrategy docstring).
        config = BacktestConfig(
            ticker="SYNTH",
            start_date="2023-01-02",
            end_date="2024-01-02",
            strategy="tests.unit.test_backtrader_adapter:FullyInvestedStrategy",
        )

        result = adapter._run_sync(config)

        # The core BUG-019 assertion: a real, finite annualized Sharpe — not None.
        # With the old timeframe=Years default this was None on a 1yr window.
        assert result.sharpe_ratio is not None
        assert isinstance(result.sharpe_ratio, float)
        assert math.isfinite(result.sharpe_ratio)
        # Annualized daily Sharpe of a fully-invested ≈19%-vol series stays
        # within single digits; pure-noise / cash-drag artifacts blow past this.
        assert abs(result.sharpe_ratio) < 5
        # The misleading "insufficient data" warning must not appear.
        assert not any("insufficient" in w.lower() for w in result.warnings)
