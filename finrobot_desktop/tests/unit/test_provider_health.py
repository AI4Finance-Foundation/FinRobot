"""Unit tests for the provider health circuit breaker (deterministic, no sleep)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from finrobot.engine.data.provider_health import ProviderHealth

UTC = timezone.utc
T0 = datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC)


def test_unknown_provider_is_available() -> None:
    h = ProviderHealth()
    assert h.is_available("fmp", now=T0) is True


def test_below_threshold_stays_available() -> None:
    h = ProviderHealth(failure_threshold=3)
    h.record_failure("fmp", now=T0)
    h.record_failure("fmp", now=T0)
    assert h.is_available("fmp", now=T0) is True  # 2 < 3


def test_threshold_breach_opens_cooldown() -> None:
    h = ProviderHealth(failure_threshold=3, base_cooldown_s=60)
    for _ in range(3):
        h.record_failure("fmp", now=T0)
    assert h.is_available("fmp", now=T0) is False
    assert h.is_available("fmp", now=T0 + timedelta(seconds=59)) is False
    assert h.is_available("fmp", now=T0 + timedelta(seconds=60)) is True


def test_rate_limit_opens_cooldown_immediately() -> None:
    h = ProviderHealth(failure_threshold=3, base_cooldown_s=60)
    h.record_failure("fmp", rate_limited=True, now=T0)  # one strike, but rate-limited
    assert h.is_available("fmp", now=T0) is False
    assert h.is_available("fmp", now=T0 + timedelta(seconds=61)) is True


def test_cooldown_grows_exponentially() -> None:
    h = ProviderHealth(failure_threshold=2, base_cooldown_s=60, max_cooldown_s=900)
    h.record_failure("x", now=T0)
    h.record_failure("x", now=T0)  # 2 == threshold → 60s (over=0)
    assert h.is_available("x", now=T0 + timedelta(seconds=60)) is True
    h.record_failure("x", now=T0)  # over=1 → 120s
    assert h.is_available("x", now=T0 + timedelta(seconds=119)) is False
    assert h.is_available("x", now=T0 + timedelta(seconds=120)) is True


def test_cooldown_capped_at_max() -> None:
    h = ProviderHealth(failure_threshold=1, base_cooldown_s=60, max_cooldown_s=180)
    for _ in range(10):  # would be 60 * 2^9 without the cap
        h.record_failure("x", now=T0)
    assert h.is_available("x", now=T0 + timedelta(seconds=180)) is True


def test_success_closes_circuit_and_resets() -> None:
    h = ProviderHealth(failure_threshold=3, base_cooldown_s=60)
    for _ in range(3):
        h.record_failure("fmp", now=T0)
    assert h.is_available("fmp", now=T0) is False
    h.record_success("fmp", now=T0 + timedelta(seconds=5))
    assert h.is_available("fmp", now=T0 + timedelta(seconds=5)) is True
    # Counter reset: it now takes a fresh full threshold to reopen.
    h.record_failure("fmp", now=T0 + timedelta(seconds=10))
    h.record_failure("fmp", now=T0 + timedelta(seconds=10))
    assert h.is_available("fmp", now=T0 + timedelta(seconds=10)) is True

    snap = h.snapshot("fmp")
    assert snap.last_success == T0 + timedelta(seconds=5)
    assert snap.consecutive_failures == 2
