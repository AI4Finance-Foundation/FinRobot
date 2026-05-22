"""Batched live-quote helper — fetch last_price for many tickers in one call.

Existing call sites (`routes/journal.py::_fetch_current_price`) iterate the
single-ticker yfinance fast_info path. That's fine for one entry but linear
for the new dashboard endpoints which fan out 20+ tickers per request.

This module exposes `fetch_quotes_batch(tickers)` — a synchronous helper that
uses yfinance's `Tickers("AAA BBB CCC")` multi-ticker API to issue one HTTP
call and return a `{ticker: price | None}` mapping. Failures degrade per
ticker, never as a whole.

Lazy import: yfinance stays an optional dep. ImportError surfaces only when
this helper is actually used.

Leaf-layer rules: no imports from routes / pipelines / agents.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

logger = logging.getLogger(__name__)


def fetch_quotes_batch(tickers: Iterable[str]) -> dict[str, float | None]:
    """Return `{ticker: last_price | None}` for the given symbols.

    Single-call when yfinance is available; degrades to a dict with every
    value None when the dependency is missing. Per-ticker failures (delisted
    symbol, fast_info miss) come back as None.

    Caller is expected to wrap with `asyncio.to_thread`; yfinance is fully
    synchronous.
    """
    symbols = [t.strip().upper() for t in tickers if t and t.strip()]
    if not symbols:
        return {}

    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance unavailable — returning all-None quote batch")
        return dict.fromkeys(symbols)

    # yfinance accepts a space-separated string or a list; both produce the
    # same `Tickers` container. fast_info per child is the cheapest path.
    try:
        container = yf.Tickers(" ".join(symbols))
    except (ValueError, OSError) as exc:
        logger.warning("yf.Tickers init failed (%s) — falling back to per-ticker", exc)
        return {sym: _fetch_one(sym) for sym in symbols}

    out: dict[str, float | None] = {}
    for sym in symbols:
        try:
            t = container.tickers.get(sym) or container.tickers.get(sym.upper())
            if t is None:
                out[sym] = None
                continue
            info = t.fast_info
            price = getattr(info, "last_price", None)
            if price is None:
                price = getattr(info, "lastPrice", None)
            out[sym] = float(price) if price is not None else None
        except (AttributeError, ValueError, TypeError, OSError):
            logger.exception("Quote fetch failed for %s", sym)
            out[sym] = None
    return out


def _fetch_one(symbol: str) -> float | None:
    """Single-ticker fallback used when the batch init itself errors."""
    try:
        import yfinance as yf

        info = yf.Ticker(symbol).fast_info
        price = getattr(info, "last_price", None)
        if price is None:
            price = getattr(info, "lastPrice", None)
        return float(price) if price is not None else None
    except (ImportError, AttributeError, ValueError, TypeError, OSError):
        logger.exception("Single-ticker fallback failed for %s", symbol)
        return None
