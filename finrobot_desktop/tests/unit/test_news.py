from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from finrobot.engine.data.interface import DataResult, ProviderError
from finrobot.engine.data.providers.news_aggregator import NewsAggregatorProvider
from finrobot.engine.compute.news import (
    NewsItem,
    RawNewsItem,
    fetch_news,
    parse_raw_news,
)
from finrobot.engine.analysis.news_classifier import (
    ClassifiedNewsBatch,
    classify_news,
)


class TestParseRawNews:
    def test_converts_data_result_to_raw_news_items(self):
        dr = DataResult(
            data={
                "news_items": [
                    {
                        "title": "Apple beats Q4",
                        "source": "Reuters",
                        "published": "2024-10-31T16:00:00.000Z",
                        "url": "https://example.com/1",
                    },
                    {
                        "title": "iPhone strong",
                        "source": "Bloomberg",
                        "published": "2024-10-30T14:00:00.000Z",
                        "url": "https://example.com/2",
                    },
                ]
            },
            provider="fmp",
            ticker="AAPL",
            data_type="news",
            timestamp=datetime.now(tz=timezone.utc),
        )
        items = parse_raw_news(dr)
        assert len(items) == 2
        assert isinstance(items[0], RawNewsItem)
        assert items[0].title == "Apple beats Q4"
        assert isinstance(items[0].published, datetime)

    def test_empty_news_items(self):
        dr = DataResult(
            data={"news_items": []},
            provider="fmp",
            ticker="AAPL",
            data_type="news",
            timestamp=datetime.now(tz=timezone.utc),
        )
        assert parse_raw_news(dr) == []

    def test_missing_news_items_key(self):
        dr = DataResult(
            data={},
            provider="fmp",
            ticker="AAPL",
            data_type="news",
            timestamp=datetime.now(tz=timezone.utc),
        )
        assert parse_raw_news(dr) == []

    def test_skips_items_without_title(self):
        dr = DataResult(
            data={
                "news_items": [
                    {"title": "", "source": "X", "published": "2024-01-01T00:00:00Z", "url": "x"},
                    {
                        "title": "Real headline",
                        "source": "Y",
                        "published": "2024-01-01T00:00:00Z",
                        "url": "y",
                    },
                ]
            },
            provider="fmp",
            ticker="AAPL",
            data_type="news",
            timestamp=datetime.now(tz=timezone.utc),
        )
        items = parse_raw_news(dr)
        assert len(items) == 1
        assert items[0].title == "Real headline"


class TestFetchNews:
    """Tests for fetch_news — DataLayer integration."""

    @pytest.mark.asyncio
    async def test_fetch_news_returns_raw_items(self):
        """Mock DataLayer.fetch → DataResult → verify list[RawNewsItem] output."""
        mock_data_layer = AsyncMock()
        mock_data_layer.fetch.return_value = DataResult(
            data={
                "news_items": [
                    {
                        "title": "AAPL Q4 beat",
                        "source": "Reuters",
                        "published": "2024-10-31T16:00:00Z",
                        "url": "https://example.com/1",
                    },
                    {
                        "title": "iPhone 16 launch",
                        "source": "Bloomberg",
                        "published": "2024-10-30T14:00:00Z",
                        "url": "https://example.com/2",
                    },
                ]
            },
            provider="yfinance",
            ticker="AAPL",
            data_type="news",
            timestamp=datetime.now(tz=timezone.utc),
        )
        items = await fetch_news(mock_data_layer, "AAPL")
        assert len(items) == 2
        assert all(isinstance(item, RawNewsItem) for item in items)
        assert items[0].title == "AAPL Q4 beat"
        assert items[1].source == "Bloomberg"
        mock_data_layer.fetch.assert_called_once_with("news", "AAPL")

    @pytest.mark.asyncio
    async def test_fetch_news_empty_provider_response(self):
        """Empty news_items from provider → empty list."""
        mock_data_layer = AsyncMock()
        mock_data_layer.fetch.return_value = DataResult(
            data={"news_items": []},
            provider="yfinance",
            ticker="AAPL",
            data_type="news",
            timestamp=datetime.now(tz=timezone.utc),
        )
        items = await fetch_news(mock_data_layer, "AAPL")
        assert items == []

    @pytest.mark.asyncio
    async def test_fetch_news_no_news_key(self):
        """Provider returns DataResult without news_items key → empty list."""
        mock_data_layer = AsyncMock()
        mock_data_layer.fetch.return_value = DataResult(
            data={"error": "no news available"},
            provider="none",
            ticker="AAPL",
            data_type="news",
            timestamp=datetime.now(tz=timezone.utc),
        )
        items = await fetch_news(mock_data_layer, "AAPL")
        assert items == []


class TestClassifyNews:
    """Tests for classify_news — LLM classification with structured output."""

    @pytest.mark.asyncio
    async def test_classify_news_empty_input(self):
        """Empty input list → empty output, no LLM call."""
        mock_deps = MagicMock()
        result = await classify_news([], mock_deps)
        assert result == []

    @pytest.mark.asyncio
    async def test_classify_news_returns_news_items(self):
        """Mock PydanticAI Agent → verify list[NewsItem] output."""
        raw_items = [
            RawNewsItem(
                title="Apple beats Q4 earnings",
                source="Reuters",
                published=datetime(2024, 10, 31, 16, 0, tzinfo=timezone.utc),
                url="https://example.com/1",
            ),
        ]
        expected_items = [
            NewsItem(
                title="Apple beats Q4 earnings",
                source="Reuters",
                published=datetime(2024, 10, 31, 16, 0, tzinfo=timezone.utc),
                url="https://example.com/1",
                category="earnings",
                sentiment="positive",
                importance=4,
                summary="Apple exceeded Q4 earnings expectations.",
            ),
        ]
        mock_output = MagicMock()
        mock_output.output = ClassifiedNewsBatch(items=expected_items)

        mock_deps = MagicMock()
        mock_deps.settings.model_name = "test-model"

        with patch("finrobot.engine.analysis.news_classifier.PydanticAgent") as MockAgent:
            mock_agent_instance = AsyncMock()
            mock_agent_instance.run.return_value = mock_output
            MockAgent.return_value = mock_agent_instance

            result = await classify_news(raw_items, mock_deps)

        assert len(result) == 1
        assert isinstance(result[0], NewsItem)
        assert result[0].category == "earnings"
        assert result[0].sentiment == "positive"
        assert result[0].importance == 4

    @pytest.mark.asyncio
    async def test_classify_news_llm_failure_raises(self):
        """When LLM agent raises, classify_news propagates a RuntimeError.

        We deliberately surface failure instead of silently returning []
        so that downstream callers can distinguish a real LLM outage from
        the legitimate "no catalysts" case.
        """
        from pydantic_ai.exceptions import AgentRunError

        raw_items = [
            RawNewsItem(
                title="Some news",
                source="CNBC",
                published=datetime(2024, 1, 1, tzinfo=timezone.utc),
                url="https://example.com",
            ),
        ]

        mock_deps = MagicMock()
        mock_deps.settings.model_name = "test-model"

        with patch("finrobot.engine.analysis.news_classifier.PydanticAgent") as MockAgent:
            mock_agent_instance = AsyncMock()
            mock_agent_instance.run.side_effect = AgentRunError("LLM failed")
            MockAgent.return_value = mock_agent_instance

            with pytest.raises(RuntimeError, match="News classification failed"):
                await classify_news(raw_items, mock_deps)


class TestNewsAggregatorKeyDoesNotLeak:
    """BUG-003: the Alpha Vantage request URL carries ?apikey=<live key>. An
    HTTP error must surface status + ticker only, never the raw httpx str()."""

    @pytest.mark.asyncio
    async def test_alpha_vantage_http_error_omits_api_key(self):
        provider = NewsAggregatorProvider(alpha_vantage_api_key="LIVEKEY_SHOULD_NOT_LEAK")

        request = httpx.Request(
            "GET",
            "https://www.alphavantage.co/query?function=NEWS_SENTIMENT"
            "&tickers=AAPL&apikey=LIVEKEY_SHOULD_NOT_LEAK",
        )
        response = httpx.Response(429, request=request)

        async def _boom(*_args, **_kwargs):
            raise httpx.HTTPStatusError(
                f"429 for url {request.url}", request=request, response=response
            )

        with patch("httpx.AsyncClient") as MockClient:
            client = MockClient.return_value.__aenter__.return_value
            client.get = AsyncMock(side_effect=_boom)

            with pytest.raises(ProviderError) as exc_info:
                await provider._fetch_alpha_vantage("AAPL")

        msg = str(exc_info.value)
        assert "LIVEKEY_SHOULD_NOT_LEAK" not in msg
        assert "apikey" not in msg.lower()
        assert "429" in msg
        assert "AAPL" in msg

    @pytest.mark.asyncio
    async def test_all_sources_failed_message_omits_api_key(self):
        """When every source fails, the aggregate ProviderError joins each
        failure string — none may carry the key."""
        provider = NewsAggregatorProvider(alpha_vantage_api_key="LIVEKEY_SHOULD_NOT_LEAK")

        av_err = ProviderError("Alpha Vantage HTTP 429 for 'AAPL'")
        yahoo_err = ProviderError("Yahoo RSS HTTP error for 'AAPL'")

        with (
            patch.object(provider, "_fetch_yahoo_rss", AsyncMock(side_effect=yahoo_err)),
            patch.object(provider, "_fetch_alpha_vantage", AsyncMock(side_effect=av_err)),
        ):
            with pytest.raises(ProviderError) as exc_info:
                await provider.fetch("AAPL", "news")

        msg = str(exc_info.value)
        assert "LIVEKEY_SHOULD_NOT_LEAK" not in msg
        assert "All news sources failed" in msg
