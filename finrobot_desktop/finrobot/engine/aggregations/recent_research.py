"""Most-recent-research strip on the /stocks landing page.

Drawer-style: top-N **tickers** by latest_at desc, each card opens to show
the ticker's most recent runs as clickable rows.

Card shape:
- ticker, run_count (total artifacts for the ticker)
- latest_signal (header lamp: hit / watching / failed / None)
- latest_at (sort key)
- runs: list of RecentTickerRun (max 5 most recent), each carrying its own
  verdict + type + age_label + artifact_id so the UI can route every row
  to /stocks/:ticker/runs/:artifact_id independently.

Older runs beyond the top-5 still get counted in run_count — UI surfaces a
"+ N 更多" footer linking to the ticker workspace's full timeline.

Pure function — no I/O. Route layer supplies per-run verdict + live
current_price for the latest run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from finrobot.engine.compute.operators.signal import Signal, compute_signal

# Max rows surfaced per ticker card. Tickers with more artifacts fall back
# to the workspace's full timeline via the card footer.
MAX_RUNS_PER_TICKER = 5


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
class RecentTickerRun:
    """One clickable row inside a ticker card."""

    artifact_id: str
    type: str  # pipeline key — research / dcf / lbo / ddm / comps / ic-memo / earnings
    verdict: str | None  # BUY / HOLD / SELL / None
    created_at: datetime
    age_label: str


@dataclass(frozen=True)
class RecentTickerView:
    """One ticker card in the landing strip."""

    ticker: str
    run_count: int  # total artifacts for the ticker (NOT len(runs) — runs is capped)
    runs: tuple[RecentTickerRun, ...]  # newest first, max MAX_RUNS_PER_TICKER
    latest_signal: Signal | None  # header lamp; computed from latest run's prices
    latest_at: datetime  # sort key


def assemble_recent_tickers(
    *,
    inputs: list[RecentResearchInput],
    limit: int,
    now: datetime | None = None,
) -> list[RecentTickerView]:
    """Group by ticker, take top-N tickers by latest_at desc, cap rows per card.

    Inputs without a ticker are dropped (no rollup key). Each surviving
    ticker yields one RecentTickerView with up to MAX_RUNS_PER_TICKER rows.
    The latest input drives latest_signal (header lamp); older inputs only
    contribute their row entries.
    """
    if limit <= 0:
        return []
    clock = now if now is not None else datetime.now(tz=timezone.utc)

    by_ticker: dict[str, list[RecentResearchInput]] = {}
    for inp in inputs:
        if not inp.ticker:
            continue
        by_ticker.setdefault(inp.ticker, []).append(inp)

    views = [_assemble_ticker(ticker, group, clock) for ticker, group in by_ticker.items()]
    views.sort(key=lambda v: _ensure_tz(v.latest_at), reverse=True)
    return views[:limit]


def _assemble_ticker(
    ticker: str,
    group: list[RecentResearchInput],
    now: datetime,
) -> RecentTickerView:
    sorted_group = sorted(group, key=lambda i: _ensure_tz(i.created_at), reverse=True)
    latest = sorted_group[0]
    runs = tuple(
        RecentTickerRun(
            artifact_id=inp.artifact_id,
            type=inp.type,
            verdict=inp.verdict,
            created_at=inp.created_at,
            age_label=format_age_label(inp.created_at, now),
        )
        for inp in sorted_group[:MAX_RUNS_PER_TICKER]
    )
    return RecentTickerView(
        ticker=ticker,
        run_count=len(group),
        runs=runs,
        latest_signal=_signal_for(latest, now),
        latest_at=latest.created_at,
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
