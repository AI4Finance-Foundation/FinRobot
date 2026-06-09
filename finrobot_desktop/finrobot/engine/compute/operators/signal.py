"""Signal verdict + hit-rate statistics (leaf-layer pure functions).

Implements the rules in v5 spec §7.1 / §7.3 — the *only* place these are
calculated. CLI / SDK / FastAPI routes / front-end all delegate here. No
duplication permitted (see ADR-0001).

Leaf-layer rules:
- No imports from `finrobot.engine.pipelines / agents / orchestrator`.
- No imports from LLM libraries (pydantic_ai / openai / anthropic / litellm).
- No imports from `finrobot.artifact.*` — pure numeric inputs only.
  Route-layer adapters convert ArtifactSummary → inputs for these functions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

Signal = Literal["hit", "watching", "failed"]

_HIT_BAND = 0.10
"""±10% of target_price counts as a hit (v5 §7.1 rule 1)."""

_HIT_PROGRESS = 0.50
"""Moving >50% of the way toward target counts as a hit (v5 §7.1 rule 2)."""

_FAIL_REVERSE = 0.10
"""Moving >10% in the wrong direction counts as failure (v5 §7.1 rule 3)."""

_WATCH_GRACE_DAYS = 7
"""Within 7 days of entry, any price action stays in watching (v5 §7.1)."""


@dataclass(frozen=True)
class HitRateStats:
    """Aggregate hit-rate statistics for a single ticker (v5 §7.3).

    Both `hit_rate` and `avg_excess_return` are `None` when `n_closed == 0`,
    so callers do not have to special-case empty samples.
    """

    n_total: int
    """Artifacts with a non-None signal (in any state)."""

    n_closed: int
    """Artifacts with signal ∈ {hit, failed}. Watching does NOT count."""

    n_hit: int
    """Artifacts with signal == 'hit'."""

    hit_rate: float | None
    """n_hit / n_closed — uses closed-sample denominator to avoid bias."""

    avg_excess_return: float | None
    """mean(ticker_return - sp500_return) over closed artifacts (incl. failed)."""


@dataclass(frozen=True)
class ClosedReturn:
    """One closed artifact's realised return data (route layer assembles)."""

    ticker_return: float
    """(current_price - entry_price) / entry_price."""

    sp500_return: float
    """(sp500_now - sp500_at_entry) / sp500_at_entry."""


def compute_signal(
    *,
    target_price: float,
    entry_price: float,
    current_price: float,
    entry_date: datetime,
    target_date: datetime | None = None,
    now: datetime | None = None,
) -> Signal:
    """Classify an artifact's current state as hit / watching / failed.

    Rules (v5 §7.1):
      - hit: |current - target| / target ≤ 10%, OR
             actual_move / expected_move > 50% (in the target direction)
      - failed: actual_move ≤ -10% * entry_price AND ≥ 7 days since entry, OR
                now > target_date and not already hit
      - watching: otherwise (default for the first 7 days)

    Args:
        target_price: AI-given target price.
        entry_price: Quote snapshot at pipeline run time.
        current_price: Quote at signal compute time.
        entry_date: When the artifact was created (== ArtifactMeta.created_at).
        target_date: Optional deadline (default ``entry_date + 365d`` set
            upstream in the thesis step).
        now: Test-injection clock; defaults to ``datetime.now(UTC)``.

    Raises:
        ValueError: If entry_price ≤ 0 or target_price ≤ 0 or
            target_price == entry_price (a thesis with no implied move is
            meaningless and would div-zero the expected_move computation).
    """
    # Non-finite prices pass every sign/degeneracy guard below (NaN comparisons are
    # all False, +Inf > 0 is True) and would yield a NaN actual_move / expected_move
    # and a meaningless verdict — reject them up front.
    for _name, _val in (
        ("entry_price", entry_price),
        ("target_price", target_price),
        ("current_price", current_price),
    ):
        if not math.isfinite(_val):
            raise ValueError(f"{_name} must be finite, got {_val!r}")
    if entry_price <= 0:
        raise ValueError("entry_price must be > 0")
    if target_price <= 0:
        raise ValueError("target_price must be > 0")
    if abs(target_price - entry_price) < 1e-9:
        raise ValueError(
            "target_price == entry_price: thesis must have a directional view; "
            "reject at artifact creation, not in signal compute"
        )

    now = now if now is not None else datetime.now(tz=timezone.utc)
    entry_date = _ensure_tz(entry_date)
    target_date = _ensure_tz(target_date) if target_date is not None else None
    now = _ensure_tz(now)

    direction = 1 if target_price > entry_price else -1
    expected_move = abs(target_price - entry_price)
    actual_move = (current_price - entry_price) * direction

    # Rule 1: within 10% of the EXPECTED MOVE from the target AND moved toward it →
    # hit (works for both bullish & bearish targets). The band is normalised by
    # ``expected_move`` (the thesis's own scale), NOT ``target_price``: a fraction of
    # the absolute price over-credited a small-move/high-price thesis (entry 1000→
    # target 1010, current 1004 = 40% progress sat 0.6% from $1010 and scored "hit")
    # and gave LONG vs mirror-SHORT different dollar bands. Matches Rule 2's
    # expected-move normalisation, so the two rules speak one scale. The direction
    # guard (actual_move > 0) is
    # essential and mirrors Rule 2's strict ``>``: without it a wrong-direction LOSS
    # (W2-F2: BUY entry100/target105, current95 sat in the band, counted "hit") OR a
    # ZERO-progress position (current == entry, no P&L) scores as a hit whenever the
    # price lands within 10% of a near target — inflating the dashboard hit-rate.
    # Strict ``> 0``: a hit requires actual movement toward the target, not standing
    # still (W3, probe 2026-06-09).
    if actual_move > 0 and abs(current_price - target_price) / expected_move <= _HIT_BAND:
        return "hit"

    # Rule 2: moved >50% of the expected distance in the right direction → hit
    if actual_move / expected_move > _HIT_PROGRESS:
        return "hit"

    days_since_entry = (now - entry_date).total_seconds() / 86_400.0

    # Rule 3a: hard reverse move after the 7-day grace window → failed
    if days_since_entry >= _WATCH_GRACE_DAYS:
        if actual_move < 0 and abs(actual_move) / entry_price > _FAIL_REVERSE:
            return "failed"

    # Rule 3b: past target_date without hitting → failed
    if target_date is not None and now > target_date:
        return "failed"

    # Default — including the entire <7-day grace window
    return "watching"


def compute_hit_rate(
    *,
    signals: list[Signal | None],
    closed_returns: list[ClosedReturn],
) -> HitRateStats:
    """Aggregate hit-rate + excess-return for a single ticker's artifacts.

    Bias-corrected statistics (v5 §7.3):
      - Denominator for hit_rate is closed sample (hit + failed), NOT total.
        Watching artifacts are too young to judge and would dilute the rate.
      - avg_excess_return averages closed artifacts including failed ones.
        Averaging only hits inflates the result (survivor bias).

    Args:
        signals: All ArtifactSummary.signal values for this ticker. None
            entries (cold artifacts without entry/target prices) are dropped
            from n_total before any counting.
        closed_returns: One ClosedReturn per artifact with signal in
            {hit, failed}. The route layer is responsible for matching order
            and fetching prices (SP500 etc.) via DataProvider.

    Returns:
        HitRateStats with hit_rate / avg_excess_return == None when n_closed
        is zero, so callers can render an "insufficient data" banner directly.
    """
    signaled = [s for s in signals if s is not None]
    n_total = len(signaled)
    n_hit = sum(1 for s in signaled if s == "hit")
    n_closed = sum(1 for s in signaled if s in ("hit", "failed"))

    hit_rate: float | None = None
    avg_excess: float | None = None
    if n_closed > 0:
        hit_rate = n_hit / n_closed
        if closed_returns:
            excess = [r.ticker_return - r.sp500_return for r in closed_returns]
            avg_excess = sum(excess) / len(excess)

    return HitRateStats(
        n_total=n_total,
        n_closed=n_closed,
        n_hit=n_hit,
        hit_rate=hit_rate,
        avg_excess_return=avg_excess,
    )


def _ensure_tz(dt: datetime) -> datetime:
    """Treat naive datetimes as UTC — JSON round-tripped values may drop tz."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
