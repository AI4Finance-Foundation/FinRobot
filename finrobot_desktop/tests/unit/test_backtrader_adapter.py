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

# backtrader is the optional ``[backtest]`` extra. This module exercises the
# adapter that wraps it; when the extra is absent (a dev venv that did not
# ``pip install 'finrobot[backtest]'``) skip the whole module cleanly instead of
# hard-failing all of its tests. CI with the extra installed still runs them all.
pytest.importorskip("backtrader")

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

    def test_dynamic_loading_disabled_by_default(self) -> None:
        """BUG-063: with no whitelisted prefix, a ``module:ClassName`` string must
        be rejected BEFORE any import — no side-effecting import_module runs."""
        adapter = BackTraderAdapter(MagicMock())
        with pytest.raises(ValueError, match="Dynamic strategy loading.*disabled"):
            adapter._resolve_strategy("nonexistent_module:MyStrategy")

    def test_import_side_effect_module_never_imported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BUG-063 core: the arbitrary-import primitive is closed — for a
        non-whitelisted path importlib.import_module is never called, so a
        module's top-level side effects cannot be triggered from a strategy
        string (e.g. ``os:getcwd``)."""
        import finrobot.engine.backtest.backtrader_adapter as adapter_mod

        def _spy_import(name: str, *args: object, **kwargs: object) -> object:
            raise AssertionError(f"import_module must not run for {name!r}")

        monkeypatch.setattr(adapter_mod.importlib, "import_module", _spy_import)
        adapter = BackTraderAdapter(MagicMock())
        with pytest.raises(ValueError, match="Dynamic strategy loading.*disabled"):
            adapter._resolve_strategy("os:getcwd")

    def test_whitelisted_prefix_loads_custom_strategy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BUG-063: a custom Strategy IS loadable once its import-path prefix is
        whitelisted via FINROBOT_BACKTEST_STRATEGY_MODULE_PREFIXES."""
        if FullyInvestedStrategy is None:  # pragma: no cover - backtrader installed
            pytest.skip("backtrader not installed")
        import backtrader as bt

        module_path = FullyInvestedStrategy.__module__  # this test module's path
        prefix = module_path.split(".", 1)[0]
        monkeypatch.setenv("FINROBOT_BACKTEST_STRATEGY_MODULE_PREFIXES", prefix)

        adapter = BackTraderAdapter(MagicMock())
        cls = adapter._resolve_strategy(f"{module_path}:FullyInvestedStrategy")
        assert issubclass(cls, bt.Strategy)

    def test_whitelisted_prefix_missing_attr_raises_clean_value_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BUG-063: a whitelisted module but unknown attribute raises a friendly
        ValueError ('Unknown strategy'), not a bare AttributeError."""
        module_path = TestResolveStrategy.__module__
        prefix = module_path.split(".", 1)[0]
        monkeypatch.setenv("FINROBOT_BACKTEST_STRATEGY_MODULE_PREFIXES", prefix)
        adapter = BackTraderAdapter(MagicMock())
        with pytest.raises(ValueError, match="Unknown strategy: 'NoSuchClass'"):
            adapter._resolve_strategy(f"{module_path}:NoSuchClass")

    def test_whitelisted_prefix_non_strategy_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """BUG-063: the issubclass(bt.Strategy) check still holds — a whitelisted
        module whose attribute is not a Strategy is rejected."""
        module_path = TestResolveStrategy.__module__
        prefix = module_path.split(".", 1)[0]
        monkeypatch.setenv("FINROBOT_BACKTEST_STRATEGY_MODULE_PREFIXES", prefix)
        adapter = BackTraderAdapter(MagicMock())
        # ``MagicMock`` is an attribute of this module (imported) but not a Strategy.
        with pytest.raises(ValueError, match="not a bt.Strategy subclass"):
            adapter._resolve_strategy(f"{module_path}:MagicMock")


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
        assert not warnings

    def test_extract_drawdown_none_warns(self) -> None:
        """BUG-064: a missing drawdown must warn like its sibling extractors.

        A zero-trade backtest yields no 'max'/'drawdown', so max_dd is None;
        previously the warnings accumulator was carried but never appended to,
        leaving the result silently None while Sharpe warned. Now it mirrors
        _extract_sharpe and records why the metric is unavailable.
        """
        adapter = BackTraderAdapter(MagicMock())
        strat = MagicMock()
        strat.analyzers.drawdown.get_analysis.return_value = {}
        warnings: list[str] = []
        result = adapter._extract_drawdown(strat, warnings)
        assert result is None
        assert warnings == ["Insufficient data for max drawdown calculation"]

    def test_extract_returns(self) -> None:
        """BUG-040: the Returns analyzer's rnorm100 is read as an annualized fraction."""
        adapter = BackTraderAdapter(MagicMock())
        strat = MagicMock()
        # rnorm100 is a percent (e.g. 11.0 == 11%/yr); we surface a fraction so
        # it sits on the same basis as total_return.
        strat.analyzers.returns.get_analysis.return_value = {"rnorm100": 11.0}
        warnings: list[str] = []
        result = adapter._extract_returns(strat, warnings)
        assert result == pytest.approx(0.11)
        assert not warnings

    def test_extract_returns_none_warns(self) -> None:
        adapter = BackTraderAdapter(MagicMock())
        strat = MagicMock()
        strat.analyzers.returns.get_analysis.return_value = {}
        warnings: list[str] = []
        result = adapter._extract_returns(strat, warnings)
        assert result is None
        assert warnings == ["Insufficient data for annualized return calculation"]

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

    def test_sharpe_is_finite_on_one_year_daily(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import math

        bars = _one_year_daily_bars(seed=42)
        assert len(bars) > 200  # ~252 trading days

        # BUG-063: dynamic ``module:ClassName`` loading is off by default; this
        # regression fixture lives in the test module, so whitelist its prefix.
        monkeypatch.setenv(
            "FINROBOT_BACKTEST_STRATEGY_MODULE_PREFIXES",
            __name__.split(".", 1)[0],
        )

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
        # BUG-040: the Returns analyzer is now consumed, not dead — a real
        # annualized return is surfaced alongside the cumulative total_return.
        assert result.annualized_return is not None
        assert math.isfinite(result.annualized_return)


@pytest.mark.skipif(FullyInvestedStrategy is None, reason="backtrader not installed")
class TestRenderChartHeadless:
    """BUG-069: cerebro.plot must never pop a GUI window or leak figures.

    The module-level matplotlib.use("Agg") was a no-op when another import had
    already locked an interactive backend (macosx). _render_chart now forces the
    Agg backend right before plotting and closes *every* figure cerebro.plot
    returns (it returns list[list[Figure]]).
    """

    def test_render_uses_agg_backend(self):
        import matplotlib
        import matplotlib.pyplot as plt

        # Simulate the bug's preconditions: someone forced a non-Agg backend.
        # Use a backend matplotlib can always select headlessly so we can prove
        # _render_chart switches *away* from it to Agg.
        plt.switch_backend("template")
        assert not plt.get_backend().lower().startswith("agg")

        adapter = BackTraderAdapter(MagicMock())
        warnings: list[str] = []

        captured: dict[str, str] = {}

        def fake_plot(*_args, **_kwargs):
            captured["backend"] = matplotlib.get_backend()
            fig = plt.figure()
            return [[fig]]

        cerebro = MagicMock()
        cerebro.plot.side_effect = fake_plot

        config = BacktestConfig(ticker="AAPL", start_date="2023-01-02", end_date="2024-01-02")

        before_open = len(plt.get_fignums())
        result = adapter._render_chart(cerebro, config, warnings)

        # A PNG was produced and no warning was raised.
        assert result is not None
        assert isinstance(result, str)
        assert warnings == []
        # cerebro.plot ran on a headless Agg backend (no GUI window).
        assert captured["backend"].lower().startswith("agg")
        # No leaked figures: the one created during plotting was closed.
        assert len(plt.get_fignums()) == before_open

    def test_render_closes_all_figures_from_nested_list(self):
        """cerebro.plot can return several figures across nested lists; all of
        them must be closed, not just [0][0] (the old leak)."""
        import matplotlib.pyplot as plt

        plt.switch_backend("Agg")
        adapter = BackTraderAdapter(MagicMock())
        warnings: list[str] = []

        def fake_plot(*_args, **_kwargs):
            # Two data feeds -> two inner groups, three figures total.
            f1, f2, f3 = plt.figure(), plt.figure(), plt.figure()
            return [[f1, f2], [f3]]

        cerebro = MagicMock()
        cerebro.plot.side_effect = fake_plot

        config = BacktestConfig(ticker="AAPL", start_date="2023-01-02", end_date="2024-01-02")

        before = len(plt.get_fignums())
        result = adapter._render_chart(cerebro, config, warnings)

        assert result is not None
        # All three figures cerebro.plot created were closed.
        assert len(plt.get_fignums()) == before

    def test_render_failure_closes_figures_and_degrades(self):
        """If savefig blows up after plotting, leftover figures are still closed
        and the method degrades to None + a warning (no leak, no crash)."""
        import matplotlib.pyplot as plt

        plt.switch_backend("Agg")
        adapter = BackTraderAdapter(MagicMock())
        warnings: list[str] = []

        leaked_fig = {}

        def fake_plot(*_args, **_kwargs):
            fig = plt.figure()
            leaked_fig["fig"] = fig
            # Make savefig raise so we exercise the except path.
            fig.savefig = MagicMock(side_effect=RuntimeError("render boom"))
            return [[fig]]

        cerebro = MagicMock()
        cerebro.plot.side_effect = fake_plot

        config = BacktestConfig(ticker="AAPL", start_date="2023-01-02", end_date="2024-01-02")

        before = len(plt.get_fignums())
        result = adapter._render_chart(cerebro, config, warnings)

        assert result is None
        assert any("Chart generation failed" in w for w in warnings)
        # The figure opened during the failed render was closed (plt.close("all")).
        assert len(plt.get_fignums()) == before
