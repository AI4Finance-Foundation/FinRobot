"""Tests for multi-dimensional financial radar chart."""

from finagent.engine.charts.base import ChartConfig, ChartDataPoint, validate_png
from finagent.engine.charts.radar import render, _create_figure


def _sample_data():
    return ChartDataPoint(
        chart_type="radar",
        title="AAPL Financial Profile",
        data=[
            {"dimension": "Profitability", "value": 0.85, "benchmark": 0.70},
            {"dimension": "Growth", "value": 0.65, "benchmark": 0.60},
            {"dimension": "Leverage", "value": 0.45, "benchmark": 0.50},
            {"dimension": "Liquidity", "value": 0.72, "benchmark": 0.65},
            {"dimension": "Efficiency", "value": 0.80, "benchmark": 0.75},
        ],
    )


class TestRadarChart:
    def test_renders_valid_png(self):
        assert validate_png(render(_sample_data()))

    def test_uses_polar_projection(self):
        """Radar chart must use polar projection."""
        fig = _create_figure(_sample_data())
        assert fig.axes[0].name == "polar", f"Expected polar projection, got '{fig.axes[0].name}'"
        import matplotlib.pyplot as plt

        plt.close(fig)

    def test_has_correct_title(self):
        fig = _create_figure(_sample_data())
        # Title may be on the figure or the axes
        title_found = (
            any("AAPL" in t.get_text() for t in fig.texts) or "AAPL" in fig.axes[0].get_title()
        )
        assert title_found
        import matplotlib.pyplot as plt

        plt.close(fig)

    def test_minimum_three_dimensions(self):
        """Radar with only 3 dimensions should still render fine."""
        data = ChartDataPoint(
            chart_type="radar",
            title="Minimal Radar",
            data=[
                {"dimension": "A", "value": 0.5, "benchmark": 0.6},
                {"dimension": "B", "value": 0.7, "benchmark": 0.4},
                {"dimension": "C", "value": 0.3, "benchmark": 0.8},
            ],
        )
        assert validate_png(render(data))

    def test_respects_config_size(self):
        config = ChartConfig(width=10, height=10)
        assert validate_png(render(_sample_data(), config=config))
