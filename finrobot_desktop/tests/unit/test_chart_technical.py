"""Tests for technical indicators chart (Bollinger Bands / RSI / MACD)."""

import math
import random

import matplotlib.pyplot as plt

from finagent.engine.charts.base import ChartDataPoint, validate_png
from finagent.engine.charts.technical_indicators import (
    _bollinger,
    _create_figure,
    _macd,
    _rsi,
    render,
)


def _sample_data() -> ChartDataPoint:
    random.seed(42)
    prices: list[dict[str, float | str | None | bool]] = []
    close = 150.0
    for i in range(60):
        change = random.gauss(0, 2)
        close += change
        prices.append(
            {
                "date": f"2024-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}",
                "close": round(close, 2),
                "high": round(close + abs(random.gauss(0, 1)), 2),
                "low": round(close - abs(random.gauss(0, 1)), 2),
            }
        )
    return ChartDataPoint(
        chart_type="technical_indicators",
        title="AAPL Technical",
        data=prices,
    )


class TestBollingerBands:
    def test_length_matches_input(self):
        closes = [float(i) for i in range(30)]
        upper, middle, lower = _bollinger(closes, window=20)
        assert len(upper) == len(middle) == len(lower) == 30

    def test_nan_before_window(self):
        closes = [float(i) for i in range(30)]
        upper, middle, lower = _bollinger(closes, window=20)
        # First 19 values should be NaN
        for i in range(19):
            assert math.isnan(upper[i])
            assert math.isnan(middle[i])
            assert math.isnan(lower[i])

    def test_valid_after_window(self):
        closes = [float(i) for i in range(30)]
        upper, middle, lower = _bollinger(closes, window=20)
        # From index 19 onward should be valid
        for i in range(19, 30):
            assert not math.isnan(upper[i])
            assert not math.isnan(middle[i])
            assert not math.isnan(lower[i])
            assert upper[i] > middle[i] > lower[i]

    def test_constant_prices_zero_bandwidth(self):
        """When all prices are constant, upper == middle == lower."""
        closes = [100.0] * 30
        upper, middle, lower = _bollinger(closes, window=20)
        for i in range(19, 30):
            assert upper[i] == middle[i] == lower[i] == 100.0


class TestRSI:
    def test_length_matches_input(self):
        closes = [float(100 + i) for i in range(30)]
        result = _rsi(closes, period=14)
        assert len(result) == 30

    def test_nan_before_period(self):
        closes = [float(100 + i) for i in range(30)]
        result = _rsi(closes, period=14)
        for i in range(14):
            assert math.isnan(result[i])

    def test_monotonic_increase_high_rsi(self):
        """Steadily rising prices should produce RSI close to 100."""
        closes = [100.0 + i for i in range(30)]
        result = _rsi(closes, period=14)
        # RSI at end should be very high (pure gains)
        assert result[-1] > 90.0

    def test_monotonic_decrease_low_rsi(self):
        """Steadily falling prices should produce RSI close to 0."""
        closes = [200.0 - i for i in range(30)]
        result = _rsi(closes, period=14)
        assert result[-1] < 10.0

    def test_rsi_in_range(self):
        """RSI values must be in [0, 100]."""
        random.seed(123)
        closes = [100.0 + random.gauss(0, 5) for _ in range(60)]
        result = _rsi(closes, period=14)
        for v in result:
            if not math.isnan(v):
                assert 0.0 <= v <= 100.0


class TestMACD:
    def test_length_matches_input(self):
        closes = [float(100 + i) for i in range(40)]
        macd_line, signal_line, histogram = _macd(closes)
        assert len(macd_line) == len(signal_line) == len(histogram) == 40

    def test_histogram_is_macd_minus_signal(self):
        random.seed(99)
        closes = [100.0 + random.gauss(0, 3) for _ in range(60)]
        macd_line, signal_line, histogram = _macd(closes)
        for i in range(len(closes)):
            if not (math.isnan(macd_line[i]) or math.isnan(signal_line[i])):
                expected = macd_line[i] - signal_line[i]
                assert abs(histogram[i] - expected) < 1e-10


class TestTechnicalChart:
    def test_renders_valid_png(self):
        assert validate_png(render(_sample_data()))

    def test_has_three_subplots(self):
        fig = _create_figure(_sample_data())
        assert len(fig.axes) == 3
        plt.close(fig)

    def test_rsi_has_threshold_lines(self):
        fig = _create_figure(_sample_data())
        ax_rsi = fig.axes[1]  # middle subplot
        # Should have at least 3 lines: RSI + 70 + 30 thresholds
        assert len(ax_rsi.lines) >= 3
        plt.close(fig)

    def test_macd_has_histogram(self):
        fig = _create_figure(_sample_data())
        ax_macd = fig.axes[2]  # bottom subplot
        # Histogram rendered as bars
        assert len(ax_macd.patches) > 0 or len(ax_macd.collections) > 0
        plt.close(fig)

    def test_price_subplot_has_bollinger_fill(self):
        fig = _create_figure(_sample_data())
        ax_price = fig.axes[0]
        # fill_between creates a PolyCollection
        assert len(ax_price.collections) > 0
        plt.close(fig)

    def test_title_is_set(self):
        fig = _create_figure(_sample_data())
        assert fig.axes[0].get_title() == "AAPL Technical"
        plt.close(fig)
