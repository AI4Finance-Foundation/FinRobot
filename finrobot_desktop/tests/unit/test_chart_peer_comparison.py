"""Tests for peer comparison bar chart."""

from finagent.engine.charts.base import ChartDataPoint, validate_png
from finagent.engine.charts.peer_comparison import render, _create_figure


def _sample_data():
    return ChartDataPoint(
        chart_type="peer_comparison",
        title="EV/EBITDA Peer Comparison",
        data=[
            {"ticker": "AAPL", "ev_ebitda": 22.5, "pe_ratio": 30.1, "is_target": True},
            {"ticker": "MSFT", "ev_ebitda": 25.3, "pe_ratio": 34.2, "is_target": False},
            {"ticker": "GOOG", "ev_ebitda": 18.7, "pe_ratio": 24.5, "is_target": False},
            {"ticker": "META", "ev_ebitda": 15.2, "pe_ratio": 22.8, "is_target": False},
        ],
    )


class TestPeerComparisonChart:
    def test_renders_valid_png(self):
        assert validate_png(render(_sample_data()))

    def test_target_highlighted(self):
        """Verify target company bar colour differs from peer bars."""
        fig = _create_figure(_sample_data())
        ax = fig.axes[0]
        patches = ax.patches
        # Collect unique face colours
        colors = set()
        for p in patches:
            fc = p.get_facecolor()
            colors.add(tuple(fc))
        # Target uses accent_color, peers use primary_color — expect at least 2 distinct
        assert len(colors) >= 2
        import matplotlib.pyplot as plt

        plt.close(fig)
