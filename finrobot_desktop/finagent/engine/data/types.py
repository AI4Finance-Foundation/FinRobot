from enum import StrEnum


class DataType(StrEnum):
    """Typed constants for all supported data_type values.

    Using StrEnum means DataType values ARE strings — backwards-compatible
    with any code that still passes bare string literals. A typo like
    DataType.FINCANCIALS causes an AttributeError at import time rather than
    silently routing to a provider that returns nothing.
    """

    FINANCIALS = "financials"
    PRICE = "price"
    NEWS = "news"
    EARNINGS = "earnings"
    FILINGS = "filings"
    PROFILE = "profile"
    RAG_10K = "10k_rag"
    EARNINGS_TRANSCRIPT = "earnings_transcript"
    SENTIMENT = "sentiment"
    # Route-level cache types for endpoints that bypass the provider chain
    # (yfinance-only deep financial data — historical multi-year + quarterly).
    HISTORICAL = "historical"
    QUARTERLY = "quarterly"
    # Historical valuation bands (v5 §6.6): EV/EBITDA + P/FCF time series with
    # P25/P75/P90 quantiles. Derived deterministically from price history +
    # quarterly financials; cached separately so the band endpoint can have
    # its own TTL independent of the underlying historical / price types.
    HISTORICAL_BANDS = "historical_bands"
