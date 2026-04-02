from datetime import datetime, timezone
from finagent.engine.data.interface import DataResult
from finagent.engine.compute.news import RawNewsItem, NewsItem, parse_raw_news


class TestParseRawNews:
    def test_converts_data_result_to_raw_news_items(self):
        dr = DataResult(
            data={"news_items": [
                {"title": "Apple beats Q4", "source": "Reuters", "published": "2024-10-31T16:00:00.000Z", "url": "https://example.com/1"},
                {"title": "iPhone strong", "source": "Bloomberg", "published": "2024-10-30T14:00:00.000Z", "url": "https://example.com/2"},
            ]},
            provider="fmp", ticker="AAPL", data_type="news", timestamp=datetime.now(tz=timezone.utc),
        )
        items = parse_raw_news(dr)
        assert len(items) == 2
        assert isinstance(items[0], RawNewsItem)
        assert items[0].title == "Apple beats Q4"
        assert isinstance(items[0].published, datetime)

    def test_empty_news_items(self):
        dr = DataResult(data={"news_items": []}, provider="fmp", ticker="AAPL", data_type="news", timestamp=datetime.now(tz=timezone.utc))
        assert parse_raw_news(dr) == []

    def test_missing_news_items_key(self):
        dr = DataResult(data={}, provider="fmp", ticker="AAPL", data_type="news", timestamp=datetime.now(tz=timezone.utc))
        assert parse_raw_news(dr) == []

    def test_skips_items_without_title(self):
        dr = DataResult(
            data={"news_items": [
                {"title": "", "source": "X", "published": "2024-01-01T00:00:00Z", "url": "x"},
                {"title": "Real headline", "source": "Y", "published": "2024-01-01T00:00:00Z", "url": "y"},
            ]},
            provider="fmp", ticker="AAPL", data_type="news", timestamp=datetime.now(tz=timezone.utc),
        )
        items = parse_raw_news(dr)
        assert len(items) == 1
        assert items[0].title == "Real headline"
