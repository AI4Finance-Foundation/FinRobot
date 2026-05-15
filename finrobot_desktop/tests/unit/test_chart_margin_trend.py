"""Tests for margin trend multi-line chart."""

import matplotlib.pyplot as plt

from finagent.engine.charts.base import ChartDataPoint, validate_png
from finagent.engine.charts.margin_trend import (
    MetricLine,
    _create_figure,
    render,
    render_ebitda_margin_detail,
    render_gross_margin,
    render_ltm_ebitda_margin,
    render_sga_ratio,
)


def _sample_data():
    return ChartDataPoint(
        chart_type="margin_trend",
        title="AAPL Margin Trends",
        data=[
            {
                "year": 2020,
                "gross_margin": 0.382,
                "ebitda_margin": 0.308,
                "operating_margin": 0.241,
            },
            {
                "year": 2021,
                "gross_margin": 0.418,
                "ebitda_margin": 0.339,
                "operating_margin": 0.298,
            },
            {
                "year": 2022,
                "gross_margin": 0.433,
                "ebitda_margin": 0.347,
                "operating_margin": 0.303,
            },
            {
                "year": 2023,
                "gross_margin": 0.441,
                "ebitda_margin": 0.356,
                "operating_margin": 0.297,
            },
            {
                "year": 2024,
                "gross_margin": 0.462,
                "ebitda_margin": 0.370,
                "operating_margin": 0.317,
            },
        ],
    )


class TestMarginTrendChart:
    def test_renders_valid_png(self):
        assert validate_png(render(_sample_data()))

    def test_has_three_lines(self):
        fig = _create_figure(_sample_data())
        assert len(fig.axes[0].lines) == 3
        plt.close(fig)

    def test_ylabel_contains_margin(self):
        fig = _create_figure(_sample_data())
        ylabel = fig.axes[0].get_ylabel()
        assert "Margin" in ylabel or "margin" in ylabel or "%" in ylabel
        plt.close(fig)

    def test_backward_compatible_default_three_lines(self):
        """Existing behavior: no metrics param -> 3 lines."""
        fig = _create_figure(_sample_data())
        assert len(fig.axes[0].lines) == 3
        plt.close(fig)


class TestGrossMarginVariant:
    def test_gross_margin_single_line(self):
        data = ChartDataPoint(
            chart_type="gross_margin",
            title="Gross Margin Test",
            data=[
                {"year": 2020, "gross_margin": 0.38},
                {"year": 2021, "gross_margin": 0.42},
            ],
        )
        fig = _create_figure(
            data,
            metrics=[MetricLine("gross_margin", "Gross Margin", "primary_color", "o")],
        )
        assert len(fig.axes[0].lines) == 1
        plt.close(fig)

    def test_gross_margin_renders_valid_png(self):
        data = ChartDataPoint(
            chart_type="gross_margin",
            title="Gross Margin PNG Test",
            data=[
                {"year": 2020, "gross_margin": 0.38},
                {"year": 2021, "gross_margin": 0.42},
            ],
        )
        assert validate_png(render_gross_margin(data))


class TestSgaRatioVariant:
    def test_sga_ratio_renders_valid_png(self):
        data = ChartDataPoint(
            chart_type="sga_ratio",
            title="SGA Ratio Test",
            data=[
                {"year": 2020, "sga_ratio": 0.15},
                {"year": 2021, "sga_ratio": 0.14},
            ],
        )
        result = render(
            data,
            metrics=[MetricLine("sga_ratio", "SG&A / Revenue", "primary_color", "o")],
        )
        assert validate_png(result)

    def test_sga_ratio_factory(self):
        data = ChartDataPoint(
            chart_type="sga_ratio",
            title="SGA Factory",
            data=[
                {"year": 2020, "sga_ratio": 0.15},
                {"year": 2021, "sga_ratio": 0.14},
            ],
        )
        assert validate_png(render_sga_ratio(data))


class TestLtmEbitdaMarginVariant:
    def test_ltm_ebitda_margin_factory(self):
        data = ChartDataPoint(
            chart_type="ltm_ebitda_margin",
            title="LTM EBITDA",
            data=[
                {"year": 2020, "ltm_ebitda_margin": 0.30},
                {"year": 2021, "ltm_ebitda_margin": 0.35},
            ],
        )
        assert validate_png(render_ltm_ebitda_margin(data))


class TestEbitdaMarginDetailVariant:
    def test_ebitda_margin_detail_has_mean_line(self):
        data = ChartDataPoint(
            chart_type="ebitda_margin_detail",
            title="EBITDA Detail Test",
            data=[
                {"year": 2020, "ebitda_margin": 0.30},
                {"year": 2021, "ebitda_margin": 0.35},
            ],
        )
        fig = _create_figure(
            data,
            metrics=[MetricLine("ebitda_margin", "EBITDA Margin", "accent_color", "s")],
            show_mean_line=True,
        )
        # Should have 1 data line + 1 mean line = 2 lines
        assert len(fig.axes[0].lines) >= 2
        plt.close(fig)

    def test_ebitda_margin_detail_factory(self):
        data = ChartDataPoint(
            chart_type="ebitda_margin_detail",
            title="EBITDA Detail Factory",
            data=[
                {"year": 2020, "ebitda_margin": 0.30},
                {"year": 2021, "ebitda_margin": 0.35},
                {"year": 2022, "ebitda_margin": 0.33},
            ],
        )
        assert validate_png(render_ebitda_margin_detail(data))

    def test_ebitda_margin_detail_mean_value_correct(self):
        data = ChartDataPoint(
            chart_type="ebitda_margin_detail",
            title="EBITDA Mean Check",
            data=[
                {"year": 2020, "ebitda_margin": 0.30},
                {"year": 2021, "ebitda_margin": 0.40},
            ],
        )
        fig = _create_figure(
            data,
            metrics=[MetricLine("ebitda_margin", "EBITDA Margin", "accent_color", "s")],
            show_mean_line=True,
        )
        # Mean of 30% and 40% = 35%
        # The second line is the axhline (mean line)
        mean_line = fig.axes[0].lines[1]
        mean_y = mean_line.get_ydata()[0]
        assert abs(mean_y - 35.0) < 0.01
        plt.close(fig)
