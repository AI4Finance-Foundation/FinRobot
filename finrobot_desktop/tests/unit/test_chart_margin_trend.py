"""Tests for margin trend multi-line chart."""

from finagent.engine.charts.base import ChartDataPoint, validate_png
from finagent.engine.charts.margin_trend import render, _create_figure


def _sample_data():
    return ChartDataPoint(
        chart_type="margin_trend",
        title="AAPL Margin Trends",
        data=[
            {"year": 2020, "gross_margin": 0.382, "ebitda_margin": 0.308, "operating_margin": 0.241},
            {"year": 2021, "gross_margin": 0.418, "ebitda_margin": 0.339, "operating_margin": 0.298},
            {"year": 2022, "gross_margin": 0.433, "ebitda_margin": 0.347, "operating_margin": 0.303},
            {"year": 2023, "gross_margin": 0.441, "ebitda_margin": 0.356, "operating_margin": 0.297},
            {"year": 2024, "gross_margin": 0.462, "ebitda_margin": 0.370, "operating_margin": 0.317},
        ],
    )


class TestMarginTrendChart:
    def test_renders_valid_png(self):
        assert validate_png(render(_sample_data()))

    def test_has_three_lines(self):
        fig = _create_figure(_sample_data())
        assert len(fig.axes[0].lines) == 3
        import matplotlib.pyplot as plt

        plt.close(fig)

    def test_ylabel_contains_margin(self):
        fig = _create_figure(_sample_data())
        ylabel = fig.axes[0].get_ylabel()
        assert "Margin" in ylabel or "margin" in ylabel or "%" in ylabel
        import matplotlib.pyplot as plt

        plt.close(fig)
