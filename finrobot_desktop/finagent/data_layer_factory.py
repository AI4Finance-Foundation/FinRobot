"""Factory for building a DataLayer from runtime settings.

Extracted from server.py so that routes/settings.py can import it without
creating a circular dependency (server → settings → server).
"""

from __future__ import annotations

from typing import Any

from finagent.engine.data.cache import DataCache
from finagent.engine.data.layer import DataLayer


def build_data_layer(settings: Any) -> DataLayer:
    """Build provider chain from runtime settings."""
    from finagent.engine.data.providers.news_aggregator import NewsAggregatorProvider
    from finagent.engine.data.providers.sec_provider import SECEdgarProvider
    from finagent.engine.data.providers.yfinance_provider import YFinanceProvider

    providers: list[Any] = []
    if settings.fmp_api_key:
        from finagent.engine.data.providers.fmp_provider import FMPProvider

        providers.append(FMPProvider(api_key=settings.fmp_api_key))
    if settings.finnhub_api_key:
        from finagent.engine.data.providers.finnhub_provider import FinnhubProvider

        providers.append(FinnhubProvider(api_key=settings.finnhub_api_key))
    providers.append(YFinanceProvider())
    providers.append(SECEdgarProvider(user_agent=settings.sec_user_agent))

    # News aggregator — always registered; uses Yahoo RSS (free, no key)
    # and Alpha Vantage (only if key is provided). Adds news sources beyond
    # what FMP/Finnhub/yfinance already provide.
    av_key = getattr(settings, "alpha_vantage_api_key", "")
    providers.append(NewsAggregatorProvider(alpha_vantage_api_key=av_key))

    cache = DataCache(settings.cache_db_path)
    return DataLayer(providers=providers, cache=cache)
