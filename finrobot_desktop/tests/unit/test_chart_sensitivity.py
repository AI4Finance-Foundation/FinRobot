"""Tests for DCF sensitivity heatmap chart."""

from finagent.engine.charts.base import ChartDataPoint, validate_png
from finagent.engine.charts.sensitivity import render, _create_figure


def _sample_data():
    cells = []
    for wacc in [0.08, 0.09, 0.10, 0.11]:
        for tg in [0.02, 0.025, 0.03]:
            price = 300 - wacc * 1000 - tg * 500 if tg < wacc else None
            cells.append({"wacc": wacc, "tg": tg, "implied_price": price})
    return ChartDataPoint(
        chart_type="sensitivity",
        title="DCF Sensitivity",
        data=cells,
    )


class TestSensitivityChart:
    def test_renders_valid_png(self):
        assert validate_png(render(_sample_data()))

    def test_has_annotations(self):
        fig = _create_figure(_sample_data())
        texts = [t for t in fig.axes[0].texts]
        assert len(texts) > 0  # cell annotations exist
        import matplotlib.pyplot as plt

        plt.close(fig)
