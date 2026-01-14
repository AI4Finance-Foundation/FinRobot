"""
Abstract base classes for data providers.

This module defines the interfaces that all data providers must implement,
enabling consistent usage patterns and easier testing through dependency injection.
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class Quote:
    """
    Represents a price quote for a financial instrument.

    Attributes:
        symbol: Ticker symbol (e.g., 'AAPL')
        price: Current price
        change_pct: Percentage change from previous close
        currency: Currency code (e.g., 'USD', 'EUR')
        timestamp: Time of the quote
        name: Optional company/instrument name
        source: Data source identifier
    """
    symbol: str
    price: float
    change_pct: float
    currency: str
    timestamp: datetime
    name: Optional[str] = None
    source: Optional[str] = None


@dataclass
class HistoricalData:
    """
    Represents historical price data for a financial instrument.

    Attributes:
        symbol: Ticker symbol
        prices: List of closing prices
        dates: Corresponding dates for prices
        return_pct: Total return over the period
        volatility: Price volatility (standard deviation of returns)
        source: Data source identifier
    """
    symbol: str
    prices: List[float]
    dates: List[datetime]
    return_pct: float
    volatility: float
    source: Optional[str] = None


@dataclass
class CompanyProfile:
    """
    Represents company profile information.

    Attributes:
        symbol: Ticker symbol
        name: Company name
        industry: Industry classification
        sector: Sector classification
        country: Country of incorporation
        market_cap: Market capitalization
        description: Company description
        website: Company website
        source: Data source identifier
    """
    symbol: str
    name: str
    industry: Optional[str] = None
    sector: Optional[str] = None
    country: Optional[str] = None
    market_cap: Optional[float] = None
    description: Optional[str] = None
    website: Optional[str] = None
    source: Optional[str] = None


class DataProviderError(Exception):
    """Base exception for data provider errors."""
    pass


class DataProviderBase(ABC):
    """
    Abstract base class for all data providers.

    All data providers must implement these core methods to ensure
    consistent interfaces across different data sources.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the name/identifier of this data provider."""
        pass

    @abstractmethod
    def get_quote(self, symbol: str) -> Optional[Quote]:
        """
        Get current price quote for a symbol.

        Args:
            symbol: Ticker symbol (e.g., 'AAPL')

        Returns:
            Quote object or None if not available
        """
        pass

    @abstractmethod
    def get_historical(
        self,
        symbol: str,
        days: int = 365
    ) -> Optional[HistoricalData]:
        """
        Get historical price data for a symbol.

        Args:
            symbol: Ticker symbol
            days: Number of days of history to retrieve

        Returns:
            HistoricalData object or None if not available
        """
        pass

    def is_available(self) -> bool:
        """
        Check if this data provider is available and configured.

        Returns:
            True if provider can be used, False otherwise
        """
        return True


class MarketDataProvider(DataProviderBase):
    """
    Extended interface for market data providers.

    Adds methods for batch operations and market-wide data.
    """

    def get_quotes_batch(
        self,
        symbols: List[str]
    ) -> Dict[str, Quote]:
        """
        Get quotes for multiple symbols.

        Default implementation calls get_quote for each symbol.
        Subclasses may override for more efficient batch operations.

        Args:
            symbols: List of ticker symbols

        Returns:
            Dictionary mapping symbols to Quote objects
        """
        results = {}
        for symbol in symbols:
            quote = self.get_quote(symbol)
            if quote:
                results[symbol] = quote
        return results

    def get_exchange_rate(
        self,
        from_currency: str = "USD",
        to_currency: str = "EUR"
    ) -> Optional[float]:
        """
        Get exchange rate between currencies.

        Args:
            from_currency: Source currency code
            to_currency: Target currency code

        Returns:
            Exchange rate or None if not available
        """
        return None


class CompanyDataProvider(DataProviderBase):
    """
    Extended interface for company information providers.

    Adds methods for company profiles, news, and fundamentals.
    """

    @abstractmethod
    def get_company_profile(self, symbol: str) -> Optional[CompanyProfile]:
        """
        Get company profile information.

        Args:
            symbol: Ticker symbol

        Returns:
            CompanyProfile object or None if not available
        """
        pass

    def get_company_news(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        max_items: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get recent news for a company.

        Args:
            symbol: Ticker symbol
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            max_items: Maximum number of news items

        Returns:
            List of news items as dictionaries
        """
        return []


class SECDataProvider(DataProviderBase):
    """
    Interface for SEC filings data providers.
    """

    @abstractmethod
    def get_filing_metadata(
        self,
        symbol: str,
        filing_type: str = "10-K",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get metadata for SEC filings.

        Args:
            symbol: Ticker symbol
            filing_type: Type of filing (10-K, 10-Q, 8-K, etc.)
            start_date: Optional start date filter
            end_date: Optional end date filter

        Returns:
            Filing metadata or None if not found
        """
        pass

    @abstractmethod
    def get_filing_section(
        self,
        filing_url: str,
        section: str
    ) -> Optional[str]:
        """
        Extract a specific section from a filing.

        Args:
            filing_url: URL of the filing
            section: Section identifier (e.g., '1A' for Risk Factors)

        Returns:
            Section text or None if not found
        """
        pass
