"""Tests for relative performance indexed return chart."""

import matplotlib.pyplot as plt

from finagent.engine.charts.base import ChartDataPoint, validate_png
from finagent.engine.charts.relative_performance import _create_figure, render


def _sample_data() -> ChartDataPoint:
    return ChartDataPoint(
        chart_type="relative_performance",
        title="AAPL vs SPY Relative Performance",
        data=[
            {"date": "2024-01-02", "ticker_return": 100.0, "benchmark_return": 100.0},
            {"date": "2024-02-01", "ticker_return": 105.2, "benchmark_return": 102.1},
            {"date": "2024-03-01", "ticker_return": 108.7, "benchmark_return": 104.5},
            {"date": "2024-04-01", "ticker_return": 103.1, "benchmark_return": 103.8},
            {"date": "2024-05-01", "ticker_return": 112.4, "benchmark_return": 106.2},
        ],
    )


def _three_series_data() -> ChartDataPoint:
    return ChartDataPoint(
        chart_type="relative_performance",
        title="AAPL vs SPY vs XLK",
        data=[
            {"date": "2024-01-02", "ticker_return": 100.0, "spy_return": 100.0, "xlk_return": 100.0},
            {"date": "2024-02-01", "ticker_return": 107.0, "spy_return": 102.5, "xlk_return": 104.0},
            {"date": "2024-03-01", "ticker_return": 110.3, "spy_return": 105.1, "xlk_return": 108.2},
        ],
    )


class TestRelativePerformanceChart:
    def test_renders_valid_png(self):
        assert validate_png(render(_sample_data()))

    def test_two_lines_for_ticker_and_benchmark(self):
        fig = _create_figure(_sample_data())
        ax = fig.axes[0]
        # 2 data lines + 1 reference line at 100
        assert len(ax.lines) == 3
        plt.close(fig)

    def test_reference_line_at_100(self):
        fig = _create_figure(_sample_data())
        ax = fig.axes[0]
        # The reference line is the last line added (axhline)
        ref_line = ax.lines[-1]
        ydata = ref_line.get_ydata()
        y0: float = ydata[0]  # type: ignore[assignment,index]
        y1: float = ydata[1]  # type: ignore[assignment,index]
        assert y0 == 100.0
        assert y1 == 100.0
        plt.close(fig)

    def test_legend_present(self):
        fig = _create_figure(_sample_data())
        ax = fig.axes[0]
        legend = ax.get_legend()
        assert legend is not None
        labels = [t.get_text() for t in legend.get_texts()]
        # Should have Benchmark, Ticker, and Base (100)
        assert "Benchmark" in labels
        assert "Ticker" in labels
        assert "Base (100)" in labels
        plt.close(fig)

    def test_ylabel(self):
        fig = _create_figure(_sample_data())
        ax = fig.axes[0]
        assert ax.get_ylabel() == "Indexed Return (Base=100)"
        plt.close(fig)

    def test_three_series(self):
        fig = _create_figure(_three_series_data())
        ax = fig.axes[0]
        # 3 data lines + 1 reference line
        assert len(ax.lines) == 4
        legend = ax.get_legend()
        assert legend is not None
        labels = [t.get_text() for t in legend.get_texts()]
        assert "Spy" in labels
        assert "Ticker" in labels
        assert "Xlk" in labels
        plt.close(fig)
