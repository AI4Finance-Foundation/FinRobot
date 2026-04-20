"""Tests for multi-axis time series chart."""

import matplotlib.pyplot as plt

from finagent.engine.charts.base import ChartDataPoint, validate_png
from finagent.engine.charts.time_series_multi import _create_figure, render


def _sample_data() -> ChartDataPoint:
    return ChartDataPoint(
        chart_type="time_series_multi",
        title="AAPL Revenue & Margins",
        data=[
            {"year": "2020", "revenue": 1e9, "net_income": 1e8, "operating_margin": 0.15},
            {"year": "2021", "revenue": 1.2e9, "net_income": 1.5e8, "operating_margin": 0.18},
            {"year": "2022", "revenue": 1.5e9, "net_income": 2e8, "operating_margin": 0.20},
            {"year": "2023", "revenue": 1.8e9, "net_income": 2.5e8, "operating_margin": 0.22},
        ],
    )


class TestTimeSeriesMultiChart:
    def test_renders_valid_png(self):
        png = render(_sample_data())
        assert validate_png(png)

    def test_has_two_y_axes(self):
        """Dual-axis chart should produce a twinx (2 axes on the figure)."""
        fig = _create_figure(_sample_data())
        # twinx creates a second axes object sharing the same x-axis
        assert len(fig.axes) == 2
        plt.close(fig)

    def test_left_axis_has_revenue_line(self):
        """Left axis should have lines for absolute-value metrics."""
        fig = _create_figure(_sample_data())
        ax_left = fig.axes[0]
        line_labels = [str(ln.get_label()) for ln in ax_left.lines]
        # 'revenue' -> 'Revenue' after title-casing
        assert any("Revenue" in lbl for lbl in line_labels)
        plt.close(fig)

    def test_right_axis_has_margin_line(self):
        """Right axis should have lines for ratio/margin metrics."""
        fig = _create_figure(_sample_data())
        ax_right = fig.axes[1]
        line_labels = [str(ln.get_label()) for ln in ax_right.lines]
        assert any("Margin" in lbl for lbl in line_labels)
        plt.close(fig)

    def test_both_axes_have_labels(self):
        """Both Y-axes should have descriptive labels."""
        fig = _create_figure(_sample_data())
        ax_left = fig.axes[0]
        ax_right = fig.axes[1]
        assert ax_left.get_ylabel() != ""
        assert ax_right.get_ylabel() != ""
        plt.close(fig)

    def test_right_axis_values_are_percentages(self):
        """Right-axis margin values should be scaled to percentage (0.15 -> 15)."""
        fig = _create_figure(_sample_data())
        ax_right = fig.axes[1]
        # Operating margin lines should have values in the 15-22 range (not 0.15-0.22)
        for ln in ax_right.lines:
            ydata: list[float] = list(ln.get_ydata())  # type: ignore[arg-type]
            assert all(v >= 10 for v in ydata), "Margin values should be in percentage scale"
        plt.close(fig)
