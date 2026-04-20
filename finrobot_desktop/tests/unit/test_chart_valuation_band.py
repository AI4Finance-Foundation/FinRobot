"""Tests for valuation range band chart (EV/EBITDA historical band)."""

import matplotlib.pyplot as plt

from finagent.engine.charts.base import ChartDataPoint, validate_png
from finagent.engine.charts.valuation_band import _create_figure, render


def _sample_data():
    return ChartDataPoint(
        chart_type="valuation_band",
        title="AAPL EV/EBITDA Band",
        data=[
            {"date": "2020-Q1", "ev_ebitda": 14.5},
            {"date": "2020-Q2", "ev_ebitda": 15.2},
            {"date": "2020-Q3", "ev_ebitda": 16.8},
            {"date": "2020-Q4", "ev_ebitda": 15.5},
            {"date": "2021-Q1", "ev_ebitda": 17.2},
            {"date": "2021-Q2", "ev_ebitda": 18.1},
            {"date": "2021-Q3", "ev_ebitda": 16.9},
            {"date": "2021-Q4", "ev_ebitda": 17.5},
        ],
    )


class TestValuationBandChart:
    def test_renders_valid_png(self):
        assert validate_png(render(_sample_data()))

    def test_has_value_line_and_mean_line(self):
        fig = _create_figure(_sample_data())
        ax = fig.axes[0]
        assert len(ax.lines) >= 2  # value line + mean line
        plt.close(fig)

    def test_has_fill_between_band(self):
        fig = _create_figure(_sample_data())
        ax = fig.axes[0]
        assert len(ax.collections) >= 1  # fill_between creates a PolyCollection
        plt.close(fig)

    def test_has_annotation(self):
        fig = _create_figure(_sample_data())
        ax = fig.axes[0]
        texts = [t.get_text() for t in ax.texts]
        # Last value (17.5) should be annotated
        assert any("17.5" in t for t in texts)
        plt.close(fig)

    def test_mean_value_correct(self):
        """Mean of [14.5, 15.2, 16.8, 15.5, 17.2, 18.1, 16.9, 17.5] = 16.4625."""
        fig = _create_figure(_sample_data())
        ax = fig.axes[0]
        # axhline is the last line added
        mean_line = ax.lines[-1]
        ydata = mean_line.get_ydata()
        mean_y: float = ydata[0]  # type: ignore[assignment,index]
        expected = (14.5 + 15.2 + 16.8 + 15.5 + 17.2 + 18.1 + 16.9 + 17.5) / 8
        assert abs(mean_y - expected) < 0.01
        plt.close(fig)

    def test_ylabel_default(self):
        fig = _create_figure(_sample_data())
        ax = fig.axes[0]
        assert ax.get_ylabel() == "EV/EBITDA"
        plt.close(fig)

    def test_ylabel_custom(self):
        data = _sample_data()
        data.y_label = "P/E Ratio"
        fig = _create_figure(data)
        ax = fig.axes[0]
        assert ax.get_ylabel() == "P/E Ratio"
        plt.close(fig)
