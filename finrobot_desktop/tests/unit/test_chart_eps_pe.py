"""Tests for EPS & PE Ratio dual-axis chart."""

from finagent.engine.charts.base import ChartConfig, ChartDataPoint, validate_png
from finagent.engine.charts.eps_pe import render, _create_figure


def _sample_data():
    return ChartDataPoint(
        chart_type="eps_pe",
        title="AAPL EPS & PE Ratio",
        data=[
            {"year": 2020, "eps": 3.28, "pe_ratio": 35.2},
            {"year": 2021, "eps": 5.61, "pe_ratio": 28.7},
            {"year": 2022, "eps": 6.11, "pe_ratio": 21.3},
            {"year": 2023, "eps": 6.42, "pe_ratio": 30.5},
            {"year": 2024, "eps": 6.97, "pe_ratio": None},
        ],
    )


class TestEpsPeChart:
    def test_renders_valid_png(self):
        assert validate_png(render(_sample_data()))

    def test_has_dual_y_axes(self):
        """EPS (bars) on left axis, PE (line) on right axis — at least 2 axes."""
        fig = _create_figure(_sample_data())
        assert len(fig.axes) >= 2, f"Expected >= 2 axes (twinx), got {len(fig.axes)}"
        import matplotlib.pyplot as plt

        plt.close(fig)

    def test_handles_null_pe_ratio(self):
        """When pe_ratio is None the chart should still render without error."""
        data = ChartDataPoint(
            chart_type="eps_pe",
            title="Null PE Test",
            data=[
                {"year": 2023, "eps": 5.0, "pe_ratio": None},
                {"year": 2024, "eps": 6.0, "pe_ratio": None},
            ],
        )
        assert validate_png(render(data))

    def test_has_correct_title(self):
        fig = _create_figure(_sample_data())
        assert "AAPL" in fig.axes[0].get_title()
        import matplotlib.pyplot as plt

        plt.close(fig)

    def test_respects_config_size(self):
        config = ChartConfig(width=14, height=7)
        assert validate_png(render(_sample_data(), config=config))
