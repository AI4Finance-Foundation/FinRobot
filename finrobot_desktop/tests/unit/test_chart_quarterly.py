"""Tests for quarterly comparison grouped bar chart."""

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from finagent.engine.charts.base import ChartDataPoint, validate_png
from finagent.engine.charts.quarterly_comparison import _create_figure, render


def _sample_data():
    return ChartDataPoint(
        chart_type="quarterly_comparison",
        title="Revenue by Quarter",
        data=[
            {"quarter": "Q1", "year": "2023", "value": 90e9},
            {"quarter": "Q2", "year": "2023", "value": 81e9},
            {"quarter": "Q3", "year": "2023", "value": 89e9},
            {"quarter": "Q4", "year": "2023", "value": 119e9},
            {"quarter": "Q1", "year": "2024", "value": 95e9},
            {"quarter": "Q2", "year": "2024", "value": 85e9},
            {"quarter": "Q3", "year": "2024", "value": 94e9},
            {"quarter": "Q4", "year": "2024", "value": 124e9},
        ],
    )


class TestQuarterlyComparisonChart:
    def test_renders_valid_png(self):
        assert validate_png(render(_sample_data()))

    def test_has_correct_bar_count(self):
        fig = _create_figure(_sample_data())
        ax = fig.axes[0]
        # 4 quarters x 2 years = 8 bars
        assert len(ax.patches) == 8
        plt.close(fig)

    def test_legend_has_year_entries(self):
        fig = _create_figure(_sample_data())
        legend = fig.axes[0].get_legend()
        assert legend is not None
        texts = [t.get_text() for t in legend.get_texts()]
        assert "2023" in texts
        assert "2024" in texts
        plt.close(fig)

    def test_xticklabels_are_quarters(self):
        fig = _create_figure(_sample_data())
        ax = fig.axes[0]
        labels = [t.get_text() for t in ax.get_xticklabels()]
        assert labels == ["Q1", "Q2", "Q3", "Q4"]
        plt.close(fig)

    def test_title_set(self):
        fig = _create_figure(_sample_data())
        assert fig.axes[0].get_title() == "Revenue by Quarter"
        plt.close(fig)

    def test_bar_heights_match_values(self):
        fig = _create_figure(_sample_data())
        ax = fig.axes[0]
        rects = [p for p in ax.patches if isinstance(p, Rectangle)]
        heights = [r.get_height() for r in rects]
        # First 4 bars = 2023 Q1-Q4, next 4 = 2024 Q1-Q4
        expected_2023 = [90e9, 81e9, 89e9, 119e9]
        expected_2024 = [95e9, 85e9, 94e9, 124e9]
        for i, exp in enumerate(expected_2023):
            assert abs(heights[i] - exp) < 1e6
        for i, exp in enumerate(expected_2024):
            assert abs(heights[i + 4] - exp) < 1e6
        plt.close(fig)

    def test_three_years(self):
        """Chart handles 3 years correctly."""
        data = ChartDataPoint(
            chart_type="quarterly_comparison",
            title="3Y",
            data=[
                {"quarter": "Q1", "year": "2022", "value": 80e9},
                {"quarter": "Q1", "year": "2023", "value": 90e9},
                {"quarter": "Q1", "year": "2024", "value": 95e9},
            ],
        )
        fig = _create_figure(data)
        ax = fig.axes[0]
        assert len(ax.patches) == 3
        legend = ax.get_legend()
        assert legend is not None
        texts = [t.get_text() for t in legend.get_texts()]
        assert "2022" in texts
        assert "2023" in texts
        assert "2024" in texts
        plt.close(fig)
