"""Tests for football field valuation chart."""

from finagent.engine.charts.base import ChartConfig, ChartDataPoint, validate_png
from finagent.engine.charts.football_field import render, _create_figure


def _sample_data():
    return ChartDataPoint(
        chart_type="football_field",
        title="Valuation Football Field",
        data=[
            {"method": "DCF", "low": 210, "mid": 245, "high": 290},
            {"method": "EV/EBITDA", "low": 220, "mid": 250, "high": 280},
            {"method": "P/E", "low": 200, "mid": 235, "high": 265},
        ],
    )


class TestFootballFieldChart:
    def test_renders_valid_png(self):
        assert validate_png(render(_sample_data()))

    def test_has_correct_number_of_bars(self):
        fig = _create_figure(_sample_data())
        patches = fig.axes[0].patches
        assert len(patches) >= 3  # one bar per method
        import matplotlib.pyplot as plt

        plt.close(fig)
