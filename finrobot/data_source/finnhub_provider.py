"""
FinnHub data provider implementation.

Provides company profiles, news, and market data from FinnHub API.
Uses dependency injection for configuration.
"""
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

import pandas as pd

from .base import (
    CompanyDataProvider,
    CompanyProfile,
    Quote,
    HistoricalData,
    DataProviderError,
)
from .config import ProviderConfig, get_config

logger = logging.getLogger(__name__)


class FinnHubProvider(CompanyDataProvider):
    """
    FinnHub API data provider.

    Provides company profiles, news, and financial metrics.

    Example:
        # Using global config
        provider = FinnHubProvider()

        # Using explicit config
        config = ProviderConfig(api_key="your-key")
        provider = FinnHubProvider(config=config)

        # Get company profile
        profile = provider.get_company_profile("AAPL")
    """

    def __init__(self, config: Optional[ProviderConfig] = None):
        """
        Initialize FinnHub provider.

        Args:
            config: Optional explicit configuration.
                   If not provided, uses global config.
        """
        if config is not None:
            self._config = config
        else:
            self._config = get_config().finnhub

        self._client = None

    @property
    def name(self) -> str:
        return "finnhub"

    @property
    def client(self):
        """Lazy initialization of FinnHub client."""
        if self._client is None:
            if not self._config.is_configured:
                raise DataProviderError(
                    "FinnHub API key not configured. "
                    "Set FINNHUB_API_KEY environment variable."
                )
            try:
                import finnhub
                self._client = finnhub.Client(api_key=self._config.api_key)
                logger.info("FinnHub client initialized")
            except ImportError:
                raise DataProviderError(
                    "finnhub-python package not installed. "
                    "Install with: pip install finnhub-python"
                )
        return self._client

    def is_available(self) -> bool:
        """Check if FinnHub is configured and available."""
        return self._config.is_configured

    def get_quote(self, symbol: str) -> Optional[Quote]:
        """
        Get current quote for a symbol.

        Args:
            symbol: Ticker symbol

        Returns:
            Quote object or None
        """
        try:
            data = self.client.quote(symbol)
            if not data or data.get("c") is None:
                return None

            return Quote(
                symbol=symbol,
                price=data["c"],  # Current price
                change_pct=data.get("dp", 0),  # Daily percent change
                currency="USD",
                timestamp=datetime.now(),
                source=self.name,
            )
        except Exception as e:
            logger.error("Error fetching quote for %s: %s", symbol, e)
            return None

    def get_historical(
        self,
        symbol: str,
        days: int = 365
    ) -> Optional[HistoricalData]:
        """
        Get historical data (not fully supported by basic FinnHub plan).

        Args:
            symbol: Ticker symbol
            days: Number of days

        Returns:
            HistoricalData or None
        """
        # FinnHub requires premium for historical data
        logger.warning("Historical data requires FinnHub premium subscription")
        return None

    def get_company_profile(self, symbol: str) -> Optional[CompanyProfile]:
        """
        Get company profile information.

        Args:
            symbol: Ticker symbol

        Returns:
            CompanyProfile object or None
        """
        try:
            data = self.client.company_profile2(symbol=symbol)
            if not data:
                logger.warning("No profile found for %s", symbol)
                return None

            return CompanyProfile(
                symbol=symbol,
                name=data.get("name", ""),
                industry=data.get("finnhubIndustry"),
                sector=None,  # FinnHub doesn't provide sector
                country=data.get("country"),
                market_cap=data.get("marketCapitalization"),
                description=None,
                website=data.get("weburl"),
                source=self.name,
            )
        except Exception as e:
            logger.error("Error fetching profile for %s: %s", symbol, e)
            return None

    def get_company_news(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        max_items: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get company news.

        Args:
            symbol: Ticker symbol
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            max_items: Maximum news items to return

        Returns:
            List of news items
        """
        try:
            news = self.client.company_news(symbol, _from=start_date, to=end_date)
            if not news:
                logger.info("No news found for %s", symbol)
                return []

            return [
                {
                    "date": datetime.fromtimestamp(n["datetime"]).strftime("%Y-%m-%d %H:%M"),
                    "headline": n.get("headline", ""),
                    "summary": n.get("summary", ""),
                    "source": n.get("source", ""),
                    "url": n.get("url", ""),
                }
                for n in news[:max_items]
            ]
        except Exception as e:
            logger.error("Error fetching news for %s: %s", symbol, e)
            return []

    def get_basic_financials(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get basic financial metrics.

        Args:
            symbol: Ticker symbol

        Returns:
            Dictionary of financial metrics or None
        """
        try:
            data = self.client.company_basic_financials(symbol, "all")
            if not data or "metric" not in data:
                return None

            return data["metric"]
        except Exception as e:
            logger.error("Error fetching financials for %s: %s", symbol, e)
            return None

    def get_recommendation_trends(self, symbol: str) -> List[Dict[str, Any]]:
        """
        Get analyst recommendation trends.

        Args:
            symbol: Ticker symbol

        Returns:
            List of recommendation data by period
        """
        try:
            data = self.client.recommendation_trends(symbol)
            return data or []
        except Exception as e:
            logger.error("Error fetching recommendations for %s: %s", symbol, e)
            return []


# Backward compatibility - create default instance
def get_finnhub_provider() -> FinnHubProvider:
    """Get the default FinnHub provider instance."""
    return FinnHubProvider()
