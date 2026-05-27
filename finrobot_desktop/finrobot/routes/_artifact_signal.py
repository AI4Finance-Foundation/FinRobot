"""Route-layer adapter: lazily compute ArtifactSummary.signal against fresh quotes.

The compute layer (`finrobot.engine.compute.signal`) is intentionally numeric
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

import logging
from collections.abc import Iterable
from datetime import datetime, timezone

from finrobot.artifact.models import ArtifactSummary
from finrobot.engine.compute.signal import compute_signal
from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.data.types import DataType

logger = logging.getLogger(__name__)


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
    quotes: dict[str, float] = {}
    for ticker in tickers:
        try:
            result = await data_layer.fetch(DataType.PRICE, ticker)
        except (ProviderError, ValueError, KeyError) as exc:
            logger.info("price fetch failed for %s while attaching signals: %s", ticker, exc)
            continue
        raw = result.data.get("current_price") if isinstance(result.data, dict) else None
        if raw is None:
            continue
        try:
            price = float(raw)
        except (TypeError, ValueError):
            continue
        if price > 0:
            quotes[ticker] = price
    return quotes
