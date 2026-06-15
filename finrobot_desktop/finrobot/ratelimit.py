"""In-process token-bucket rate limiting for cost-bearing endpoints (BUG-043).

The desktop server binds loopback and (pending the deferred capability token,
BUG-004/finding-1) has no inbound auth. Three endpoints spend the user's real
LLM money per call — POST /chat, POST /api/runs, and POST
/api/coverage/groups/{id}/runs. ``run_semaphore`` (BUG-017) caps *concurrency*
at 4 but not *total spend*: a runaway loop or buggy retry storm just keeps the
queue full and drains DeepSeek/Anthropic/OpenAI credits plus the EDGAR rate
budget indefinitely.

This module adds the defense-in-depth the finding calls for: a small in-process
token bucket sitting in front of those endpoints. It is an additional INBOUND
guard, orthogonal to both the host-header allowlist (TrustedHostMiddleware,
BUG-004) and the concurrency cap (run_semaphore, BUG-017).

Design notes:
- We bucket on **work units started per minute**, not requests, exactly as the
  finding requires: a coverage batch legitimately spawns one run per ticker, so
  it draws one token per ticker. Sizing the bucket above the largest realistic
  batch means a normal 10- (or even 50-) ticker batch sails through while a
  thousand-run loop is throttled.
- A token-bucket (not a fixed window) so a legitimate burst that fits inside the
  accumulated capacity is allowed, but the *sustained* rate is capped at the
  refill rate. Capacity == one minute of refill, so the worst-case burst a
  caller can fire after idling equals the per-minute budget.
- Single shared object on ``app.state``; cheap (a couple of floats per bucket),
  no background task, no external dependency.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.requests import Request

# Per-minute budgets. Sized WELL above the largest legitimate burst so 429 only
# fires under abnormal volume (a runaway loop / retry storm), never normal use:
#
# - RUNS: each pipeline run (single POST /api/runs or one ticker of a coverage
#   batch) draws one token. 120/min clears a 50-ticker batch with headroom to
#   spare and a few more batches back-to-back, while a script looping create_run
#   as fast as it can is capped at ~2 expensive pipelines/second.
# - CHAT: each POST /chat opens one LLM stream. A human types a handful of
#   messages a minute; 60/min is generous for a real session yet stops a page
#   hammering the chat endpoint in a loop.
# - LIVE_DATA: read-only GETs (/api/data/*, /api/sentiment/*) spend no LLM
#   money, but each cache MISS burns provider quota (FMP free tier is a daily
#   budget) — an unguarded loop could exhaust it in minutes. The budget is
#   deliberately MUCH wider than runs/chat because reads are mostly cache hits
#   and the desktop legitimately bursts dozens of GETs on a dashboard cold
#   load: 240/min (~4/s sustained) never throttles a human-driven UI, yet caps
#   a runaway script at a rate the provider-side caches can absorb.
_RUNS_PER_MINUTE = 120.0
_CHAT_PER_MINUTE = 60.0
_LIVE_DATA_PER_MINUTE = 240.0


@dataclass
class _Bucket:
    """A single token bucket.

    ``capacity`` tokens accrue at ``refill_per_sec`` up to the ceiling. Each
    accepted unit of work removes one token; when fewer than one remains the
    request is rejected (429).
    """

    capacity: float
    refill_per_sec: float
    tokens: float
    updated_at: float

    def _refill(self, now: float) -> None:
        elapsed = now - self.updated_at
        if elapsed > 0:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_sec)
            self.updated_at = now

    def try_consume(self, cost: float, now: float) -> bool:
        """Remove ``cost`` tokens if available; return whether it was allowed.

        ``cost`` may exceed the leftover tokens by less than one and still be
        rejected — partial consumption is never granted, so the caller either
        gets the whole batch admitted or none of it.
        """
        self._refill(now)
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False


class RunRateLimiter:
    """Shared token buckets guarding the cost-bearing endpoints (BUG-043).

    Two independent buckets — one for pipeline runs, one for chat — because the
    two cost profiles and cadences differ (a coverage batch draws many run
    tokens at once; a chat is one stream per human message). Held as a single
    object on ``app.state.run_rate_limiter`` so all three endpoints share it.

    Not thread-safe by design: the server runs a single asyncio event loop and
    these methods do no ``await``, so they execute atomically between awaits —
    no lock needed.
    """

    def __init__(
        self,
        *,
        runs_per_minute: float = _RUNS_PER_MINUTE,
        chat_per_minute: float = _CHAT_PER_MINUTE,
        live_data_per_minute: float = _LIVE_DATA_PER_MINUTE,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        # Injectable clock for deterministic tests; defaults to wall time.
        self._now: Callable[[], float] = time.monotonic if time_fn is None else time_fn
        now = self._now()
        self._runs = _Bucket(
            capacity=runs_per_minute,
            refill_per_sec=runs_per_minute / 60.0,
            tokens=runs_per_minute,
            updated_at=now,
        )
        self._chat = _Bucket(
            capacity=chat_per_minute,
            refill_per_sec=chat_per_minute / 60.0,
            tokens=chat_per_minute,
            updated_at=now,
        )
        self._live_data = _Bucket(
            capacity=live_data_per_minute,
            refill_per_sec=live_data_per_minute / 60.0,
            tokens=live_data_per_minute,
            updated_at=now,
        )

    def allow_runs(self, count: int = 1) -> bool:
        """Try to admit ``count`` pipeline runs (one token per run started).

        A coverage batch passes its ticker count so the whole batch is admitted
        or rejected atomically — never half a batch.
        """
        return self._runs.try_consume(float(count), self._now())

    def allow_chat(self) -> bool:
        """Try to admit one chat request (one LLM stream)."""
        return self._chat.try_consume(1.0, self._now())

    def allow_live_data(self) -> bool:
        """Try to admit one read-only data GET (provider-quota guard)."""
        return self._live_data.try_consume(1.0, self._now())


def enforce_live_data_limit(request: "Request") -> None:
    """Shared 429 guard for read-only live-data GETs.

    One call at the top of every provider-backed GET route (/api/data/*,
    /api/sentiment/*) so the bucket, the message, and the no-limiter-configured
    fallback (tests build bare apps without app.state.run_rate_limiter) stay
    identical across routes. Raises ``HTTPException(429)`` when the bucket is
    drained.
    """
    limiter = getattr(request.app.state, "run_rate_limiter", None)
    if limiter is not None and not limiter.allow_live_data():
        from fastapi import HTTPException

        raise HTTPException(
            status_code=429,
            detail="Too many data requests; read-only rate limiting has been triggered. Please retry shortly.",
        )
