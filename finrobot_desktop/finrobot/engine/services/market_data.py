"""Market-data service — price-history payload for the /price route.

收口 to the DataLayer (门一): this no longer touches yfinance directly. It
fetches ``DataType.PRICE`` through the provider chain (FMP → yfinance) via
``DataLayer.fetch_price`` and shapes the route payload. The error-classification
keywords below stay here (locked by tests/audit/test_yfinance_error_mapping.py)
because the route still maps an invalid ticker → 422 vs upstream-down → 502.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from finrobot.engine.data.interface import ProviderError

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
    '429',
    'rate limit',
    'connection',
    'timeout',
    'http error 5',
    'too many requests',
)


def _is_yfinance_service_down(exc: Exception) -> bool:
    """Return True iff exception message indicates upstream failure
    (rate limit, timeout, 5xx) rather than an invalid ticker."""
    msg = str(exc).lower()
    return any(kw in msg for kw in _YFINANCE_SERVICE_DOWN_KEYWORDS)


def _change_from_history(history: list[Any]) -> tuple[float | None, float | None]:
    """Day-over-day change + pct from the last two closes in a price history."""
    closes: list[float] = []
    for row in history:
        if not isinstance(row, dict):
            continue
        raw = row.get("close")
        try:
            closes.append(float(raw))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    if len(closes) < 2:
        return None, None
    prev_close = closes[-2]
    if prev_close == 0:
        return None, None
    change = closes[-1] - prev_close
    return change, (change / prev_close) * 100


async def fetch_price_history(data_layer: DataLayer, ticker: str) -> dict[str, Any]:
    """Fetch current price + ~1y OHLC history via the DataLayer PRICE chain.

    Returns the route payload (current_price, change/change_pct computed from
    history, exchange, history, fetched_at, data_source, warnings). market_cap
    and company_name are left None here and filled by the route from the
    financials cache (``_enrich_price_payload_from_financial_cache``).

    Raises:
        ValueError: invalid / unknown ticker → 422.
        ProviderError: upstream data source down (rate limit / timeout / 5xx) → 502.
    """
    try:
        result = await data_layer.fetch_price(ticker)
    except ProviderError as e:
        if _is_yfinance_service_down(e):
            raise
        # Non-service-down provider error → treat as invalid / unknown ticker.
        raise ValueError(f"未知 ticker '{ticker}': {e}") from e

    raw = result.data if isinstance(result.data, dict) else {}
    current_price = raw.get("current_price")
    history_raw = raw.get("price_history") or raw.get("history") or []
    history = history_raw if isinstance(history_raw, list) else []
    if current_price is None and not history:
        raise ValueError(f"未知 ticker '{ticker}': 无价格数据")

    change, change_pct = _change_from_history(history)
    fetched_at = (
        result.timestamp.isoformat()
        if result.timestamp
        else datetime.now(tz=timezone.utc).isoformat()
    )
    return {
        "current_price": current_price,
        "change": change,
        "change_pct": change_pct,
        # market_cap / company_name are enriched by the route from the
        # financials cache; the PRICE DataResult doesn't carry them.
        "market_cap": None,
        "company_name": None,
        "exchange": raw.get("exchange"),
        # next_earnings_date isn't in the PRICE result; the UI hides the callout
        # when null (same as the route's provider-cache fast path).
        "next_earnings_date": None,
        "history": history,
        "fetched_at": fetched_at,
        "data_source": result.provider,
        "warnings": list(result.warnings),
    }
