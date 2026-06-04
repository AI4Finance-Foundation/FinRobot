"""Deterministic per-ticker technical snapshot.

What this code does that raw LLM cannot: computes a price-trend snapshot (SMA
20/50/200 stack, trend classification, 52-week range position) from a price
series with repeatable arithmetic — an LLM would produce plausible but
unrepeatable numbers.

门一收口 (ADR-0006 / tests/audit/test_no_direct_yfinance_imports.py): the price
series is pulled via ``DataLayer.fetch_canonical(PRICE)`` — the provider chain
(FMP → yfinance) and the circuit-breaker cover it, and provenance stays honest.
This module never touches yfinance directly.

Leaf-layer rules: no imports from agents/pipelines/orchestrator/pydantic_ai/openai.
It may depend on the data layer (it is a 取数协调器, not a pure operator — ADR-0005).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.normalize.contracts import NormalizedPrice
from finrobot.engine.data.normalize.window import bar_extreme
from finrobot.engine.data.types import DataType

if TYPE_CHECKING:
    from finrobot.engine.data.layer import DataLayer

logger = logging.getLogger(__name__)

# A trend snapshot needs at least the SMA20 window to mean anything; below this
# the series is too short to classify (returns insufficient_history).
_MIN_HISTORY = 20
# 52-week window in trading days (~252). Shorter series use whatever they have.
_WINDOW_52W = 252


def _sma(closes: Sequence[float], window: int) -> float | None:
    """Simple moving average over the last ``window`` closes, or None if the
    series is shorter than the window (the average would be misleading)."""
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def _classify_trend(
    current: float, sma20: float | None, sma50: float | None, sma200: float | None
) -> str:
    """Classify trend from the SMA stack (short→long).

    Fully stacked rising MAs (SMA20 > SMA50 > SMA200) → uptrend; fully stacked
    falling → downtrend; otherwise sideways. With fewer than two MAs available
    (short series) fall back to price-vs-SMA20.
    """
    mas = [m for m in (sma20, sma50, sma200) if m is not None]
    if len(mas) >= 2:
        if all(a > b for a, b in zip(mas, mas[1:], strict=False)):
            return "uptrend"
        if all(a < b for a, b in zip(mas, mas[1:], strict=False)):
            return "downtrend"
        return "sideways"
    ref = mas[0] if mas else current
    if current > ref:
        return "uptrend"
    if current < ref:
        return "downtrend"
    return "sideways"


def technical_payload(history: Sequence[Mapping[str, float | None]]) -> dict[str, Any]:
    """Pure trend snapshot from a bar series (oldest → newest).

    ``history`` is a list of bar-like mappings each carrying a ``close`` and,
    when available, intraday ``high`` / ``low``. Returns ``{"available": False,
    "reason": ...}`` when the series is too short to classify, otherwise a
    snapshot with SMA 20/50/200, trend, current price, and 52-week
    high/low/range-position. No provider access — callers pass bars in.

    The SMA stack and current price use closing prices (the convention for a
    moving-average trend). The 52-week high/low use intraday high/low via the
    canonical ``bar_extreme`` (the same high-or-close fallback as
    ``NormalizedPrice.fifty_two_week_high``, so this snapshot agrees with the
    financials 52W tiles) — that is what Yahoo / Bloomberg report; a close-only
    range understates the high and skews range_position (verified live on AAPL:
    315.00 intraday vs 312.51 close, range_position 0.975 vs 0.996).
    """
    bars: list[tuple[float, float, float]] = []
    for b in history:
        close = bar_extreme(b, "close")
        if close is None:
            continue
        # high/low fall back to close inside bar_extreme, so they are never None
        # once close is present.
        high = bar_extreme(b, "high")
        low = bar_extreme(b, "low")
        assert high is not None and low is not None  # close present ⇒ both resolve
        bars.append((close, high, low))
    if len(bars) < _MIN_HISTORY:
        return {"available": False, "reason": "insufficient_history"}

    closes = [c for c, _, _ in bars]
    current = closes[-1]
    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50)
    sma200 = _sma(closes, 200)

    window = bars[-_WINDOW_52W:]
    high_52w = max(h for _, h, _ in window)
    low_52w = min(lo for _, _, lo in window)
    span = high_52w - low_52w
    range_position = (current - low_52w) / span if span > 0 else None

    return {
        "available": True,
        "trend": _classify_trend(current, sma20, sma50, sma200),
        "current_price": current,
        "sma20": sma20,
        "sma50": sma50,
        "sma200": sma200,
        "high_52w": high_52w,
        "low_52w": low_52w,
        "range_position": range_position,
    }


async def get_technicals(ticker: str, layer: DataLayer) -> dict[str, Any]:
    """Trend snapshot for ``ticker``, pulling the close series via the canonical
    PRICE chain (门一收口 — never yfinance directly).

    Returns ``{"available": False, "reason": "no_data"}`` on a provider failure
    or an empty series; otherwise the :func:`technical_payload` snapshot. This is
    the standalone entry for callers that have only a ticker; callers that
    already hold a ``NormalizedPrice`` should call :func:`technical_payload` on
    its bars to avoid a redundant fetch.
    """
    try:
        price = await layer.fetch_canonical(DataType.PRICE, ticker)
    except ProviderError:
        return {"available": False, "reason": "no_data"}
    if not isinstance(price, NormalizedPrice) or not price.bars:
        return {"available": False, "reason": "no_data"}
    return technical_payload(
        [{"close": bar.close, "high": bar.high, "low": bar.low} for bar in price.bars]
    )
