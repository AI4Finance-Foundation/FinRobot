"""The single trailing-52-week calendar window implementation (ADR-0004).

Before this module the window logic lived in three places with the same
invariant re-implemented each time: ``extractor.py`` (max/min of an assumed
52-week array), ``fmp_provider.py`` (a fetch-side day count), and the frontend
sparkline (a -365-day anchor). Providers don't all return exactly one year —
FMP's ``timeseries=N`` counts *trading* days (365 ≈ 17 months), which dragged
pre-window lows into the 52-week low. Centralizing it here means the calendar
window is computed once and everyone downstream consumes the result.

Windowing is anchored on the most recent bar's date, not wall-clock now, so
cached/replayed history stays correct.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any

# 52 weeks + a leap-day cushion. Calendar days, not trading days.
FIFTY_TWO_WEEK_DAYS = 366


def bar_date(bar: dict[str, Any]) -> date | None:
    raw = bar.get("date")
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, str) and raw:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None
    return None


def trim_to_trailing_window(
    bars: list[dict[str, Any]],
    days: int = FIFTY_TWO_WEEK_DAYS,
) -> list[dict[str, Any]]:
    """Keep only bars within ``days`` calendar days of the most recent dated bar.

    Undated histories pass through unchanged (we never silently drop data we
    can't place in time). Ordering is preserved.
    """
    dated = [(d, b) for b in bars if (d := bar_date(b)) is not None]
    if not dated:
        return list(bars)
    cutoff = max(d for d, _ in dated) - timedelta(days=days)
    return [b for d, b in dated if d >= cutoff]


def bar_extreme(bar: Mapping[str, Any], field: str) -> float | None:
    """Intraday ``high``/``low`` when present, else the close.

    Close-only feeds (legacy FMP serietype=line, cached rows) keep working;
    OHLC feeds yield the true intraday extremes brokers display.
    """
    for key in (field, "close"):
        val = bar.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None
