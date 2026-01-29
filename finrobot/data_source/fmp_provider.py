"""
Financial Modeling Prep (FMP) data provider implementation.

Provides financial data, SEC filings, and market data from FMP API.
Uses dependency injection for configuration.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

import requests
import numpy as np

from .base import (
    MarketDataProvider,
    SECDataProvider,
    Quote,
    HistoricalData,
    DataProviderError,
)
from .config import ProviderConfig, get_config

logger = logging.getLogger(__name__)


class FMPProvider(MarketDataProvider, SECDataProvider):
    """
    Financial Modeling Prep API data provider.

    Provides market data, financial statements, and SEC filing access.

    Example:
        # Using global config
        provider = FMPProvider()

        # Using explicit config
        config = ProviderConfig(api_key="your-key")
        provider = FMPProvider(config=config)

        # Get quote
        quote = provider.get_quote("AAPL")
    """

    BASE_URL = "https://financialmodelingprep.com/api"

    def __init__(self, config: Optional[ProviderConfig] = None):
        """
        Initialize FMP provider.

        Args:
            config: Optional explicit configuration.
                   If not provided, uses global config.
        """
        if config is not None:
            self._config = config
        else:
            self._config = get_config().fmp

        self._session = requests.Session()
        self._session.timeout = self._config.timeout

    @property
    def name(self) -> str:
        return "fmp"

    @property
    def api_key(self) -> str:
        """Get API key, raising error if not configured."""
        if not self._config.is_configured:
            raise DataProviderError(
                "FMP API key not configured. "
                "Set FMP_API_KEY environment variable."
            )
        return self._config.api_key

    def is_available(self) -> bool:
        """Check if FMP is configured and available."""
        return self._config.is_configured

    def _make_request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Optional[Any]:
        """
        Make authenticated request to FMP API.

        Args:
            endpoint: API endpoint path
            params: Optional query parameters

        Returns:
            JSON response or None on error
        """
        url = f"{self.BASE_URL}/{endpoint}"
        params = params or {}
        params["apikey"] = self.api_key

        try:
            response = self._session.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error("FMP API request failed: %s", e)
            return None

    def get_quote(self, symbol: str) -> Optional[Quote]:
        """
        Get current quote for a symbol.

        Args:
            symbol: Ticker symbol

        Returns:
            Quote object or None
        """
        data = self._make_request(f"v3/quote/{symbol}")
        if not data or len(data) == 0:
            return None

        quote_data = data[0]
        return Quote(
            symbol=symbol,
            price=quote_data.get("price", 0),
            change_pct=quote_data.get("changesPercentage", 0),
            currency="USD",
            timestamp=datetime.now(),
            name=quote_data.get("name"),
            source=self.name,
        )

    def get_historical(
        self,
        symbol: str,
        days: int = 365
    ) -> Optional[HistoricalData]:
        """
        Get historical price data.

        Args:
            symbol: Ticker symbol
            days: Number of days of history

        Returns:
            HistoricalData object or None
        """
        data = self._make_request(
            f"v3/historical-price-full/{symbol}",
            params={"timeseries": days}
        )

        if not data or "historical" not in data:
            return None

        historical = data["historical"]
        if not historical:
            return None

        prices = [d["close"] for d in reversed(historical)]
        dates = [
            datetime.strptime(d["date"], "%Y-%m-%d")
            for d in reversed(historical)
        ]

        # Calculate return and volatility
        if len(prices) > 1:
            return_pct = ((prices[-1] - prices[0]) / prices[0]) * 100
            returns = np.diff(prices) / prices[:-1]
            volatility = np.std(returns) * np.sqrt(252) * 100  # Annualized
        else:
            return_pct = 0
            volatility = 0

        return HistoricalData(
            symbol=symbol,
            prices=prices,
            dates=dates,
            return_pct=return_pct,
            volatility=volatility,
            source=self.name,
        )

    def get_filing_metadata(
        self,
        symbol: str,
        filing_type: str = "10-K",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get SEC filing metadata.

        Args:
            symbol: Ticker symbol
            filing_type: Type of filing (10-K, 10-Q, etc.)
            start_date: Optional start date filter
            end_date: Optional end date filter

        Returns:
            Filing metadata or None
        """
        data = self._make_request(
            f"v3/sec_filings/{symbol}",
            params={"type": filing_type.lower(), "page": 0}
        )

        if not data or len(data) == 0:
            return None

        # Return most recent filing
        return data[0]

    def get_filing_section(
        self,
        filing_url: str,
        section: str
    ) -> Optional[str]:
        """
        Extract section from filing (requires full filing download).

        Note: FMP provides filing URLs but not section extraction.
        Use SECUtils for section extraction.

        Args:
            filing_url: URL of the filing
            section: Section identifier

        Returns:
            None (not supported directly by FMP)
        """
        logger.warning("Section extraction not supported by FMP. Use SECUtils.")
        return None

    def get_target_price(
        self,
        symbol: str,
        date: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get analyst target prices.

        Args:
            symbol: Ticker symbol
            date: Optional date for historical targets

        Returns:
            Target price data or None
        """
        data = self._make_request(
            "v4/price-target",
            params={"symbol": symbol}
        )

        if not data or len(data) == 0:
            return None

        if date:
            target_date = datetime.strptime(date, "%Y-%m-%d")
            estimates = []
            for item in data:
                pub_date = datetime.strptime(
                    item["publishedDate"].split("T")[0],
                    "%Y-%m-%d"
                )
                if abs((pub_date - target_date).days) <= 365:
                    estimates.append(item["priceTarget"])

            if estimates:
                return {
                    "min": float(np.min(estimates)),
                    "max": float(np.max(estimates)),
                    "median": float(np.median(estimates)),
                    "count": len(estimates),
                }
            return None

        # Return latest target
        latest = data[0]
        return {
            "target": latest.get("priceTarget"),
            "analyst": latest.get("analystName"),
            "company": latest.get("analystCompany"),
            "date": latest.get("publishedDate"),
        }

    def get_financial_ratios(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get financial ratios for a company.

        Args:
            symbol: Ticker symbol

        Returns:
            Dictionary of ratios or None
        """
        data = self._make_request(f"v3/ratios/{symbol}")
        if not data or len(data) == 0:
            return None
        return data[0]

    def get_income_statement(
        self,
        symbol: str,
        period: str = "annual",
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Get income statements.

        Args:
            symbol: Ticker symbol
            period: 'annual' or 'quarter'
            limit: Number of periods

        Returns:
            List of income statements
        """
        data = self._make_request(
            f"v3/income-statement/{symbol}",
            params={"period": period, "limit": limit}
        )
        return data or []


# Backward compatibility
def get_fmp_provider() -> FMPProvider:
    """Get the default FMP provider instance."""
    return FMPProvider()
