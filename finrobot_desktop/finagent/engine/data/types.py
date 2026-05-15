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
