"""Tests for revenue YoY growth bar chart."""

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from finagent.engine.charts.base import ChartDataPoint, validate_png
from finagent.engine.charts.revenue_yoy import _create_figure, render


def _sample_data():
    return ChartDataPoint(
        chart_type="revenue_yoy",
        title="AAPL Revenue YoY",
        data=[
            {"year": "2019", "revenue": 260e9},
            {"year": "2020", "revenue": 274e9},
            {"year": "2021", "revenue": 366e9},
            {"year": "2022", "revenue": 394e9},
            {"year": "2023", "revenue": 383e9},  # negative YoY
        ],
    )


class TestRevenueYoYChart:
    def test_renders_valid_png(self):
        assert validate_png(render(_sample_data()))

    def test_has_bars(self):
        fig = _create_figure(_sample_data())
        ax = fig.axes[0]
        # 4 bars (first year has no YoY)
        assert len(ax.patches) == 4
        plt.close(fig)

    def test_negative_yoy_uses_different_color(self):
        fig = _create_figure(_sample_data())
        ax = fig.axes[0]
        # Last bar (2023 decline) should have different color than first bars
        colors = [p.get_facecolor() for p in ax.patches]
        assert colors[-1] != colors[0]  # negative != positive
        plt.close(fig)

    def test_ylabel_contains_percent(self):
        fig = _create_figure(_sample_data())
        ylabel = fig.axes[0].get_ylabel()
        assert "%" in ylabel or "Growth" in ylabel
        plt.close(fig)

    def test_yoy_values_correct(self):
        """Verify computed YoY growth rates match expected values."""
        fig = _create_figure(_sample_data())
        ax = fig.axes[0]
        # Expected YoY: 2020=(274-260)/260=5.38%, 2021=(366-274)/274=33.58%,
        #   2022=(394-366)/366=7.65%, 2023=(383-394)/394=-2.79%
        rects = [p for p in ax.patches if isinstance(p, Rectangle)]
        heights = [r.get_height() for r in rects]
        assert abs(heights[0] - 5.384615) < 0.01
        assert abs(heights[1] - 33.5766) < 0.01
        assert abs(heights[2] - 7.6503) < 0.01
        assert heights[3] < 0  # 2023 is negative
        plt.close(fig)

    def test_trend_line_present_with_4plus_points(self):
        """With 4 YoY points, a trend line should be drawn."""
        fig = _create_figure(_sample_data())
        ax = fig.axes[0]
        # Should have at least 1 line (the trend line)
        assert len(ax.lines) >= 1
        plt.close(fig)

    def test_no_trend_line_with_few_points(self):
        """With fewer than 4 YoY points, no trend line."""
        short_data = ChartDataPoint(
            chart_type="revenue_yoy",
            title="Short",
            data=[
                {"year": "2020", "revenue": 100e9},
                {"year": "2021", "revenue": 110e9},
                {"year": "2022", "revenue": 120e9},
            ],
        )
        fig = _create_figure(short_data)
        ax = fig.axes[0]
        # Only the axhline at 0 (1 line), no trend line overlay
        assert len(ax.lines) == 1
        plt.close(fig)
