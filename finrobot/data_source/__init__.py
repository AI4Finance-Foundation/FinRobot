"""
Data source providers for FinRobot.

This module provides access to various financial data sources including
FinnHub, Yahoo Finance, FMP, SEC filings, and more.

New code should use the provider classes (FinnHubProvider, FMPProvider)
which support dependency injection. Legacy Utils classes are maintained
for backward compatibility.
"""
import importlib.util

# Base classes and configuration
from .base import (
    DataProviderBase,
    MarketDataProvider,
    CompanyDataProvider,
    SECDataProvider,
    Quote,
    HistoricalData,
    CompanyProfile,
    DataProviderError,
)
from .config import (
    ProviderConfig,
    DataSourceConfig,
    get_config,
    set_config,
    reset_config,
)

# New provider implementations (with DI)
from .finnhub_provider import FinnHubProvider, get_finnhub_provider
from .fmp_provider import FMPProvider, get_fmp_provider

# Legacy utilities (backward compatibility)
# These are imported lazily to avoid requiring all dependencies
_FinnHubUtils = None
_YFinanceUtils = None
_FMPUtils = None
_SECUtils = None
_RedditUtils = None


def __getattr__(name: str):
    """Lazy loading for legacy utilities to avoid import errors when dependencies are missing."""
    global _FinnHubUtils, _YFinanceUtils, _FMPUtils, _SECUtils, _RedditUtils

    if name == "FinnHubUtils":
        if _FinnHubUtils is None:
            from .finnhub_utils import FinnHubUtils as _FinnHubUtils
        return _FinnHubUtils
    elif name == "YFinanceUtils":
        if _YFinanceUtils is None:
            from .yfinance_utils import YFinanceUtils as _YFinanceUtils
        return _YFinanceUtils
    elif name == "FMPUtils":
        if _FMPUtils is None:
            from .fmp_utils import FMPUtils as _FMPUtils
        return _FMPUtils
    elif name == "SECUtils":
        if _SECUtils is None:
            from .sec_utils import SECUtils as _SECUtils
        return _SECUtils
    elif name == "RedditUtils":
        if _RedditUtils is None:
            from .reddit_utils import RedditUtils as _RedditUtils
        return _RedditUtils

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Base classes
    "DataProviderBase",
    "MarketDataProvider",
    "CompanyDataProvider",
    "SECDataProvider",
    "Quote",
    "HistoricalData",
    "CompanyProfile",
    "DataProviderError",
    # Configuration
    "ProviderConfig",
    "DataSourceConfig",
    "get_config",
    "set_config",
    "reset_config",
    # New providers
    "FinnHubProvider",
    "FMPProvider",
    "get_finnhub_provider",
    "get_fmp_provider",
    # Legacy utilities
    "FinnHubUtils",
    "YFinanceUtils",
    "FMPUtils",
    "SECUtils",
    "RedditUtils",
]

if importlib.util.find_spec("finnlp") is not None:
    from .finnlp_utils import FinNLPUtils
    __all__.append("FinNLPUtils")
