"""Cross-ticker hit-rate roll-up powering the /stocks landing banner.

Re-uses `finrobot.engine.compute.operators.signal.compute_signal` per artifact, then
groups by verdict (BUY / HOLD / SELL) plus an overall bucket. Watching
artifacts count toward n_total but not n_closed — same bias-corrected
convention as the ticker-level `compute_hit_rate`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from finrobot.engine.compute.operators.signal import Signal, compute_signal

Window = Literal["30d", "90d", "all"]
"""Time-window keys exposed to the route layer."""

_WINDOW_DAYS: dict[Window, int | None] = {"30d": 30, "90d": 90, "all": None}


@dataclass(frozen=True)
class ArtifactSignalInput:
    """One artifact's inputs to the signal classifier (route layer assembles)."""

    entry_price: float | None
    target_price: float | None
    current_price: float | None
    entry_date: datetime
    target_date: datetime | None
    verdict: str | None
    """BUY / HOLD / SELL — None means "no thesis" (e.g. peer research)."""


@dataclass(frozen=True)
class HitRateBucketStats:
    """Aggregated counts + hit-rate for one verdict slice (or overall)."""

    n_total: int
    """Artifacts with a non-None signal (any state)."""
    n_closed: int
    """Artifacts with signal ∈ {hit, failed}."""
    n_hit: int
    hit_rate: float | None
    """n_hit / n_closed; None when n_closed == 0 so UI can show 'not enough'."""


@dataclass(frozen=True)
class HitRateOverviewStats:
    """Roll-up returned to the route layer; route wraps into Pydantic."""

    window: Window
    overall: HitRateBucketStats
    by_verdict: dict[str, HitRateBucketStats]
    generated_at: datetime


def compute_hit_rate_overview(
    *,
    artifacts: list[ArtifactSignalInput],
    window: Window,
    now: datetime | None = None,
) -> HitRateOverviewStats:
    """Bucket artifacts by verdict + overall and emit hit-rate stats per bucket.

    Filtering rules:
      - Time window: `created_at >= now - window_days` (skipped when window='all').
      - Signal eligibility: artifact needs `entry_price > 0`, `target_price > 0`,
        and `current_price` known. Otherwise it falls out (does not count toward
        any n_total).
      - Verdict bucketing: only verdicts in {BUY, HOLD, SELL} create a bucket.
        Artifacts with verdict=None still contribute to `overall`.

    Args:
        artifacts: Pre-filtered list (route layer should pass everything; this
            function does the window cut so the rule lives in one place).
        window: One of "30d", "90d", "all".
        now: Test-injection clock; defaults to ``datetime.now(UTC)``.

    Returns:
        HitRateOverviewStats — buckets `BUY`, `HOLD`, `SELL` are always present
        (empty stats when no artifacts qualify), so UI doesn't have to handle
        the missing-key case.
    """
    clock = now if now is not None else datetime.now(tz=timezone.utc)
    cutoff_days = _WINDOW_DAYS[window]
    cutoff = clock - timedelta(days=cutoff_days) if cutoff_days is not None else None

    overall_signals: list[Signal] = []
    by_verdict_signals: dict[str, list[Signal]] = {"BUY": [], "HOLD": [], "SELL": []}

    for art in artifacts:
        if cutoff is not None and _ensure_tz(art.entry_date) < cutoff:
            continue
        sig = _signal_for(art, clock)
        if sig is None:
            continue
        overall_signals.append(sig)
        if art.verdict in by_verdict_signals:
            by_verdict_signals[art.verdict].append(sig)

    return HitRateOverviewStats(
        window=window,
        overall=_bucket_stats(overall_signals),
        by_verdict={k: _bucket_stats(v) for k, v in by_verdict_signals.items()},
        generated_at=clock,
    )


def _signal_for(art: ArtifactSignalInput, now: datetime) -> Signal | None:
    """Classify one artifact; None when insufficient data."""
    if (
        art.entry_price is None
        or art.entry_price <= 0
        or art.target_price is None
        or art.target_price <= 0
        or art.current_price is None
    ):
        return None
    if abs(art.target_price - art.entry_price) < 1e-9:
        # `compute_signal` would raise; we just drop the artifact instead of
        # crashing the whole landing endpoint over one bad thesis.
        return None
    try:
        return compute_signal(
            target_price=art.target_price,
            entry_price=art.entry_price,
            current_price=art.current_price,
            entry_date=art.entry_date,
            target_date=art.target_date,
            now=now,
        )
    except ValueError:
        return None


def _bucket_stats(signals: list[Signal]) -> HitRateBucketStats:
    n_total = len(signals)
    n_hit = sum(1 for s in signals if s == "hit")
    n_closed = sum(1 for s in signals if s in ("hit", "failed"))
    hit_rate: float | None = n_hit / n_closed if n_closed > 0 else None
    return HitRateBucketStats(
        n_total=n_total,
        n_closed=n_closed,
        n_hit=n_hit,
        hit_rate=hit_rate,
    )


def _ensure_tz(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
