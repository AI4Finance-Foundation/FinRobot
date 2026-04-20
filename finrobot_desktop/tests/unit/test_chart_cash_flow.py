"""Tests for cash flow composition stacked bar chart."""

import matplotlib.pyplot as plt

from finagent.engine.charts.base import ChartDataPoint, validate_png
from finagent.engine.charts.cash_flow import _create_figure, _scale_label, render


def _sample_data():
    return ChartDataPoint(
        chart_type="cash_flow",
        title="AAPL Cash Flow",
        data=[
            {
                "year": "2020",
                "operating": 8e10,
                "investing": -1e10,
                "financing": -9e10,
            },
            {
                "year": "2021",
                "operating": 1.04e11,
                "investing": -1.5e10,
                "financing": -1.01e11,
            },
            {
                "year": "2022",
                "operating": 1.22e11,
                "investing": -2.3e10,
                "financing": -1.1e11,
            },
        ],
    )


class TestCashFlowChart:
    def test_renders_valid_png(self):
        assert validate_png(render(_sample_data()))

    def test_has_bars_for_three_components(self):
        fig = _create_figure(_sample_data())
        ax = fig.axes[0]
        # 3 years x 3 components = 9 bar patches minimum
        assert len(ax.patches) >= 9
        plt.close(fig)

    def test_has_net_line(self):
        fig = _create_figure(_sample_data())
        ax = fig.axes[0]
        # At least 1 line for net cash flow (plus axhline at 0)
        assert len(ax.lines) >= 1
        plt.close(fig)

    def test_legend_has_four_entries(self):
        fig = _create_figure(_sample_data())
        legend = fig.axes[0].get_legend()
        assert legend is not None
        assert len(legend.get_texts()) >= 4  # Operating, Investing, Financing, Net
        plt.close(fig)

    def test_ylabel_contains_scale(self):
        fig = _create_figure(_sample_data())
        ylabel = fig.axes[0].get_ylabel()
        assert "$" in ylabel
        assert "B" in ylabel  # Values are in billions
        plt.close(fig)

    def test_scale_label_billions(self):
        divisor, suffix = _scale_label([1e10, -5e9, 2e10])
        assert divisor == 1e9
        assert suffix == "$B"

    def test_scale_label_millions(self):
        divisor, suffix = _scale_label([5e6, -3e6])
        assert divisor == 1e6
        assert suffix == "$M"

    def test_scale_label_thousands(self):
        divisor, suffix = _scale_label([5000, -3000])
        assert divisor == 1e3
        assert suffix == "$K"

    def test_scale_label_small(self):
        divisor, suffix = _scale_label([50, -30])
        assert divisor == 1.0
        assert suffix == "$"

    def test_net_line_values_are_sum(self):
        """Verify net cash flow line data equals sum of three components."""
        fig = _create_figure(_sample_data())
        ax = fig.axes[0]
        # Find the line with label "Net Cash Flow"
        net_lines = [ln for ln in ax.lines if ln.get_label() == "Net Cash Flow"]
        assert len(net_lines) == 1
        net_y: list[float] = list(net_lines[0].get_ydata())  # type: ignore[arg-type]

        # Expected net in $B: 2020: (80-10-90)/1=-20, 2021: (104-15-101)/1=-12,
        #   2022: (122-23-110)/1=-11
        expected_net = [
            (8e10 - 1e10 - 9e10) / 1e9,
            (1.04e11 - 1.5e10 - 1.01e11) / 1e9,
            (1.22e11 - 2.3e10 - 1.1e11) / 1e9,
        ]
        for actual, expected in zip(net_y, expected_net):
            assert abs(actual - expected) < 0.01, f"{actual} != {expected}"
        plt.close(fig)

    def test_three_years_on_x_axis(self):
        fig = _create_figure(_sample_data())
        ax = fig.axes[0]
        labels = [t.get_text() for t in ax.get_xticklabels()]
        assert labels == ["2020", "2021", "2022"]
        plt.close(fig)
