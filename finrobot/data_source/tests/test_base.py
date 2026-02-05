"""
Tests for the base data provider classes.
"""
import sys
import os

# Add parent directory for direct module imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import datetime

from base import (
    Quote,
    HistoricalData,
    CompanyProfile,
    DataProviderBase,
    MarketDataProvider,
    CompanyDataProvider,
    DataProviderError,
)


class TestQuote:
    """Tests for Quote dataclass."""

    def test_create_quote(self):
        quote = Quote(
            symbol="AAPL",
            price=175.50,
            change_pct=2.5,
            currency="USD",
            timestamp=datetime.now(),
        )
        assert quote.symbol == "AAPL"
        assert quote.price == 175.50
        assert quote.change_pct == 2.5
        assert quote.currency == "USD"

    def test_quote_with_optional_fields(self):
        quote = Quote(
            symbol="MSFT",
            price=350.00,
            change_pct=-1.0,
            currency="USD",
            timestamp=datetime.now(),
            name="Microsoft Corporation",
            source="test",
        )
        assert quote.name == "Microsoft Corporation"
        assert quote.source == "test"


class TestHistoricalData:
    """Tests for HistoricalData dataclass."""

    def test_create_historical_data(self):
        data = HistoricalData(
            symbol="AAPL",
            prices=[100.0, 105.0, 110.0],
            dates=[datetime(2024, 1, i) for i in range(1, 4)],
            return_pct=10.0,
            volatility=15.0,
        )
        assert data.symbol == "AAPL"
        assert len(data.prices) == 3
        assert len(data.dates) == 3
        assert data.return_pct == 10.0


class TestCompanyProfile:
    """Tests for CompanyProfile dataclass."""

    def test_create_profile(self):
        profile = CompanyProfile(
            symbol="AAPL",
            name="Apple Inc.",
            industry="Consumer Electronics",
            country="US",
        )
        assert profile.symbol == "AAPL"
        assert profile.name == "Apple Inc."
        assert profile.industry == "Consumer Electronics"


class TestDataProviderBase:
    """Tests for DataProviderBase abstract class."""

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            DataProviderBase()

    def test_concrete_implementation(self):
        class ConcreteProvider(DataProviderBase):
            @property
            def name(self):
                return "test"

            def get_quote(self, symbol):
                return Quote(
                    symbol=symbol,
                    price=100.0,
                    change_pct=0.0,
                    currency="USD",
                    timestamp=datetime.now(),
                )

            def get_historical(self, symbol, days=365):
                return None

        provider = ConcreteProvider()
        assert provider.name == "test"
        assert provider.is_available() is True

        quote = provider.get_quote("AAPL")
        assert quote.symbol == "AAPL"


class TestMarketDataProvider:
    """Tests for MarketDataProvider interface."""

    def test_batch_quotes_default_implementation(self):
        class TestProvider(MarketDataProvider):
            @property
            def name(self):
                return "test"

            def get_quote(self, symbol):
                return Quote(
                    symbol=symbol,
                    price=100.0,
                    change_pct=0.0,
                    currency="USD",
                    timestamp=datetime.now(),
                )

            def get_historical(self, symbol, days=365):
                return None

        provider = TestProvider()
        quotes = provider.get_quotes_batch(["AAPL", "MSFT"])

        assert len(quotes) == 2
        assert "AAPL" in quotes
        assert "MSFT" in quotes

    def test_exchange_rate_default_returns_none(self):
        class TestProvider(MarketDataProvider):
            @property
            def name(self):
                return "test"

            def get_quote(self, symbol):
                return None

            def get_historical(self, symbol, days=365):
                return None

        provider = TestProvider()
        rate = provider.get_exchange_rate()
        assert rate is None


class TestDataProviderError:
    """Tests for DataProviderError exception."""

    def test_raise_error(self):
        with pytest.raises(DataProviderError):
            raise DataProviderError("Test error")

    def test_error_message(self):
        error = DataProviderError("API key missing")
        assert str(error) == "API key missing"
