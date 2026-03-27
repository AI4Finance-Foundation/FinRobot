#!/usr/bin/env python
# coding: utf-8

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from modules.html_template_professional import render_professional_html_report
from modules.retail_sentiment_client import (
    RetailSentimentClient,
    format_retail_sentiment_for_prompt,
)
from modules.html_renderer import format_retail_sentiment_html


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_get_snapshot_aggregates_available_sources(monkeypatch):
    fixtures = {
        "/reddit/stocks/v1/compare": {
            "stocks": [
                {
                    "ticker": "TSLA",
                    "buzz_score": 82.0,
                    "bullish_pct": 58.0,
                    "mentions": 1200,
                    "trend": "rising",
                }
            ]
        },
        "/x/stocks/v1/compare": {
            "stocks": [
                {
                    "ticker": "TSLA",
                    "buzz_score": 76.0,
                    "bullish_pct": 54.0,
                    "mentions": 3400,
                    "trend": "stable",
                }
            ]
        },
        "/polymarket/stocks/v1/compare": {
            "stocks": [
                {
                    "ticker": "TSLA",
                    "buzz_score": 68.0,
                    "bullish_pct": 62.0,
                    "trade_count": 480,
                    "trend": "rising",
                }
            ]
        },
    }

    def fake_get(url, **kwargs):
        path = url.replace("https://api.adanos.org", "")
        assert kwargs["params"]["tickers"] == "TSLA"
        assert kwargs["params"]["days"] == 7
        assert kwargs["headers"]["X-API-Key"] == "test-key"
        return _Response(fixtures[path])

    monkeypatch.setattr("modules.retail_sentiment_client.requests.get", fake_get)

    snapshot = RetailSentimentClient(api_key="test-key").get_snapshot("tsla")

    assert snapshot["ticker"] == "TSLA"
    assert snapshot["coverage"] == "3/3"
    assert snapshot["average_buzz"] == 75.3
    assert snapshot["bullish_avg"] == 58.0
    assert snapshot["source_alignment"] == "Bullish alignment"
    assert [source["key"] for source in snapshot["sources"]] == [
        "reddit",
        "x",
        "polymarket",
    ]


def test_get_snapshot_skips_failed_source(monkeypatch):
    def fake_get(url, **kwargs):
        if "reddit" in url:
            raise RuntimeError("temporary upstream failure")
        if "x" in url:
            return _Response(
                {
                    "stocks": [
                        {
                            "ticker": "MSFT",
                            "buzz_score": 71.0,
                            "bullish_pct": 49.0,
                            "mentions": 900,
                            "trend": "stable",
                        }
                    ]
                }
            )
        return _Response({"stocks": []})

    monkeypatch.setattr("modules.retail_sentiment_client.requests.get", fake_get)

    snapshot = RetailSentimentClient(api_key="test-key").get_snapshot("MSFT")

    assert snapshot["coverage"] == "1/3"
    assert snapshot["average_buzz"] == 71.0
    assert snapshot["bullish_avg"] == 49.0
    assert snapshot["source_alignment"] == "Single-source signal"
    assert snapshot["sources"][0]["has_data"] is False
    assert snapshot["sources"][1]["has_data"] is True


def test_prompt_formatter_renders_retail_sentiment_snapshot():
    prompt_block = format_retail_sentiment_for_prompt(
        {
            "average_buzz": 73.9,
            "bullish_avg": 57.1,
            "source_alignment": "Partial divergence",
            "coverage": "2/3",
            "sources": [
                {
                    "label": "Reddit",
                    "buzz_score": 81.0,
                    "bullish_pct": 61.0,
                    "activity_label": "Mentions",
                    "activity_value": 1450,
                    "trend": "rising",
                    "has_data": True,
                },
                {
                    "label": "Polymarket",
                    "buzz_score": 66.8,
                    "bullish_pct": 53.2,
                    "activity_label": "Trades",
                    "activity_value": 320,
                    "trend": "stable",
                    "has_data": True,
                },
            ],
        }
    )

    assert "## Retail Sentiment Insights" in prompt_block
    assert "Average Buzz: 73.9/100" in prompt_block
    assert "Bullish Avg: 57.1%" in prompt_block
    assert "Source Alignment: Partial divergence" in prompt_block
    assert "Reddit: buzz 81.0/100, bullish 61.0%, mentions 1450, trend rising" in prompt_block
    assert "Polymarket: buzz 66.8/100, bullish 53.2%, trades 320, trend stable" in prompt_block


def test_html_formatter_renders_retail_sentiment_block():
    html = format_retail_sentiment_html(
        {
            "average_buzz": 70.3,
            "bullish_avg": 52.4,
            "source_alignment": "Neutral alignment",
            "coverage": "2/3",
            "sources": [
                {
                    "label": "Reddit",
                    "buzz_score": 72.0,
                    "bullish_pct": 49.0,
                    "activity_label": "Mentions",
                    "activity_value": 840,
                    "trend": "stable",
                    "has_data": True,
                }
            ],
        }
    )

    assert "Retail Sentiment Insights" in html
    assert "Average Buzz: 70.3/100" in html
    assert "Source Alignment: Neutral alignment" in html
    assert "Reddit" in html


def test_professional_report_renders_retail_sentiment_section():
    html = render_professional_html_report(
        {
            "company_name_full": "Tesla, Inc.",
            "company_ticker": "TSLA",
            "share_price": "$180.00",
            "target_price": "$210.00",
            "news_summary": "Recent developments remain mixed.",
            "retail_sentiment": {
                "average_buzz": 74.4,
                "bullish_avg": 58.8,
                "source_alignment": "Bullish alignment",
                "coverage": "2/3",
                "sources": [
                    {
                        "label": "Reddit",
                        "buzz_score": 79.1,
                        "bullish_pct": 55.0,
                        "activity_label": "Mentions",
                        "activity_value": 1220,
                        "trend": "rising",
                        "has_data": True,
                    }
                ],
            },
        }
    )

    assert "Retail Sentiment Insights" in html
    assert "Average Buzz" in html
    assert "74.4/100" in html
    assert "Bullish alignment" in html
