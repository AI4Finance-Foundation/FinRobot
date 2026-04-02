"""Tests for 52-week price line + volume bars chart."""

from finagent.engine.charts.base import ChartConfig, ChartDataPoint, validate_png
from finagent.engine.charts.price_chart import render, _create_figure


def _sample_data():
    return ChartDataPoint(
        chart_type="price",
        title="AAPL 52-Week Price",
        x_label="Date",
        y_label="Price (USD)",
        data=[
            {"date": "2025-01-02", "close": 150.0, "volume": 80_000_000},
            {"date": "2025-02-03", "close": 155.5, "volume": 75_000_000},
            {"date": "2025-03-03", "close": 148.0, "volume": 90_000_000},
            {"date": "2025-04-01", "close": 162.3, "volume": 65_000_000},
            {"date": "2025-05-01", "close": 170.0, "volume": 70_000_000},
        ],
    )


class TestPriceChart:
    def test_renders_valid_png(self):
        assert validate_png(render(_sample_data()))

    def test_has_dual_y_axes(self):
        """Price chart must have twinx — at least 2 axes on the figure."""
        fig = _create_figure(_sample_data())
        assert len(fig.axes) >= 2, f"Expected >= 2 axes (twinx), got {len(fig.axes)}"
        import matplotlib.pyplot as plt

        plt.close(fig)

    def test_has_correct_title(self):
        fig = _create_figure(_sample_data())
        assert "AAPL" in fig.axes[0].get_title()
        import matplotlib.pyplot as plt

        plt.close(fig)

    def test_respects_config_size(self):
        config = ChartConfig(width=12, height=8)
        assert validate_png(render(_sample_data(), config=config))
