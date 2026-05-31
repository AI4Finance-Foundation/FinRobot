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
    # Lightweight current-price-only quote (dashboard tiles, batched warmup).
    # Distinct from PRICE — PRICE pulls a full ~1y OHLC history per ticker,
    # which is a perf regression for high-fan-out dashboard quotes. QUOTE maps
    # to yfinance fast_info.last_price / FMP /quote and returns just {"price"}.
    QUOTE = "quote"
    NEWS = "news"
    EARNINGS = "earnings"
    # FILINGS retained as alias to FILINGS_10K (2026-05 EdgarTools migration).
    # Cache layer treats both keys as the same slot (verified in
    # tests/unit/test_datatype_alias.py) so a 7d TTL doesn't get double-paid
    # when callers mix the two during the deprecation window.
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
    # ────────────────────────────────────────────────────────────────
    # SEC EDGAR primary data layer (added 2026-05-27 / EdgarTools 5.31).
    # See specs/research/EdgarTools5集成评估-2026-05-27.md §4 门 2.
    # ────────────────────────────────────────────────────────────────
    FILINGS_10K = "filings_10k"  # 10-K annual report (replaces legacy FILINGS)
    FILINGS_10Q = "filings_10q"  # 10-Q quarterly report
    FILINGS_8K = "filings_8k"  # 8-K material event (CurrentReport in edgartools)
    XBRL_FACTS = "xbrl_facts"  # standardized us-gaap concepts (cross-company aligned)
    INSIDER_TRADES = "insider_trades"  # Form 4 — insider transactions
    INSTITUTIONAL_HOLDINGS = "institutional_holdings"  # 13F — via local cache (no reverse API)
    PROXY_STATEMENT = "proxy_statement"  # DEF 14A — executive compensation / governance
    # Analyst consensus forward estimates (FMP /v3/analyst-estimates). Feeds the
    # one-true forward EPS / EBITDA / FCF leaf (compute/forward_estimates.py) so
    # the Football Field forward-multiple rows stop degrading to trailing.
    FORWARD_ESTIMATES = "forward_estimates"
