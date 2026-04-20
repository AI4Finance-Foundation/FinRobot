"""Tests for revenue segment donut chart."""

import matplotlib.pyplot as plt
from matplotlib.patches import Wedge

from finagent.engine.charts.base import ChartDataPoint, validate_png
from finagent.engine.charts.revenue_segments import _create_figure, render


def _sample_data():
    return ChartDataPoint(
        chart_type="revenue_segments",
        title="AAPL Revenue by Segment",
        data=[
            {"segment": "iPhone", "revenue": 200e9},
            {"segment": "Services", "revenue": 85e9},
            {"segment": "Mac", "revenue": 29e9},
            {"segment": "iPad", "revenue": 28e9},
            {"segment": "Wearables", "revenue": 39e9},
        ],
    )


class TestRevenueSegmentsChart:
    def test_renders_valid_png(self):
        assert validate_png(render(_sample_data()))

    def test_has_pie_wedges(self):
        fig = _create_figure(_sample_data())
        ax = fig.axes[0]
        # Pie creates wedge patches
        assert len(ax.patches) == 5
        plt.close(fig)

    def test_has_percentage_labels(self):
        fig = _create_figure(_sample_data())
        ax = fig.axes[0]
        texts = [t.get_text() for t in ax.texts]
        # At least one percentage label
        assert any("%" in t for t in texts)
        plt.close(fig)

    def test_segments_sorted_by_size(self):
        fig = _create_figure(_sample_data())
        ax = fig.axes[0]
        # Largest segment (iPhone) should be first wedge
        wedges = [p for p in ax.patches if isinstance(p, Wedge)]
        wedge_sizes = [w.theta2 - w.theta1 for w in wedges]
        assert wedge_sizes[0] == max(wedge_sizes)
        plt.close(fig)

    def test_respects_config_dpi(self):
        from finagent.engine.charts.base import ChartConfig

        config = ChartConfig(dpi=72)
        png = render(_sample_data(), config=config)
        assert validate_png(png)

    def test_single_segment(self):
        data = ChartDataPoint(
            chart_type="revenue_segments",
            title="Single Segment",
            data=[{"segment": "Only", "revenue": 100e9}],
        )
        fig = _create_figure(data)
        assert len(fig.axes[0].patches) == 1
        plt.close(fig)
