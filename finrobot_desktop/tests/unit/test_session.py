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
    has_newer_session_since,
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


# --- 7-state marketState mapping (primary signal) ------------------------------
# Baseline: yfinance marketState enum {PREPRE, PRE, REGULAR, POST, POSTPOST,
# CLOSED} per the 2026-06-08 probe (specs/research/行情盘内取证…). marketState is
# the PRIMARY signal — when present and recognized it is authoritative and needs
# no as_of / exchange resolution; the clock window is the fallback only.


def test_market_state_regular_maps_to_live():
    """REGULAR = regular session in progress → live (the legacy "live" anchor)."""
    assert compute_session_state(None, market_state="REGULAR") == "live"


def test_market_state_pre_maps_to_pre_market():
    """PRE = pre-market session active → the new pre_market phase (was 'closed')."""
    assert compute_session_state(None, market_state="PRE") == "pre_market"


def test_market_state_post_maps_to_post_market():
    """POST = after-hours session active → the new post_market phase (was 'closed')."""
    assert compute_session_state(None, market_state="POST") == "post_market"


def test_market_state_prepre_maps_to_closed():
    """PREPRE = overnight before pre-market opens — no trading → closed."""
    assert compute_session_state(None, market_state="PREPRE") == "closed"


def test_market_state_postpost_maps_to_closed():
    """POSTPOST = after after-hours ends — market fully shut → closed."""
    assert compute_session_state(None, market_state="POSTPOST") == "closed"


def test_market_state_closed_maps_to_closed():
    """CLOSED = weekend / holiday / between sessions → closed."""
    assert compute_session_state(None, market_state="CLOSED") == "closed"


def test_market_state_is_case_and_whitespace_insensitive():
    """Provider casing/whitespace must not change the phase."""
    assert compute_session_state(None, market_state=" regular ") == "live"
    assert compute_session_state(None, market_state="Pre") == "pre_market"


def test_market_state_overrides_clock_window():
    """marketState is authoritative: a PRE quote during US regular hours is
    pre_market, NOT the clock-derived live. (Defensive — in practice the feed's
    phase and the clock agree; this proves the precedence, not a real conflict.)"""
    # 17:00 UTC = 13:00 EDT → inside the US 09:30–16:00 ET regular window.
    now = datetime(2026, 5, 27, 17, 0, tzinfo=timezone.utc)
    assert compute_session_state("2026-05-27", market_state="PRE", ticker="AAPL", now=now) == (
        "pre_market"
    )


def test_market_state_full_enum_is_covered():
    """Every documented yfinance marketState value maps to a non-fallback phase —
    no value silently drops to the clock window. (Guards the mapping completeness
    against the probe-confirmed enum.)"""
    expected = {
        "REGULAR": "live",
        "PRE": "pre_market",
        "PREPRE": "closed",
        "POST": "post_market",
        "POSTPOST": "closed",
        "CLOSED": "closed",
    }
    for value, phase in expected.items():
        # as_of=None / no ticker → only marketState can produce these; if any
        # value fell through it would return "closed" via the empty-as_of guard,
        # which for PRE/POST/REGULAR would fail this assert.
        assert compute_session_state(None, market_state=value) == phase


# --- fallback: unrecognized / absent marketState → clock window ----------------


def test_unrecognized_market_state_falls_back_to_clock_live():
    """An unknown marketState string is NOT trusted — fall back to the clock
    window, which (US regular hours, today's bar) yields live."""
    now = datetime(2026, 5, 27, 17, 0, tzinfo=timezone.utc)  # 13:00 EDT, regular hours
    assert (
        compute_session_state("2026-05-27", market_state="WEIRD", ticker="AAPL", now=now) == "live"
    )


def test_none_market_state_falls_back_to_clock():
    """market_state=None (FMP path, or yfinance without the field) → clock window.
    Friday close viewed Monday pre-market → closed (legacy behavior preserved)."""
    assert (
        compute_session_state(
            FRI_CLOSE_DT.isoformat(), market_state=None, ticker="TSLA", now=MON_PREMARKET
        )
        == "closed"
    )


def test_empty_market_state_falls_back_to_clock():
    """An empty-string marketState is treated as absent → clock fallback."""
    now = datetime(2026, 5, 27, 17, 0, tzinfo=timezone.utc)  # 13:00 EDT, regular hours
    assert compute_session_state("2026-05-27", market_state="", ticker="AAPL", now=now) == "live"


def test_fallback_still_returns_unknown_for_unresolvable_exchange():
    """No marketState + unmapped foreign suffix → unknown (BUG-081 preserved)."""
    now = datetime(2026, 5, 27, 17, 0, tzinfo=timezone.utc)
    assert compute_session_state("2026-05-27", ticker="ABC.XYZ", now=now) == "unknown"


# --- has_newer_session_since: the calendar gate for rate-safe refresh ----------
# Drives "smart refresh": False → no provider call (closed, already latest close);
# True → a newer settled close exists (or market live) → worth fetching; None →
# unresolvable exchange → caller refetches conservatively. US regular session is
# 09:30–16:00 ET = 13:30–20:00 UTC in June (EDT).
SAT = datetime(2026, 6, 6, 18, 0, tzinfo=timezone.utc)  # Sat afternoon
MON_INSESSION = datetime(2026, 6, 8, 14, 30, tzinfo=timezone.utc)  # 10:30 ET, open
MON_AFTERCLOSE = datetime(2026, 6, 8, 21, 0, tzinfo=timezone.utc)  # 17:00 ET, closed
MON_CLOSE_DT = datetime(2026, 6, 8, 20, 0, tzinfo=timezone.utc)  # Mon 16:00 ET


def test_no_newer_session_weekend_premarket_is_false():
    """Friday close held Monday pre-market: nothing newer until Monday open → no-op."""
    assert has_newer_session_since(FRI_CLOSE_DT, ticker="TSLA", now=MON_PREMARKET) is False


def test_no_newer_session_saturday_is_false():
    """Friday close held Saturday: market closed, Friday is the latest → no-op."""
    assert has_newer_session_since(FRI_CLOSE_DT, ticker="TSLA", now=SAT) is False


def test_newer_session_when_market_live_is_true():
    """Mid-session the price moves every second — always worth a refetch."""
    assert has_newer_session_since(FRI_CLOSE_DT, ticker="TSLA", now=MON_INSESSION) is True


def test_newer_session_after_monday_close_holding_only_friday_is_true():
    """After Monday's close while still holding Friday's: Monday's close is newer."""
    assert has_newer_session_since(FRI_CLOSE_DT, ticker="TSLA", now=MON_AFTERCLOSE) is True


def test_no_newer_session_after_close_holding_today_close_is_false():
    """Already hold Monday's settled close, viewed after close → no-op."""
    assert has_newer_session_since(MON_CLOSE_DT, ticker="TSLA", now=MON_AFTERCLOSE) is False


def test_quote_instant_one_second_after_nominal_close_is_not_stale():
    """as_of = 20:00:01Z (real quote instant) still counts as holding the 20:00 close."""
    quote_instant = datetime(2026, 6, 5, 20, 0, 1, tzinfo=timezone.utc)
    assert has_newer_session_since(quote_instant, ticker="TSLA", now=SAT) is False


def test_hk_overnight_in_session_is_true():
    """A .HK quote sits in ET overnight; judged in HK time it can be mid-session."""
    # now = 2026-06-05T04:00Z = 12:00 HKT Friday → HK regular session in progress.
    hk_now = datetime(2026, 6, 5, 4, 0, tzinfo=timezone.utc)
    prev_hk_close = datetime(2026, 6, 4, 8, 0, tzinfo=timezone.utc)  # 16:00 HKT Thu
    assert has_newer_session_since(prev_hk_close, ticker="0700.HK", now=hk_now) is True


def test_unresolvable_exchange_is_none():
    """Unknown foreign listing: can't assert closed — caller must refetch."""
    assert has_newer_session_since(FRI_CLOSE_DT, ticker="ABC.XYZ", now=SAT) is None


# --- free-form exchange labels resolve US via contains-match (BUG: no-op gate) --
# The cross-provider ``exchange`` field arrives as opaque yfinance codes
# (``NMS``/``NYQ``) OR free-form, non-deterministic FMP labels for the SAME ticker
# (``NasdaqGS``/``NasdaqGM``/``NasdaqCM``/``NYSEArca``/the full
# ``New York Stock Exchange``). A US name carrying ANY of these must resolve to a
# US session so a closed-market refresh is a provable no-op. An exact-match table
# silently missed the FMP labels → ``has_newer_session_since`` returned ``None`` →
# 13/20 common US tickers refetched a closed-market close they should have skipped.
# Live-probe baseline (2026-06-15 FMP): AAPL/MSFT=NasdaqGS, QQQ=NasdaqGM,
# SPY=NYSEArca, KO=NYSE.
_US_FREEFORM_LABELS = [
    "NasdaqGS",
    "NasdaqGM",
    "NasdaqCM",
    "NYSEArca",
    "New York Stock Exchange",
    "NYSE",
    "NMS",  # yfinance code still resolves
    "NYQ",
]


def test_freeform_us_labels_are_noop_when_closed():
    """Every cross-provider US label → no newer session on a closed Saturday."""
    for label in _US_FREEFORM_LABELS:
        assert (
            has_newer_session_since(FRI_CLOSE_DT, ticker="AAPL", exchange=label, now=SAT) is False
        ), f"{label!r} should be a closed-market no-op (False), not refetch"


def test_freeform_us_labels_force_fetch_in_session():
    """In-session, the SAME labels must return True — never falsely no-op a live
    session into a stale price (the asymmetric safety guarantee)."""
    for label in _US_FREEFORM_LABELS:
        assert (
            has_newer_session_since(FRI_CLOSE_DT, ticker="AAPL", exchange=label, now=MON_INSESSION)
            is True
        ), f"{label!r} must force a fetch while the session is live"


def test_freeform_us_labels_session_state_closed_and_live():
    """The shared chokepoint also feeds compute_session_state: the labels classify
    closed/live in lockstep with the no-op gate (no path divergence)."""
    for label in _US_FREEFORM_LABELS:
        assert (
            compute_session_state(FRI_CLOSE_DT.isoformat(), ticker="AAPL", exchange=label, now=SAT)
            == "closed"
        ), f"{label!r} closed-market quote should classify closed"
        # 2026-06-08 is a Monday; 14:30Z = 10:30 ET → US regular session in progress.
        assert (
            compute_session_state("2026-06-08", ticker="AAPL", exchange=label, now=MON_INSESSION)
            == "live"
        ), f"{label!r} in-session quote should classify live"


def test_nonus_freeform_exchange_label_stays_unresolvable():
    """A suffix-less ticker whose provider exchange names a NON-US venue (no US
    token) must NOT be faked into a US session — return None (refetch)."""
    for label in ["Frankfurt Stock Exchange", "Toronto Stock Exchange", "London Stock Exchange"]:
        assert (
            has_newer_session_since(FRI_CLOSE_DT, ticker="SAP", exchange=label, now=SAT) is None
        ), f"{label!r} is non-US — must stay unresolvable, not asserted US"


def test_foreign_suffix_still_unresolvable_despite_us_label():
    """The dotted suffix wins over the exchange string: a ``.XYZ`` we don't map
    stays None even if a (spurious) US-looking exchange tags along."""
    assert (
        has_newer_session_since(FRI_CLOSE_DT, ticker="ABC.XYZ", exchange="NASDAQ", now=SAT) is None
    )
