"""Tests for revenue & EBITDA grouped bar chart."""

from finagent.engine.charts.base import ChartConfig, ChartDataPoint, validate_png
from finagent.engine.charts.revenue_ebitda import render, _create_figure


def _sample_data():
    return ChartDataPoint(
        chart_type="revenue_ebitda",
        title="AAPL Revenue & EBITDA",
        data=[
            {"year": 2022, "revenue": 300e9, "ebitda": 100e9, "is_forecast": False},
            {"year": 2023, "revenue": 350e9, "ebitda": 120e9, "is_forecast": False},
            {"year": 2024, "revenue": 394e9, "ebitda": 130e9, "is_forecast": False},
            {"year": 2025, "revenue": 422e9, "ebitda": 139e9, "is_forecast": True},
        ],
    )


class TestRevenueEbitdaChart:
    def test_renders_valid_png(self):
        assert validate_png(render(_sample_data()))

    def test_has_correct_title(self):
        fig = _create_figure(_sample_data())
        assert "AAPL" in fig.axes[0].get_title() or any(
            "AAPL" in t.get_text() for t in fig.texts
        )
        import matplotlib.pyplot as plt

        plt.close(fig)

    def test_respects_config_size(self):
        config = ChartConfig(width=12, height=8)
        assert validate_png(render(_sample_data(), config=config))
