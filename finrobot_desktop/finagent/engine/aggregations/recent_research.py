"""Most-recent-research strip on the /stocks landing page.

Top-N artifacts by created_at desc, each enriched with:
- Live current_price (route layer supplies; this module stays pure).
- delta_to_target_pct = (current - entry) / (target - entry) when both
  directions are available; clamped to [-2.0, 2.0] so a wild outlier doesn't
  blow up the chart.
- signal: hit / watching / failed via compute_signal.
- age_label: "12m ago" / "3h ago" / "5d ago" / "2026-04-12" (date once > 30d).

Pure function — no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from finagent.engine.compute.signal import Signal, compute_signal


@dataclass(frozen=True)
class RecentResearchInput:
    """Route-layer assembled view of one artifact, all fields raw."""

    artifact_id: str
    ticker: str | None
    cross_tickers: tuple[str, ...]
    type: str
    headline: str
    verdict: str | None
    entry_price: float | None
    target_price: float | None
    target_date: datetime | None
    current_price: float | None
    created_at: datetime


@dataclass(frozen=True)
class RecentResearchView:
    """Output one row for the landing strip."""

    artifact_id: str
    ticker: str | None
    cross_tickers: tuple[str, ...]
    type: str
    headline: str
    verdict: str | None
    entry_price: float | None
    target_price: float | None
    current_price: float | None
    delta_to_target_pct: float | None
    signal: Signal | None
    created_at: datetime
    age_label: str


def assemble_recent_research(
    *,
    inputs: list[RecentResearchInput],
    limit: int,
    now: datetime | None = None,
) -> list[RecentResearchView]:
    """Sort desc by created_at, take top N, enrich each."""
    if limit <= 0:
        return []
    clock = now if now is not None else datetime.now(tz=timezone.utc)
    ordered = sorted(inputs, key=lambda i: _ensure_tz(i.created_at), reverse=True)[:limit]
    return [_assemble_one(i, clock) for i in ordered]


def _assemble_one(inp: RecentResearchInput, now: datetime) -> RecentResearchView:
    sig = _signal_for(inp, now)
    delta = _delta_to_target(inp)
    return RecentResearchView(
        artifact_id=inp.artifact_id,
        ticker=inp.ticker,
        cross_tickers=inp.cross_tickers,
        type=inp.type,
        headline=inp.headline,
        verdict=inp.verdict,
        entry_price=inp.entry_price,
        target_price=inp.target_price,
        current_price=inp.current_price,
        delta_to_target_pct=delta,
        signal=sig,
        created_at=inp.created_at,
        age_label=format_age_label(inp.created_at, now),
    )


def _signal_for(inp: RecentResearchInput, now: datetime) -> Signal | None:
    if (
        inp.entry_price is None
        or inp.entry_price <= 0
        or inp.target_price is None
        or inp.target_price <= 0
        or inp.current_price is None
    ):
        return None
    if abs(inp.target_price - inp.entry_price) < 1e-9:
        return None
    try:
        return compute_signal(
            target_price=inp.target_price,
            entry_price=inp.entry_price,
            current_price=inp.current_price,
            entry_date=inp.created_at,
            target_date=inp.target_date,
            now=now,
        )
    except ValueError:
        return None


def _delta_to_target(inp: RecentResearchInput) -> float | None:
    if (
        inp.entry_price is None
        or inp.target_price is None
        or inp.current_price is None
    ):
        return None
    denom = inp.target_price - inp.entry_price
    if abs(denom) < 1e-9:
        return None
    raw = (inp.current_price - inp.entry_price) / denom
    return max(-2.0, min(2.0, raw))


def format_age_label(created_at: datetime, now: datetime) -> str:
    """Render the relative age. Switches to absolute date past 30 days."""
    delta = _ensure_tz(now) - _ensure_tz(created_at)
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:
        return f"{days}d ago"
    return created_at.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _ensure_tz(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
