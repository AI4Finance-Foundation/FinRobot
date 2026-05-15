"""Market overview data — indices, sector ETFs, earnings calendar.

What this code does that raw LLM cannot:
- Deterministically fetches live market prices from yfinance via batch download
  so every index/sector price is traceable to a provider call, never hallucinated.
- Computes price change and change_pct from two-day history arithmetic — an LLM
  would produce plausible but unrepeatable numbers.
- Optionally hits FMP /v3/earning_calendar for forward-looking events with typed
  output; LLM cannot produce a correctly dated forward earnings calendar.

Leaf-layer rules: no imports from agents/pipelines/orchestrator/pydantic_ai/openai.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class MarketIndex(BaseModel):
    symbol: str
    name: str
    price: float
    change: float
    change_pct: float


class EarningsEvent(BaseModel):
    date: str
    ticker: str
    company_name: str
    time: str  # "BMO" | "AMC" | "—"
    eps_estimate: float | None = None


# ---------------------------------------------------------------------------
# Symbol registries
# ---------------------------------------------------------------------------

INDICES: dict[str, str] = {
    "^GSPC": "S&P 500",
    "^IXIC": "NASDAQ",
    "^DJI": "DOW 30",
    "^VIX": "VIX",
    "^TNX": "10Y UST",
    "^RUT": "RUSSELL 2000",
}

SECTOR_ETFS: dict[str, str] = {
    "XLK": "Tech",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Healthcare",
    "XLY": "Consumer Disc",
    "XLP": "Consumer Staples",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLU": "Utilities",
    "XLC": "Communication",
}

# ---------------------------------------------------------------------------
# Internal: sync batch download (wrapped in asyncio.to_thread by callers)
# ---------------------------------------------------------------------------

_FMP_TIMEOUT = 10.0  # seconds


def _batch_download(symbols: list[str]) -> dict[str, tuple[float, float]]:
    """Synchronous yfinance batch download.

    Returns mapping of symbol -> (latest_close, previous_close).
    Missing or errored symbols are omitted from the result — callers skip them.
    """
    import yfinance as yf

    try:
        df = yf.download(
            symbols,
            period="5d",       # 5 trading days covers weekends / holidays
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=False,      # avoid spawning threads inside to_thread
        )
    except (OSError, ValueError, RuntimeError, ImportError, AttributeError, TypeError):
        # yfinance raises a mix of these depending on network state, pandas
        # version, or curl_cffi errors. All are non-fatal here — return empty
        # so callers degrade gracefully rather than crashing the whole request.
        logger.exception("yfinance batch download failed")
        return {}

    result: dict[str, tuple[float, float]] = {}

    # yfinance MultiIndex layout differs between single vs multiple symbols.
    # When only one symbol is downloaded the columns are flat (Open/High/Close…).
    # When multiple symbols are downloaded, columns are a MultiIndex (symbol, field).
    if len(symbols) == 1:
        sym = symbols[0]
        try:
            closes = df["Close"].dropna()
            if len(closes) >= 2:
                result[sym] = (float(closes.iloc[-1]), float(closes.iloc[-2]))
            elif len(closes) == 1:
                result[sym] = (float(closes.iloc[-1]), float(closes.iloc[-1]))
        except (KeyError, IndexError, TypeError, ValueError):
            logger.warning("No Close data for %s", sym)
        return result

    for sym in symbols:
        try:
            closes = df[sym]["Close"].dropna()
            if len(closes) >= 2:
                result[sym] = (float(closes.iloc[-1]), float(closes.iloc[-2]))
            elif len(closes) == 1:
                result[sym] = (float(closes.iloc[-1]), float(closes.iloc[-1]))
            else:
                logger.warning("Empty Close series for %s — skipping", sym)
        except (KeyError, IndexError, TypeError, ValueError):
            logger.warning("Failed to extract Close data for %s — skipping", sym)

    return result


def _build_market_index_list(
    symbol_map: dict[str, str],
    prices: dict[str, tuple[float, float]],
) -> list[MarketIndex]:
    """Convert raw price tuples into MarketIndex objects, skipping missing symbols."""
    out: list[MarketIndex] = []
    for symbol, name in symbol_map.items():
        if symbol not in prices:
            continue
        latest, prev = prices[symbol]
        change = round(latest - prev, 4)
        change_pct = round((change / prev) * 100, 4) if prev != 0 else 0.0
        out.append(
            MarketIndex(
                symbol=symbol,
                name=name,
                price=round(latest, 4),
                change=change,
                change_pct=change_pct,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------


async def fetch_market_indices() -> list[MarketIndex]:
    """Fetch current prices for major market indices.

    Uses yfinance batch download (wrapped in asyncio.to_thread to avoid
    blocking the event loop). Symbols that fail to return data are skipped
    gracefully — the response may be a partial list.
    """
    symbols = list(INDICES.keys())
    prices = await asyncio.to_thread(_batch_download, symbols)
    return _build_market_index_list(INDICES, prices)


async def fetch_sector_etfs() -> list[MarketIndex]:
    """Fetch current prices for GICS sector ETFs.

    Same approach as fetch_market_indices — yfinance batch, to_thread wrapper,
    graceful per-symbol failure.
    """
    symbols = list(SECTOR_ETFS.keys())
    prices = await asyncio.to_thread(_batch_download, symbols)
    return _build_market_index_list(SECTOR_ETFS, prices)


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
        eps_raw = item.get("epsEstimated")
        try:
            eps_estimate = float(eps_raw) if eps_raw is not None else None
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

    # Sort ascending by date so the frontend receives chronological order
    events.sort(key=lambda e: e.date)
    return events
