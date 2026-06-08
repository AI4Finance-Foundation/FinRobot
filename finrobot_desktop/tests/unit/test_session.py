"""Unit tests for the shared market-session module.

``compute_session_state`` is exercised in depth by test_routes_price_period.py;
here we cover the as_of-derivation chain (``derive_price_as_of`` /
``session_close_dt`` / ``_coerce_quote_dt``) that fixes the freshness-overstatement
bug — a daily bar's as_of must read its real session close, never midnight.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from finrobot.engine.data.normalize.session import (
    _coerce_quote_dt,
    compute_session_state,
    derive_price_as_of,
    session_close_dt,
)

# External baseline (this session's FMP probe): TSLA Friday close timestamp.
FRI_CLOSE_TS = 1780689600  # 2026-06-05T20:00:00Z (16:00 ET)
FRI_CLOSE_DT = datetime(2026, 6, 5, 20, 0, tzinfo=timezone.utc)
MON_PREMARKET = datetime(2026, 6, 8, 8, 0, tzinfo=timezone.utc)  # 04:00 ET


def test_session_close_dt_us_is_2000z_not_midnight():
    """A US bar's close is 16:00 ET = 20:00 UTC, not 00:00 UTC."""
    assert session_close_dt(date(2026, 6, 5), ticker="TSLA") == FRI_CLOSE_DT


def test_session_close_dt_unresolvable_exchange_is_none():
    assert session_close_dt(date(2026, 6, 5), ticker="ABC.XYZ") is None


def test_derive_prefers_quote_timestamp():
    as_of, approx = derive_price_as_of(FRI_CLOSE_TS, date(2026, 6, 5), ticker="TSLA")
    assert as_of == FRI_CLOSE_DT
    assert approx is False


def test_derive_falls_back_to_session_close_when_no_timestamp():
    as_of, approx = derive_price_as_of(None, date(2026, 6, 5), ticker="TSLA")
    assert as_of == FRI_CLOSE_DT  # session close, NOT midnight
    assert approx is True


def test_derive_midnight_only_when_exchange_unresolvable():
    as_of, approx = derive_price_as_of(None, date(2026, 6, 5), ticker="ABC.XYZ")
    assert as_of == datetime(2026, 6, 5, 0, 0, tzinfo=timezone.utc)
    assert approx is True


def test_derive_session_close_never_after_fetch():
    """A still-open session has no close yet → don't stamp a future as_of; floor
    to midnight (flagged) rather than a session close past the fetch instant."""
    fetched = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)  # before 20:00Z close
    as_of, approx = derive_price_as_of(None, date(2026, 6, 8), ticker="TSLA", fetched_at=fetched)
    assert as_of <= fetched
    assert approx is True


def test_derive_no_bar_no_timestamp_uses_fetched_at():
    fetched = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
    as_of, approx = derive_price_as_of(None, None, fetched_at=fetched)
    assert as_of == fetched
    assert approx is True


def test_coerce_quote_dt_shapes():
    assert _coerce_quote_dt(FRI_CLOSE_TS) == FRI_CLOSE_DT  # unix seconds
    assert _coerce_quote_dt(FRI_CLOSE_TS * 1000) == FRI_CLOSE_DT  # unix millis
    assert _coerce_quote_dt("2026-06-05T20:00:00Z") == FRI_CLOSE_DT  # iso
    assert _coerce_quote_dt(str(FRI_CLOSE_TS)) == FRI_CLOSE_DT  # digit string
    naive = datetime(2026, 6, 5, 20, 0)
    assert _coerce_quote_dt(naive) == FRI_CLOSE_DT  # naive → assume UTC
    assert _coerce_quote_dt(None) is None
    assert _coerce_quote_dt(0) is None
    assert _coerce_quote_dt(True) is None  # bool is not a timestamp
    assert _coerce_quote_dt("garbage") is None


def test_session_state_closed_for_weekend_close_at_monday_premarket():
    """The bug scenario: Friday close viewed Monday pre-market → closed, not live."""
    assert (
        compute_session_state(FRI_CLOSE_DT.isoformat(), ticker="TSLA", now=MON_PREMARKET)
        == "closed"
    )
