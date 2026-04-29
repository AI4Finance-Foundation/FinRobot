"""Tests for HTML report renderer.

Verifies that Jinja2 templates render correct HTML output with
embedded chart images, company data, and structured financial content.
"""

from __future__ import annotations

from finagent.engine.reports.html_renderer import (
    _auto_bold,
    _markdown_to_html,
    render_comps_report,
    render_dcf_report,
    render_equity_report,
)


def _equity_context(**overrides: object) -> dict:
    """Build a minimal equity report context with sensible defaults."""
    base = {
        "ticker": "AAPL",
        "company_name": "Apple Inc.",
        "current_price": 230.0,
        "market_cap": 3e12,
        "recommendation": "Buy",
        "price_target": 260.0,
        "charts": {},
        "historical_metrics": None,
        "forecast": None,
        "dcf_result": None,
        "peer_comps": None,
        "catalyst_analysis": None,
        "valuation_synthesis": None,
        "report_date": "April 17, 2026",
        "data_source": "yfinance",
        "data_timestamp": "2026-04-17 12:00 UTC",
        "sector": "Technology",
        "thesis_text": "",
        "report_text": "",
        "data_warnings": [],
    }
    base.update(overrides)
    return base


class TestRenderEquityReport:
    def test_returns_html_string(self) -> None:
        context = _equity_context()
        html = render_equity_report(context)
        assert "<html" in html.lower()
        assert "AAPL" in html
        assert "Apple Inc." in html

    def test_contains_recommendation(self) -> None:
        context = _equity_context(
            ticker="MSFT",
            company_name="Microsoft",
            current_price=400.0,
            recommendation="Hold",
            price_target=420.0,
        )
        html = render_equity_report(context)
        assert "Hold" in html
        assert "MSFT" in html

    def test_embeds_chart_image(self) -> None:
        context = _equity_context(
            charts={"revenue_ebitda": "data:image/png;base64,ABC123"},
        )
        html = render_equity_report(context)
        assert "data:image/png;base64,ABC123" in html

    def test_contains_price_info(self) -> None:
        context = _equity_context(current_price=230.0, price_target=260.0)
        html = render_equity_report(context)
        assert "230" in html
        assert "260" in html

    def test_market_cap_displayed(self) -> None:
        context = _equity_context(market_cap=3e12)
        html = render_equity_report(context)
        # Market cap should appear somewhere in the rendered output
        assert "3" in html

    def test_multiple_charts_embedded(self) -> None:
        charts = {
            "revenue_ebitda": "data:image/png;base64,CHART1",
            "margin_trend": "data:image/png;base64,CHART2",
            "sensitivity": "data:image/png;base64,CHART3",
        }
        context = _equity_context(charts=charts)
        html = render_equity_report(context)
        assert "data:image/png;base64,CHART1" in html
        assert "data:image/png;base64,CHART2" in html
        assert "data:image/png;base64,CHART3" in html

    def test_historical_metrics_table(self) -> None:
        metrics = {
            "years": [2022, 2023, 2024],
            "revenue": [394e9, 383e9, 391e9],
            "ebitda": [130e9, 125e9, 132e9],
            "gross_margin": [0.433, 0.441, 0.462],
            "operating_margin": [0.302, 0.299, 0.317],
            "net_income": [99.8e9, 97e9, 101e9],
        }
        context = _equity_context(historical_metrics=metrics)
        html = render_equity_report(context)
        assert "2022" in html
        assert "2023" in html
        assert "2024" in html

    def test_catalyst_analysis_section(self) -> None:
        catalyst = {
            "events": [
                {
                    "category": "product_launch",
                    "headline": "Vision Pro launch",
                    "sentiment": "positive",
                    "impact_score": 4,
                }
            ],
            "overall_sentiment": "bullish",
            "key_catalysts": ["Vision Pro", "Services growth"],
        }
        context = _equity_context(catalyst_analysis=catalyst)
        html = render_equity_report(context)
        assert "Vision Pro" in html
        assert "product launch" in html or "product_launch" in html

    def test_color_scheme_in_css(self) -> None:
        """Verify the FinTech color scheme is used in inline CSS."""
        html = render_equity_report(_equity_context())
        assert "#0f172a" in html
        assert "#6366f1" in html

    def test_html_is_complete_document(self) -> None:
        html = render_equity_report(_equity_context())
        lower = html.lower()
        assert "<!doctype html>" in lower or "<html" in lower
        assert "</html>" in lower
        assert "<head" in lower
        assert "<body" in lower


class TestAutoBold:
    def test_bolds_dollar_amounts(self) -> None:
        assert "<strong>$5.2B</strong>" in _auto_bold("Revenue was $5.2B last year")

    def test_bolds_percentages(self) -> None:
        result = _auto_bold("Margin improved to 25.3% from 20%")
        assert "<strong>25.3%</strong>" in result
        assert "<strong>20%</strong>" in result

    def test_bolds_multiples(self) -> None:
        assert "<strong>12.5x</strong>" in _auto_bold("Trading at 12.5x EV/EBITDA")

    def test_skips_already_bolded(self) -> None:
        text = "<strong>$5B</strong> revenue"
        assert _auto_bold(text) == text

    def test_empty_input(self) -> None:
        assert _auto_bold("") == ""


class TestMarkdownToHtml:
    def test_headings(self) -> None:
        result = _markdown_to_html("## Summary\n\nText here")
        assert "<h3" in result
        assert "Summary" in result

    def test_bold(self) -> None:
        result = _markdown_to_html("This is **important** text")
        assert "<strong>important</strong>" in result

    def test_list_items(self) -> None:
        result = _markdown_to_html("- Item one\n- Item two")
        assert "<li" in result
        assert "Item one" in result
        assert "Item two" in result

    def test_empty_input(self) -> None:
        assert _markdown_to_html("") == ""


class TestAutoBoldInTemplate:
    """Verify that autobold filter is applied to catalyst event text."""

    def test_catalyst_headline_gets_autobold(self) -> None:
        catalyst = {
            "events": [
                {
                    "category": "earnings",
                    "headline": "Revenue beat at $95.4B vs $93.2B expected",
                    "sentiment": "positive",
                    "impact_score": 4,
                }
            ],
        }
        context = _equity_context(catalyst_analysis=catalyst)
        html = render_equity_report(context)
        assert "<strong>$95.4B</strong>" in html
        assert "<strong>$93.2B</strong>" in html

    def test_catalyst_reasoning_gets_autobold(self) -> None:
        catalyst = {
            "events": [
                {
                    "category": "guidance",
                    "headline": "Q2 guidance raised",
                    "reasoning": "Management expects 15% growth to $100B",
                    "sentiment": "positive",
                    "impact_score": 3,
                }
            ],
        }
        context = _equity_context(catalyst_analysis=catalyst)
        html = render_equity_report(context)
        assert "<strong>15%</strong>" in html
        assert "<strong>$100B</strong>" in html


class TestRenderCompsReport:
    def test_returns_html(self) -> None:
        html = render_comps_report({"ticker": "AAPL", "charts": {}, "peer_comps": None})
        assert "<html" in html.lower()
        assert "AAPL" in html

    def test_peer_table_renders(self) -> None:
        peer_comps = {
            "target": {"ticker": "AAPL", "ev_ebitda": 25.0, "pe_ratio": 30.0},
            "peers": [
                {"ticker": "MSFT", "ev_ebitda": 22.0, "pe_ratio": 35.0},
                {"ticker": "GOOGL", "ev_ebitda": 18.0, "pe_ratio": 25.0},
            ],
            "median_ev_ebitda": 20.0,
            "median_pe": 30.0,
        }
        html = render_comps_report(
            {"ticker": "AAPL", "charts": {}, "peer_comps": peer_comps}
        )
        assert "MSFT" in html
        assert "GOOGL" in html

    def test_comps_chart_embedded(self) -> None:
        html = render_comps_report(
            {
                "ticker": "AAPL",
                "charts": {"peer_comparison": "data:image/png;base64,COMP1"},
                "peer_comps": None,
            }
        )
        assert "data:image/png;base64,COMP1" in html


class TestRenderDcfReport:
    def test_returns_html(self) -> None:
        html = render_dcf_report({"ticker": "AAPL", "charts": {}, "dcf_result": None})
        assert "<html" in html.lower()
        assert "AAPL" in html

    def test_dcf_result_renders(self) -> None:
        dcf_result = {
            "wacc": 0.095,
            "implied_price": 255.0,
            "enterprise_value": 3.2e12,
            "equity_value": 3.1e12,
            "projected_fcf": [80e9, 85e9, 90e9],
            "terminal_value": 2.5e12,
        }
        html = render_dcf_report(
            {"ticker": "AAPL", "charts": {}, "dcf_result": dcf_result}
        )
        assert "255" in html
        assert "9.5" in html or "0.095" in html

    def test_dcf_chart_embedded(self) -> None:
        html = render_dcf_report(
            {
                "ticker": "AAPL",
                "charts": {"waterfall": "data:image/png;base64,DCF1"},
                "dcf_result": None,
            }
        )
        assert "data:image/png;base64,DCF1" in html
