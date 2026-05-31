"""Deterministic per-ticker market-data helpers.

What this code does that raw LLM cannot:
- Computes a price-trend snapshot (SMA 20/50/200 stack, trend classification,
  52-week range position) from a close series with repeatable arithmetic — an
  LLM would produce plausible but unrepeatable numbers.
- Hits FMP /v3/earning_calendar for forward-looking events with typed output;
  an LLM cannot produce a correctly dated forward earnings calendar.

门一收口 (ADR-0006 / tests/audit/test_no_direct_yfinance.py): the price series
for technicals is pulled via ``DataLayer.fetch_canonical(PRICE)`` — the provider
chain (FMP → yfinance) and the circuit-breaker cover it, and provenance stays
honest. This module never touches yfinance directly.

Leaf-layer rules: no imports from agents/pipelines/orchestrator/pydantic_ai/openai.
It may depend on the data layer (it is a 取数协调器, not a pure operator — ADR-0005).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import BaseModel

from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.normalize.contracts import NormalizedPrice
from finrobot.engine.data.types import DataType

if TYPE_CHECKING:
    from finrobot.engine.data.layer import DataLayer

logger = logging.getLogger(__name__)

_FMP_TIMEOUT = 10.0  # seconds

# A trend snapshot needs at least the SMA20 window to mean anything; below this
# the series is too short to classify (returns insufficient_history).
_MIN_HISTORY = 20
# 52-week window in trading days (~252). Shorter series use whatever they have.
_WINDOW_52W = 252


class EarningsEvent(BaseModel):
    date: str
    ticker: str
    company_name: str
    time: str  # "BMO" | "AMC" | "—"
    eps_estimate: float | None = None


# ---------------------------------------------------------------------------
# Technical snapshot (pure) + canonical entry point
# ---------------------------------------------------------------------------


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


def technical_payload(history: Sequence[Mapping[str, float]]) -> dict[str, Any]:
    """Pure trend snapshot from a close series (oldest → newest).

    ``history`` is a list of bar-like mappings each carrying a ``close``. Returns
    ``{"available": False, "reason": ...}`` when the series is too short to
    classify, otherwise a snapshot with SMA 20/50/200, trend, current price, and
    52-week high/low/range-position. No provider access — callers pass closes in.
    """
    closes = [float(b["close"]) for b in history if b.get("close") is not None]
    if len(closes) < _MIN_HISTORY:
        return {"available": False, "reason": "insufficient_history"}

    current = closes[-1]
    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50)
    sma200 = _sma(closes, 200)

    window = closes[-_WINDOW_52W:]
    high_52w = max(window)
    low_52w = min(window)
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
    return technical_payload([{"close": bar.close} for bar in price.bars])


# ---------------------------------------------------------------------------
# Earnings calendar (FMP)
# ---------------------------------------------------------------------------


async def fetch_earnings_calendar(
    fmp_api_key: str | None = None,
) -> list[EarningsEvent]:
    """Fetch upcoming earnings events for the next 7 days.

    Requires an FMP API key. Returns an empty list (not an error) when no key
    is provided — callers should surface this as a "no key configured" UI hint
    rather than treating it as a failure.
    """
    if not fmp_api_key:
        logger.debug("fetch_earnings_calendar: no FMP key provided, returning empty list")
        return []

    today = date.today()
    end = today + timedelta(days=7)
    url = "https://financialmodelingprep.com/api/v3/earning_calendar"
    params = {
        "from": today.isoformat(),
        "to": end.isoformat(),
        "apikey": fmp_api_key,
    }

    try:
        async with httpx.AsyncClient(timeout=_FMP_TIMEOUT) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            raw: list[dict[str, object]] = response.json()
    except httpx.HTTPStatusError as e:
        logger.exception("FMP earnings calendar HTTP error: %s", e.response.status_code)
        return []
    except (httpx.TimeoutException, httpx.ConnectError):
        logger.exception("FMP earnings calendar network error")
        return []

    events: list[EarningsEvent] = []
    for item in raw:
        ticker = str(item.get("symbol") or "")
        if not ticker:
            continue
        # Filter to US-listed tickers. FMP's earning_calendar returns the full
        # global universe (NSE/BSE India, .T Japan, .AX Australia, .L London,
        # .HK Hong Kong, .TWO Taiwan, ...) — thousands of names per week, mostly
        # noise for a US-focused dashboard. Whitelist US share-class suffixes
        # (BRK.A, BRK.B, BF.B, LEN.B); drop everything else with a dot.
        # Note .T / .L look like single-letter share classes but are Tokyo /
        # London exchange suffixes, so we can't generalise to "any single
        # uppercase letter".
        if "." in ticker:
            suffix = ticker.rsplit(".", 1)[1]
            if suffix not in {"A", "B"}:
                continue
        eps_raw = item.get("epsEstimated")
        try:
            eps_estimate = float(str(eps_raw)) if eps_raw is not None else None
        except (TypeError, ValueError):
            eps_estimate = None

        # FMP "time" field: "bmo" (before market open) / "amc" (after market close) / null
        time_raw = str(item.get("time") or "").lower()
        if time_raw == "bmo":
            time_label = "BMO"
        elif time_raw == "amc":
            time_label = "AMC"
        else:
            time_label = "—"

        events.append(
            EarningsEvent(
                date=str(item.get("date") or ""),
                ticker=ticker,
                company_name=str(item.get("name") or ticker),
                time=time_label,
                eps_estimate=eps_estimate,
            )
        )

    events.sort(key=lambda ev: ev.date)

    # Dedup (ticker, date) — FMP occasionally returns multiple rows for the same
    # company on the same date (BMO + AMC, listing-exchange duplicates). Keep
    # the first occurrence so downstream React keys stay unique.
    deduped: dict[tuple[str, str], EarningsEvent] = {}
    for event in events:
        deduped.setdefault((event.ticker, event.date), event)
    return list(deduped.values())
