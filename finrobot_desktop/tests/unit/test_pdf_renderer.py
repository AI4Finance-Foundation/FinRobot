import pytest
from finagent.engine.reports.pdf_renderer import render_pdf


class TestRenderPdf:
    def test_function_exists_and_callable(self):
        """Basic smoke test — function exists and accepts HTML string."""
        assert callable(render_pdf)

    def test_raises_on_missing_weasyprint(self):
        """If weasyprint is not installed, should raise RuntimeError."""
        from unittest.mock import patch
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "weasyprint":
                raise ImportError("No module named 'weasyprint'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            with pytest.raises(RuntimeError, match="weasyprint"):
                render_pdf("<html><body>Test</body></html>")

    def test_renders_pdf_if_weasyprint_available(self):
        """If weasyprint is installed, should return bytes starting with %PDF."""
        try:
            result = render_pdf("<html><body><h1>Test Report</h1></body></html>")
            assert isinstance(result, bytes)
            assert result[:5] == b"%PDF-"
        except RuntimeError:
            pytest.skip("weasyprint not installed")
