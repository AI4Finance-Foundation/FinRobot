"""Market-data service — price-history payload for the /price route.

ADR-0006 Step 5: price data now flows through ``DataLayer.fetch_canonical(PRICE)``
and day-over-day change is computed from ``NormalizedPrice.latest_session_change()``
instead of a manual raw-dict parse. The raw ``price_history`` list is still
forwarded to the route response (the frontend chart consumes it) — only the
change/change_pct computation has moved to the canonical method.

收口 to the DataLayer (门一): this no longer touches yfinance directly. It
fetches ``DataType.PRICE`` through the provider chain (FMP → yfinance) via
``DataLayer.fetch_canonical`` and shapes the route payload. The error-classification
keywords below stay here (locked by tests/audit/test_yfinance_error_mapping.py)
because the route still maps an invalid ticker → 422 vs upstream-down → 502.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.types import DataType

if TYPE_CHECKING:
    from finrobot.engine.data.layer import DataLayer

logger = logging.getLogger(__name__)

# yfinance error message keyword list — case-insensitive substring match.
# A provider error whose message contains ANY of these keywords is classified
# as upstream service down (raises ProviderError → 502). Otherwise it's
# treated as invalid ticker (raises ValueError → 422).
#
# Locked by tests/audit/test_yfinance_error_mapping.py — removing a keyword
# requires an audit-reviewer-acknowledged commit.
_YFINANCE_SERVICE_DOWN_KEYWORDS: tuple[str, ...] = (
    "429",
    "rate limit",
    "connection",
    "timeout",
    "http error 5",
    "too many requests",
)


def _is_yfinance_service_down(exc: Exception) -> bool:
    """Return True iff exception message indicates upstream failure
    (rate limit, timeout, 5xx) rather than an invalid ticker."""
    msg = str(exc).lower()
    return any(kw in msg for kw in _YFINANCE_SERVICE_DOWN_KEYWORDS)


async def fetch_price_history(data_layer: DataLayer, ticker: str) -> dict[str, Any]:
    """Fetch current price + ~1y OHLC history via the DataLayer canonical PRICE chain.

    Returns the route payload (current_price, change/change_pct computed from
    NormalizedPrice.latest_session_change(), exchange, history, fetched_at,
    data_source, warnings). market_cap and company_name are left None here and
    filled by the route from the financials cache; the technicals snapshot,
    as_of, and session_state are added by the route's _enrich choke point (so
    the provider-cache fast path carries them too).

    Raises:
        ValueError: invalid / unknown ticker → 422.
        ProviderError: upstream data source down (rate limit / timeout / 5xx) → 502.
    """
    try:
        price = await data_layer.fetch_canonical(DataType.PRICE, ticker)
    except ProviderError as e:
        if _is_yfinance_service_down(e):
            raise
        # Non-service-down provider error → treat as invalid / unknown ticker.
        raise ValueError(f"未知 ticker '{ticker}': {e}") from e

    if not price.bars and not price.current_price:
        raise ValueError(f"未知 ticker '{ticker}': 无价格数据")

    change, change_pct = price.latest_session_change()

    # Reconstruct the raw history list the frontend chart still expects.
    # Bars are already trimmed to trailing 52 weeks and sorted ascending.
    history = [
        {
            "date": b.date.isoformat(),
            "close": b.close,
            **({"open": b.open} if b.open is not None else {}),
            **({"high": b.high} if b.high is not None else {}),
            **({"low": b.low} if b.low is not None else {}),
            **({"volume": b.volume} if b.volume is not None else {}),
        }
        for b in price.bars
    ]

    fetched_at = price.provenance.fetched_at.isoformat()
    return {
        "current_price": price.current_price,
        "change": change,
        "change_pct": change_pct,
        # Observation time from the canonical provenance (quote timestamp →
        # session close chain), so the /price freshness pill matches the Coverage
        # card and reads a real age. The route's _stamp_as_of leaves this as-is.
        "as_of": price.provenance.as_of.isoformat(),
        # market_cap / company_name are enriched by the route from the
        # financials cache; the PRICE canonical doesn't carry them.
        "market_cap": None,
        "company_name": None,
        "exchange": price.exchange,
        # next_earnings_date isn't in the PRICE result; the UI hides the callout
        # when null (same as the route's provider-cache fast path).
        "next_earnings_date": None,
        "history": history,
        "fetched_at": fetched_at,
        "data_source": price.provenance.provider,
        "warnings": list(price.warnings),
    }
