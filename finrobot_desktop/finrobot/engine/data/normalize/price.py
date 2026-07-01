"""normalize_price: raw provider price DataResult → canonical NormalizedPrice.

Trims to the trailing 52 calendar weeks, builds typed bars, detects whether the
feed carries intraday OHLC (close-only feeds get a ``close_only`` degraded
marker), and stamps provenance whose ``as_of`` is the quote's authoritative
observation instant (provider ``quote_timestamp``) — falling back to the latest
bar's SESSION CLOSE, never its midnight — so the freshness pill reports a real
age instead of overstating it by the hours from midnight to the close (~20h).
"""

from __future__ import annotations

import math
from datetime import date, datetime, time, timezone
from typing import Any

from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.normalize.contracts import (
    DEGRADED_CLOSE_ONLY,
    DEGRADED_PRICE_FALLBACK_CLOSE,
    DEGRADED_QUOTE_CURRENCY_MISSING,
    DEGRADED_QUOTE_TS_MISSING,
    NormalizedPrice,
    PriceBar,
    Provenance,
)
from finrobot.engine.data.normalize.session import derive_price_as_of
from finrobot.engine.data.normalize.window import bar_date, trim_to_trailing_window


def _f(v: Any) -> float | None:
    """Scalar → finite float, else None. NaN/±Inf are missing data, not values:
    a NaN close slips every ``is None`` gate, serializes to null, and crashes
    chart consumers (yfinance handed an all-NaN OHLC session row, 2026-06-11).
    守 None ≠ 守 finiteness — the canonical chokepoint must check both."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _date_to_dt(d: date) -> datetime:
    """A bare date → UTC midnight. The honest ``as_of`` for an accounting
    period_end (a calendar boundary, not a clock instant) — reused by
    ``normalize_financials``. Price ``as_of`` does NOT use this: a quote belongs
    to its trade instant / session close, not midnight (see ``derive_price_as_of``)."""
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
    if current_price is None:
        # No quote AND no usable bars — there is no honest price to
        # canonicalize. Refuse instead of fabricating: the old 0.0 fallback
        # flowed a $0 quote into the versioned canonical PRICE slot, where it
        # read as a real price for the whole TTL (报错一个数字砸招牌).
        raise ValueError(
            f"Cannot normalize PRICE for {result.ticker}: provider payload has "
            f"neither current_price nor any usable price bars "
            f"(provider={result.provider})."
        )

    degraded: list[str] = []
    if not ohlc_complete:
        degraded.append(DEGRADED_CLOSE_ONLY)
    if price_fell_back_to_close:
        # The "current" price is actually the latest bar's close — flag it so the
        # UI freshness pill won't present a stale close as a live "实时" quote.
        degraded.append(DEGRADED_PRICE_FALLBACK_CLOSE)

    as_of, as_of_approximate = derive_price_as_of(
        data.get("quote_timestamp"),
        bars[-1].date if bars else None,
        ticker=result.ticker,
        exchange=data.get("exchange"),
        fetched_at=result.timestamp,
    )
    if as_of_approximate and bars:
        # Provider gave no quote timestamp; as_of was inferred from the bar's
        # session close. The number is real — only its observation time is
        # accurate to the session, not the minute.
        degraded.append(DEGRADED_QUOTE_TS_MISSING)
    raw_quote_currency = data.get("quote_currency")
    quote_currency = (
        raw_quote_currency.strip().upper()
        if isinstance(raw_quote_currency, str) and raw_quote_currency.strip()
        else "UNKNOWN"
    )
    if quote_currency == "UNKNOWN":
        degraded.append(DEGRADED_QUOTE_CURRENCY_MISSING)
    provenance = Provenance(
        provider=result.provider,
        as_of=as_of,
        fetched_at=result.timestamp,
        degraded=degraded,
    )
    market_state = data.get("market_state")
    return NormalizedPrice(
        ticker=result.ticker,
        quote_currency=quote_currency,
        bars=bars,
        current_price=current_price,
        is_ohlc_complete=ohlc_complete,
        exchange=data.get("exchange"),
        # Carried verbatim (str | None); SessionState is derived at read time, not
        # here — session phase is time-varying and must never be baked into the
        # canonical cache (a 15:59 ET "live" would still read live at 16:14).
        market_state=market_state if isinstance(market_state, str) else None,
        provenance=provenance,
    )
