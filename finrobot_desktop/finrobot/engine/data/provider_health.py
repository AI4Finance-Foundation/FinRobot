"""Provider health registry + circuit breaker for the data layer.

BACKLOG P0「Provider 健康机制」: when a provider rate-limits us or fails
repeatedly, paying its timeout on every subsequent call slows the whole
pipeline (the DataLayer iterates providers in priority order). This registry
tracks per-provider failure state and opens a cooldown window so the DataLayer
skips a known-down provider until it's likely recovered, then closes the
circuit on the next success.

Pure + deterministic: every method takes an optional ``now`` so the breaker
policy is unit-testable without sleeping. No I/O, no provider imports. The
DataLayer owns the wiring: it calls ``is_available`` to skip a provider in an
open cooldown window, ``record_success`` on a successful fetch, and
``record_failure`` (with ``rate_limited=is_rate_limit_error(exc)``) on a
``ProviderError`` — see ``DataLayer.__init__`` / its provider loops.

The rate-limit classifier lives in ``interface`` (one shared copy across the
data layer); re-exported here for the breaker's historical call sites.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from finrobot.engine.data.interface import is_rate_limit_error

__all__ = ["ProviderHealth", "ProviderState", "is_rate_limit_error"]


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass
class ProviderState:
    """Mutable health state for one provider."""

    consecutive_failures: int = 0
    cooldown_until: datetime | None = None
    last_success: datetime | None = None
    last_failure: datetime | None = None
    last_rate_limited: bool = False


@dataclass
class ProviderHealth:
    """Per-provider circuit breaker.

    A provider enters cooldown when it rate-limits us (immediately) or after
    ``failure_threshold`` consecutive failures. Cooldown grows exponentially
    from ``base_cooldown_s`` (doubling per extra failure) up to
    ``max_cooldown_s``. Any success closes the circuit and resets the counter.
    """

    failure_threshold: int = 3
    base_cooldown_s: float = 60.0
    max_cooldown_s: float = 900.0
    _states: dict[str, ProviderState] = field(default_factory=dict)

    def _state(self, provider: str) -> ProviderState:
        return self._states.setdefault(provider, ProviderState())

    def is_available(self, provider: str, *, now: datetime | None = None) -> bool:
        """True unless the provider is in an open cooldown window."""
        st = self._states.get(provider)
        if st is None or st.cooldown_until is None:
            return True
        return (now or _utcnow()) >= st.cooldown_until

    def record_success(self, provider: str, *, now: datetime | None = None) -> None:
        """Close the circuit: clear failures and cooldown, stamp last success."""
        st = self._state(provider)
        st.consecutive_failures = 0
        st.cooldown_until = None
        st.last_rate_limited = False
        st.last_success = now or _utcnow()

    def record_failure(
        self, provider: str, *, rate_limited: bool = False, now: datetime | None = None
    ) -> None:
        """Record a failure; open/extend cooldown on rate-limit or threshold breach."""
        ts = now or _utcnow()
        st = self._state(provider)
        st.consecutive_failures += 1
        st.last_failure = ts
        st.last_rate_limited = rate_limited
        if rate_limited or st.consecutive_failures >= self.failure_threshold:
            # Exponential backoff measured from the first over-threshold failure
            # (rate-limit starts at the base window immediately).
            over = max(0, st.consecutive_failures - self.failure_threshold)
            cooldown = min(self.max_cooldown_s, self.base_cooldown_s * (2**over))
            st.cooldown_until = ts + timedelta(seconds=cooldown)

    def snapshot(self, provider: str) -> ProviderState:
        """Read-only-ish view for provenance / observability."""
        return self._state(provider)
