"""
Market Data Provider (OpenBB + Yahoo Finance).

Centralizes all calls to financial data APIs.
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from dataclasses import dataclass

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DataProvider")


@dataclass
class Quote:
    """Asset quote with current price data."""
    ticker: str
    price: float
    change_pct: float
    currency: str
    timestamp: datetime
    name: Optional[str] = None


@dataclass
class HistoricalData:
    """Historical data for an asset."""
    ticker: str
    prices: List[float]
    dates: List[datetime]
    return_pct: float
    volatility: float


class DataProvider:
    """
    Market data provider using OpenBB.
    Centralizes all calls to financial data APIs.
    """

    def __init__(self):
        self.cache: Dict = {}
        self.cache_duration = timedelta(minutes=5)
        self.eur_usd_rate = 0.92  # Fallback
        self._init_openbb()

    def _init_openbb(self):
        """Initialize OpenBB."""
        try:
            from openbb import obb
            self.obb = obb
            logger.info("✅ OpenBB initialized successfully")
        except ImportError:
            logger.error("❌ OpenBB not installed. Run: pip install openbb")
            self.obb = None

    def get_exchange_rate(self) -> float:
        """
        Get real-time EUR/USD exchange rate.
        Returns how many EUR 1 USD is worth.
        """
        if not self.obb:
            return self.eur_usd_rate

        try:
            logger.info("💱 Fetching EUR/USD exchange rate...")
            quote = self.obb.equity.price.quote("EURUSD=X", provider="yfinance")

            if quote and len(quote.results) > 0:
                q = quote.results[0]
                # EURUSD=X gives how many USD 1 EUR is worth, we need the inverse
                rate = getattr(q, 'last_price', None) or getattr(q, 'prev_close', None)
                if rate:
                    self.eur_usd_rate = 1 / rate  # Invert to get EUR per USD
                    logger.info(f"✅ Exchange rate: 1 USD = {self.eur_usd_rate:.4f} EUR")

            return self.eur_usd_rate

        except Exception as e:
            logger.warning(f"⚠️ Error fetching exchange rate: {e}")
            return self.eur_usd_rate

    def get_quote(self, ticker: str) -> Optional[Quote]:
        """
        Get current quote for an asset.

        Args:
            ticker: Asset symbol (e.g., "AAPL", "IWDA.AS", "BTC-USD")

        Returns:
            Quote with current price or None if error
        """
        if not self.obb:
            return None

        # Check cache
        cache_key = f"quote_{ticker}"
        if cache_key in self.cache:
            cached, timestamp = self.cache[cache_key]
            if datetime.now() - timestamp < self.cache_duration:
                return cached

        try:
            logger.info(f"📊 Fetching quote for {ticker}...")
            quote = self.obb.equity.price.quote(ticker, provider='yfinance')

            if quote and len(quote.results) > 0:
                q = quote.results[0]
                price = getattr(q, 'last_price', None) or getattr(q, 'prev_close', None)
                change = getattr(q, 'change_percent', 0) or 0
                name = getattr(q, 'name', ticker)

                if price:
                    result = Quote(
                        ticker=ticker,
                        price=price,
                        change_pct=change,
                        currency='USD' if not ticker.endswith(('.AS', '.DE', '.MC', '.PA')) else 'EUR',
                        timestamp=datetime.now(),
                        name=name
                    )
                    self.cache[cache_key] = (result, datetime.now())
                    logger.info(f"✅ {ticker}: ${price:.2f} ({change:+.2f}%)")
                    return result

        except Exception as e:
            logger.error(f"❌ Error fetching {ticker}: {e}")

        return None

    def get_quotes_batch(self, tickers: List[str]) -> Dict[str, Quote]:
        """
        Get quotes for multiple assets.

        Args:
            tickers: List of symbols

        Returns:
            Dictionary ticker -> Quote
        """
        results = {}
        for ticker in tickers:
            quote = self.get_quote(ticker)
            if quote:
                results[ticker] = quote
        return results

    def get_historical(self, ticker: str, days: int = 365) -> Optional[HistoricalData]:
        """
        Get historical data for an asset.

        Args:
            ticker: Asset symbol
            days: Number of days to look back

        Returns:
            HistoricalData with prices and metrics
        """
        if not self.obb:
            return None

        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)

            logger.info(f"📈 Fetching historical data for {ticker} ({days} days)...")

            hist = self.obb.equity.price.historical(
                ticker,
                start_date=start_date.strftime('%Y-%m-%d'),
                end_date=end_date.strftime('%Y-%m-%d'),
                provider='yfinance'
            )

            if hist and len(hist.results) > 0:
                prices = [r.close for r in hist.results if r.close]
                dates = [r.date for r in hist.results if r.close]

                if len(prices) > 1:
                    # Calculate return
                    return_pct = ((prices[-1] / prices[0]) - 1) * 100

                    # Calculate annualized volatility
                    import numpy as np
                    returns = np.diff(prices) / prices[:-1]
                    volatility = np.std(returns) * np.sqrt(252) * 100

                    return HistoricalData(
                        ticker=ticker,
                        prices=prices,
                        dates=dates,
                        return_pct=return_pct,
                        volatility=volatility
                    )

        except Exception as e:
            logger.error(f"❌ Error fetching historical data for {ticker}: {e}")

        return None

    def convert_to_eur(self, value_usd: float) -> float:
        """Convert USD to EUR using the current exchange rate."""
        return value_usd * self.eur_usd_rate

    def get_market_info(self) -> Dict:
        """
        Get general market information.

        Returns:
            Dictionary with main indices
        """
        indices = {
            'SPY': 'S&P 500',
            'QQQ': 'Nasdaq 100',
            'EWG': 'DAX (Germany)',
            'EWQ': 'CAC 40 (France)',
        }

        info = {
            'timestamp': datetime.now().isoformat(),
            'eur_usd': self.get_exchange_rate(),
            'indices': {}
        }

        for ticker, name in indices.items():
            quote = self.get_quote(ticker)
            if quote:
                info['indices'][name] = {
                    'price': quote.price,
                    'change_pct': quote.change_pct
                }

        return info

    # Legacy method aliases for backward compatibility
    obtener_tipo_cambio = get_exchange_rate
    obtener_cotizacion = get_quote
    obtener_cotizaciones_batch = get_quotes_batch
    obtener_historico = get_historical
    convertir_a_eur = convert_to_eur
    obtener_info_mercado = get_market_info


# Singleton for global use
_data_provider: Optional[DataProvider] = None


def get_data_provider() -> DataProvider:
    """Get the singleton DataProvider instance."""
    global _data_provider
    if _data_provider is None:
        _data_provider = DataProvider()
    return _data_provider

