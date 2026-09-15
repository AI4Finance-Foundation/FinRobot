"""Route-layer adapter: lazily compute ArtifactSummary.signal against fresh quotes.

The compute layer (`finrobot.engine.compute.operators.signal`) is intentionally numeric
only — it knows nothing about ArtifactSummary or the DataLayer. This adapter
bridges the two: group summaries by ticker, fetch one quote per ticker, run
`compute_signal` per summary, and return the enriched list.

Designed to keep the per-list overhead bounded:
- One quote per unique ticker (not per summary).
- Provider errors are logged but never raise — a missing quote just leaves
  signal=None on the affected summaries.
- compute_signal's own ValueError (degenerate entry==target etc.) is caught
  too so a single bad artifact can't 500 the whole list.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from datetime import datetime, timezone

from finrobot.artifact.models import ArtifactSummary
from finrobot.engine.compute.operators.signal import compute_signal
from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.data.types import DataType

logger = logging.getLogger(__name__)

# Cap on concurrent quote fetches. A bare gather over every unique ticker in
# the artifact list (a 500-row store page = up to 500 coroutines) stampedes
# the provider pool and the event loop at once; the DataLayer's per-provider
# lock only serialises same-(type,ticker) calls, not distinct tickers. Same
# value as coverage's _MARKET_FANOUT_CONCURRENCY — one shared budget shape for
# market fan-outs.
_QUOTE_FANOUT_CONCURRENCY = 8


async def attach_signals(
    summaries: list[ArtifactSummary],
    data_layer: DataLayer,
    *,
    now: datetime | None = None,
) -> list[ArtifactSummary]:
    """Return a new list with `signal` populated where possible.

    Summaries lacking entry_price / target_price / a known ticker keep
    signal=None — the UI treats that as "no verdict yet" and skips the
    artifact from the hit-rate banner.
    """
    if not summaries:
        return summaries

    now = now if now is not None else datetime.now(tz=timezone.utc)
    tickers_needed = {
        s.ticker.upper()
        for s in summaries
        if s.ticker and s.entry_price is not None and s.target_price is not None
    }
    quotes = await _fetch_quotes(tickers_needed, data_layer)

    enriched: list[ArtifactSummary] = []
    for summary in summaries:
        enriched.append(_apply_signal(summary, quotes, now))
    return enriched


def _apply_signal(
    summary: ArtifactSummary,
    quotes: dict[str, float],
    now: datetime,
) -> ArtifactSummary:
    if summary.ticker is None or summary.entry_price is None or summary.target_price is None:
        return summary
    current = quotes.get(summary.ticker.upper())
    if current is None or current <= 0:
        return summary
    try:
        verdict = compute_signal(
            target_price=summary.target_price,
            entry_price=summary.entry_price,
            current_price=current,
            entry_date=summary.created_at,
            target_date=summary.target_date,
            now=now,
        )
    except ValueError as exc:
        logger.debug("signal skipped for %s: %s", summary.id, exc)
        return summary
    return summary.model_copy(update={"signal": verdict})


async def _fetch_quotes(tickers: Iterable[str], data_layer: DataLayer) -> dict[str, float]:
    """Fetch one quote per ticker, concurrently but capped.

    Concurrency turns an N-ticker serial wait into ~⌈N/8⌉×latency, while the
    semaphore keeps a large artifact page (hundreds of unique tickers) from
    stampeding the provider pool — the DataLayer's per-provider lock only
    serialises same-(type,ticker) calls, not distinct tickers (same pattern as
    coverage's market fan-out cap). Per-ticker errors leave that ticker out of
    the result, never raise.
    """
    ticker_list = list(tickers)
    if not ticker_list:
        return {}

    sem = asyncio.Semaphore(_QUOTE_FANOUT_CONCURRENCY)

    async def _one(ticker: str) -> float | None:
        async with sem:
            try:
                result = await data_layer.fetch_canonical(DataType.PRICE, ticker)
            except (ProviderError, ValueError, KeyError) as exc:
                logger.info("price fetch failed for %s while attaching signals: %s", ticker, exc)
                return None
        try:
            price = float(result.current_price)
        except (TypeError, ValueError):
            return None
        if price <= 0:
            return None
        # The canonical PRICE snapshot is in its quote currency (PRICE is never
        # FX-normalized — the FX gate is FINANCIALS-only). entry/target on the
        # ArtifactSummary are canonical USD, so a foreign LOCAL listing's quote
        # must be converted to USD before compute_signal compares the three legs;
        # otherwise the verdict flips on a cross-currency comparison (same hole
        # fixed in coverage + valuation + the landing hit-rate). US issuers / pure
        # ADRs (quote=USD) are a strict no-op. On an FX miss the price is dropped
        # so the signal stays None, never a mixed-currency fabrication.
        quote_ccy = (getattr(result, "quote_currency", "USD") or "USD").upper()
        if quote_ccy == "USD":
            return price
        try:
            rate = await data_layer.fx_rate_to_usd(quote_ccy)
        except (ProviderError, ValueError, KeyError) as exc:
            logger.info(
                "signal FX %s→USD failed for %s — dropping signal: %s", quote_ccy, ticker, exc
            )
            return None
        return price * rate

    prices = await asyncio.gather(*(_one(ticker) for ticker in ticker_list))
    return {
        ticker: price
        for ticker, price in zip(ticker_list, prices, strict=True)
        if price is not None
    }
