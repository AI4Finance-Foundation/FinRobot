"""Tests for valuation bridge waterfall chart."""

from finagent.engine.charts.base import ChartConfig, ChartDataPoint, validate_png
from finagent.engine.charts.waterfall import render, _create_figure


def _sample_data():
    return ChartDataPoint(
        chart_type="waterfall",
        title="AAPL Valuation Bridge",
        data=[
            {"label": "PV of FCFs", "value": 450.0, "is_total": False},
            {"label": "Terminal Value", "value": 320.0, "is_total": False},
            {"label": "Enterprise Value", "value": 770.0, "is_total": True},
            {"label": "Net Debt", "value": -50.0, "is_total": False},
            {"label": "Equity Value", "value": 720.0, "is_total": True},
        ],
    )


class TestWaterfallChart:
    def test_renders_valid_png(self):
        assert validate_png(render(_sample_data()))

    def test_correct_number_of_bars(self):
        """Each data row should produce one bar in the chart."""
        fig = _create_figure(_sample_data())
        ax = fig.axes[0]
        # Count patches (bars) — each row produces exactly one bar
        bars = [p for p in ax.patches if hasattr(p, "get_height")]
        assert len(bars) == 5, f"Expected 5 bars, got {len(bars)}"
        import matplotlib.pyplot as plt

        plt.close(fig)

    def test_has_correct_title(self):
        fig = _create_figure(_sample_data())
        assert "AAPL" in fig.axes[0].get_title()
        import matplotlib.pyplot as plt

        plt.close(fig)

    def test_negative_value_handled(self):
        """Negative incremental bars (e.g. Net Debt) should render without error."""
        data = ChartDataPoint(
            chart_type="waterfall",
            title="Negative Test",
            data=[
                {"label": "Start", "value": 100.0, "is_total": False},
                {"label": "Deduction", "value": -30.0, "is_total": False},
                {"label": "End", "value": 70.0, "is_total": True},
            ],
        )
        assert validate_png(render(data))

    def test_respects_config_size(self):
        config = ChartConfig(width=14, height=8)
        assert validate_png(render(_sample_data(), config=config))
