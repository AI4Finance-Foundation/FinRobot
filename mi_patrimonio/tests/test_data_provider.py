"""
Unit tests for data_provider.py module.

Tests cover Quote, HistoricalData dataclasses and DataProvider class.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch


class TestQuote:
    """Tests for the Quote dataclass."""

    def test_create_quote(self):
        """Test creating a Quote from valid data."""
        from data_provider import Quote

        quote = Quote(
            ticker="AAPL",
            price=175.50,
            change_pct=2.5,
            currency="USD",
            timestamp=datetime.now(),
            name="Apple Inc.",
        )

        assert quote.ticker == "AAPL"
        assert quote.price == 175.50
        assert quote.change_pct == 2.5
        assert quote.currency == "USD"
        assert quote.name == "Apple Inc."

    def test_create_quote_without_name(self):
        """Test creating a Quote without optional name."""
        from data_provider import Quote

        quote = Quote(
            ticker="MSFT",
            price=350.00,
            change_pct=-1.2,
            currency="USD",
            timestamp=datetime.now(),
        )

        assert quote.ticker == "MSFT"
        assert quote.name is None


class TestHistoricalData:
    """Tests for the HistoricalData dataclass."""

    def test_create_historical_data(self):
        """Test creating HistoricalData from valid data."""
        from data_provider import HistoricalData

        prices = [100.0, 105.0, 102.0, 108.0]
        dates = [datetime.now() - timedelta(days=i) for i in range(4, 0, -1)]

        historical = HistoricalData(
            ticker="AAPL",
            prices=prices,
            dates=dates,
            return_pct=8.0,
            volatility=15.5,
        )

        assert historical.ticker == "AAPL"
        assert len(historical.prices) == 4
        assert len(historical.dates) == 4
        assert historical.return_pct == 8.0
        assert historical.volatility == 15.5


class TestDataProvider:
    """Tests for the DataProvider class."""

    @pytest.fixture
    def mock_obb(self):
        """Create a mock OpenBB instance."""
        mock = MagicMock()
        return mock

    @pytest.fixture
    def data_provider_with_mock_obb(self, mock_obb):
        """Create DataProvider with mocked OpenBB."""
        with patch.dict("sys.modules", {"openbb": MagicMock()}):
            from data_provider import DataProvider

            provider = DataProvider()
            provider.obb = mock_obb
            return provider

    def test_init_without_openbb(self):
        """Test DataProvider initialization when OpenBB is not installed."""
        with patch.dict("sys.modules", {"openbb": None}):
            with patch("data_provider.DataProvider._init_openbb") as mock_init:
                mock_init.return_value = None
                from data_provider import DataProvider

                # Force reimport to test without OpenBB
                provider = DataProvider()
                provider.obb = None

                assert provider.obb is None
                assert provider.eur_usd_rate == 0.92  # Fallback value

    def test_get_exchange_rate_without_obb(self):
        """Test get_exchange_rate returns fallback when OpenBB not available."""
        from data_provider import DataProvider

        provider = DataProvider()
        provider.obb = None

        rate = provider.get_exchange_rate()
        assert rate == 0.92  # Fallback value

    def test_get_exchange_rate_success(self, data_provider_with_mock_obb, mock_obb):
        """Test successful exchange rate retrieval."""
        # Mock the quote response
        mock_result = MagicMock()
        mock_result.last_price = 1.08  # EUR/USD rate
        mock_obb.equity.price.quote.return_value = MagicMock(results=[mock_result])

        rate = data_provider_with_mock_obb.get_exchange_rate()

        # Should be inverse: 1/1.08 = ~0.926
        assert abs(rate - (1 / 1.08)) < 0.01
        mock_obb.equity.price.quote.assert_called_once_with("EURUSD=X", provider="yfinance")

    def test_get_exchange_rate_handles_exception(self, data_provider_with_mock_obb, mock_obb):
        """Test get_exchange_rate handles exceptions gracefully."""
        mock_obb.equity.price.quote.side_effect = Exception("API Error")

        rate = data_provider_with_mock_obb.get_exchange_rate()

        assert rate == 0.92  # Should return fallback

    def test_get_quote_without_obb(self):
        """Test get_quote returns None when OpenBB not available."""
        from data_provider import DataProvider

        provider = DataProvider()
        provider.obb = None

        quote = provider.get_quote("AAPL")
        assert quote is None

    def test_get_quote_success(self, data_provider_with_mock_obb, mock_obb):
        """Test successful quote retrieval."""
        # Mock the quote response
        mock_result = MagicMock()
        mock_result.last_price = 175.50
        mock_result.change_percent = 2.5
        mock_result.name = "Apple Inc."
        mock_obb.equity.price.quote.return_value = MagicMock(results=[mock_result])

        quote = data_provider_with_mock_obb.get_quote("AAPL")

        assert quote is not None
        assert quote.ticker == "AAPL"
        assert quote.price == 175.50
        assert quote.change_pct == 2.5
        assert quote.currency == "USD"

    def test_get_quote_european_ticker(self, data_provider_with_mock_obb, mock_obb):
        """Test quote retrieval for European ticker (EUR currency)."""
        mock_result = MagicMock()
        mock_result.last_price = 85.50
        mock_result.change_percent = 1.0
        mock_result.name = "iShares MSCI World"
        mock_obb.equity.price.quote.return_value = MagicMock(results=[mock_result])

        quote = data_provider_with_mock_obb.get_quote("IWDA.AS")

        assert quote is not None
        assert quote.currency == "EUR"  # European tickers should be EUR

    def test_get_quote_caching(self, data_provider_with_mock_obb, mock_obb):
        """Test that quotes are cached."""
        mock_result = MagicMock()
        mock_result.last_price = 175.50
        mock_result.change_percent = 2.5
        mock_result.name = "Apple Inc."
        mock_obb.equity.price.quote.return_value = MagicMock(results=[mock_result])

        # First call
        quote1 = data_provider_with_mock_obb.get_quote("AAPL")
        # Second call should use cache
        quote2 = data_provider_with_mock_obb.get_quote("AAPL")

        assert quote1 is not None
        assert quote2 is not None
        # Should only call API once due to caching
        assert mock_obb.equity.price.quote.call_count == 1

    def test_get_quote_handles_exception(self, data_provider_with_mock_obb, mock_obb):
        """Test get_quote handles exceptions gracefully."""
        mock_obb.equity.price.quote.side_effect = Exception("API Error")

        quote = data_provider_with_mock_obb.get_quote("AAPL")

        assert quote is None

    def test_get_quote_no_results(self, data_provider_with_mock_obb, mock_obb):
        """Test get_quote when API returns no results."""
        mock_obb.equity.price.quote.return_value = MagicMock(results=[])

        quote = data_provider_with_mock_obb.get_quote("INVALID")

        assert quote is None

    def test_get_quotes_batch(self, data_provider_with_mock_obb, mock_obb):
        """Test batch quote retrieval."""
        mock_result = MagicMock()
        mock_result.last_price = 100.0
        mock_result.change_percent = 1.0
        mock_result.name = "Test"
        mock_obb.equity.price.quote.return_value = MagicMock(results=[mock_result])

        tickers = ["AAPL", "MSFT", "GOOGL"]
        quotes = data_provider_with_mock_obb.get_quotes_batch(tickers)

        assert len(quotes) == 3
        assert "AAPL" in quotes
        assert "MSFT" in quotes
        assert "GOOGL" in quotes

    def test_get_historical_without_obb(self):
        """Test get_historical returns None when OpenBB not available."""
        from data_provider import DataProvider

        provider = DataProvider()
        provider.obb = None

        historical = provider.get_historical("AAPL")
        assert historical is None

    def test_get_historical_success(self, data_provider_with_mock_obb, mock_obb):
        """Test successful historical data retrieval."""
        # Mock historical data
        mock_results = []
        for i in range(10):
            result = MagicMock()
            result.close = 100.0 + i * 2  # Increasing prices
            result.date = datetime.now() - timedelta(days=10 - i)
            mock_results.append(result)

        mock_obb.equity.price.historical.return_value = MagicMock(results=mock_results)

        historical = data_provider_with_mock_obb.get_historical("AAPL", days=10)

        assert historical is not None
        assert historical.ticker == "AAPL"
        assert len(historical.prices) == 10
        assert historical.return_pct > 0  # Prices increased

    def test_get_historical_handles_exception(self, data_provider_with_mock_obb, mock_obb):
        """Test get_historical handles exceptions gracefully."""
        mock_obb.equity.price.historical.side_effect = Exception("API Error")

        historical = data_provider_with_mock_obb.get_historical("AAPL")

        assert historical is None

    def test_convert_to_eur(self):
        """Test USD to EUR conversion."""
        from data_provider import DataProvider

        provider = DataProvider()
        provider.eur_usd_rate = 0.92

        eur_value = provider.convert_to_eur(100.0)

        assert eur_value == 92.0

    def test_get_market_info(self, data_provider_with_mock_obb, mock_obb):
        """Test market info retrieval."""
        # Mock exchange rate
        mock_rate_result = MagicMock()
        mock_rate_result.last_price = 1.08

        # Mock index quotes
        mock_index_result = MagicMock()
        mock_index_result.last_price = 450.0
        mock_index_result.change_percent = 0.5
        mock_index_result.name = "S&P 500"

        mock_obb.equity.price.quote.return_value = MagicMock(results=[mock_index_result])

        info = data_provider_with_mock_obb.get_market_info()

        assert "timestamp" in info
        assert "eur_usd" in info
        assert "indices" in info

    def test_legacy_method_aliases(self, data_provider_with_mock_obb):
        """Test that legacy method aliases work."""
        from data_provider import DataProvider

        # Check that legacy aliases exist
        assert hasattr(data_provider_with_mock_obb, "obtener_cotizacion")
        assert hasattr(data_provider_with_mock_obb, "obtener_cotizaciones_batch")
        assert hasattr(data_provider_with_mock_obb, "obtener_historico")
        assert hasattr(data_provider_with_mock_obb, "obtener_tipo_cambio")
        assert hasattr(data_provider_with_mock_obb, "convertir_a_eur")

        # They should be the same as the new methods
        assert data_provider_with_mock_obb.obtener_cotizacion == data_provider_with_mock_obb.get_quote
        assert data_provider_with_mock_obb.obtener_tipo_cambio == data_provider_with_mock_obb.get_exchange_rate


class TestGetDataProvider:
    """Tests for the get_data_provider singleton function."""

    def test_get_data_provider_returns_instance(self):
        """Test that get_data_provider returns a DataProvider instance."""
        from data_provider import get_data_provider, DataProvider

        provider = get_data_provider()

        assert isinstance(provider, DataProvider)

    def test_get_data_provider_singleton(self):
        """Test that get_data_provider returns the same instance."""
        from data_provider import get_data_provider

        provider1 = get_data_provider()
        provider2 = get_data_provider()

        assert provider1 is provider2
