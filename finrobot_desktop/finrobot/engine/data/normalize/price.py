"""normalize_price: raw provider price DataResult → canonical NormalizedPrice.

Trims to the trailing 52 calendar weeks, builds typed bars, detects whether the
feed carries intraday OHLC (close-only feeds get a ``close_only`` degraded
marker), and stamps provenance whose ``as_of`` is the latest bar's date — the
data's semantic time, so the freshness pill can't claim "实时" over a stale close.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any

from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.normalize.contracts import (
    DEGRADED_CLOSE_ONLY,
    DEGRADED_PRICE_FALLBACK_CLOSE,
    NormalizedPrice,
    PriceBar,
    Provenance,
)
from finrobot.engine.data.normalize.window import bar_date, trim_to_trailing_window


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _date_to_dt(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


def normalize_price(result: DataResult) -> NormalizedPrice:
    data = result.data if isinstance(result.data, dict) else {}
    raw_hist = data.get("price_history") or data.get("history") or []
    windowed = trim_to_trailing_window([b for b in raw_hist if isinstance(b, dict)])

    bars: list[PriceBar] = []
    ohlc_complete = True
    for b in windowed:
        d = bar_date(b)
        close = _f(b.get("close"))
        if d is None or close is None:
            continue
        high, low = _f(b.get("high")), _f(b.get("low"))
        if high is None or low is None:
            ohlc_complete = False
        bars.append(
            PriceBar(
                date=d,
                close=close,
                open=_f(b.get("open")),
                high=high,
                low=low,
                volume=_f(b.get("volume")),
            )
        )
    bars.sort(key=lambda x: x.date)
    if not bars:
        ohlc_complete = False

    current_price = _f(data.get("current_price"))
    price_fell_back_to_close = current_price is None and bool(bars)
    if price_fell_back_to_close:
        current_price = bars[-1].close

    degraded: list[str] = []
    if not ohlc_complete:
        degraded.append(DEGRADED_CLOSE_ONLY)
    if price_fell_back_to_close:
        # The "current" price is actually the latest bar's close — flag it so the
        # UI freshness pill won't present a stale close as a live "实时" quote.
        degraded.append(DEGRADED_PRICE_FALLBACK_CLOSE)

    as_of = _date_to_dt(bars[-1].date) if bars else result.timestamp
    provenance = Provenance(
        provider=result.provider,
        as_of=as_of,
        fetched_at=result.timestamp,
        degraded=degraded,
    )
    return NormalizedPrice(
        ticker=result.ticker,
        quote_currency=(data.get("quote_currency") or "USD").upper(),
        bars=bars,
        current_price=current_price if current_price is not None else 0.0,
        is_ohlc_complete=ohlc_complete,
        exchange=data.get("exchange"),
        provenance=provenance,
    )
