import pytest
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from finagent.engine.charts.base import ChartConfig, render_to_base64, validate_png, ChartDataPoint, StepChartData, _num


class TestChartConfig:
    def test_default_colors(self):
        config = ChartConfig()
        assert config.primary_color == "#1a365d"
        assert config.accent_color == "#d4a843"
        assert config.neutral_color == "#6b7280"

    def test_default_size(self):
        config = ChartConfig()
        assert config.width == 10
        assert config.height == 6


class TestRenderToBase64:
    def test_returns_valid_base64_string(self):
        fig, ax = plt.subplots()
        ax.bar(["A", "B"], [1, 2])
        result = render_to_base64(fig)
        assert isinstance(result, str)
        assert result.startswith("data:image/png;base64,")


class TestValidatePng:
    def test_valid_png(self):
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot([1, 2, 3])
        import io
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100)
        data = buf.getvalue()
        plt.close(fig)
        assert validate_png(data) is True

    def test_invalid_png(self):
        assert validate_png(b"not a png") is False


class TestChartDataPoint:
    def test_valid_construction(self):
        cdp = ChartDataPoint(
            chart_type="revenue_ebitda",
            data=[{"year": 2024, "revenue": 394e9, "ebitda": 130e9, "is_forecast": False}],
            title="Revenue & EBITDA",
        )
        assert cdp.chart_type == "revenue_ebitda"


class TestStepChartData:
    def test_default_empty(self):
        scd = StepChartData()
        assert scd.charts == []


class TestNum:
    def test_float_passthrough(self):
        assert _num(3.14) == 3.14

    def test_int_to_float(self):
        assert _num(2024) == 2024.0

    def test_none_returns_zero(self):
        assert _num(None) == 0.0

    def test_string_numeric(self):
        assert _num("42.5") == 42.5

    def test_bool_true(self):
        assert _num(True) == 1.0

    def test_bool_false(self):
        assert _num(False) == 0.0
