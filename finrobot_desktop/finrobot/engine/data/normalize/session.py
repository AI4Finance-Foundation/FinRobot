"""Market-session classification + price ``as_of`` derivation — pure, zero-I/O.

Extracted from ``routes/data.py`` so the ``/price`` route AND the Coverage
service derive ``session_state`` and the price ``as_of`` from ONE implementation.
A closed-market quote must read identically on the ticker hero and the coverage
card — two copies of this logic would let them disagree (path divergence).

Two responsibilities, kept orthogonal on purpose:

* :func:`derive_price_as_of` — the *observation time* of a price (the immutable
  semantic timestamp baked into ``Provenance.as_of`` and the canonical cache).
* :func:`compute_session_state` — whether that price is a live intraday quote or
  a session close, classified against ``now``. This is a TIME-VARYING value: it
  must be recomputed on every read, never cached (a 15:59 ET ``live`` snapshot
  would otherwise still read ``live`` at 16:14 — the exact freshness lie this
  module exists to kill).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

# Market-session taxonomy — 7 honest phases, primary signal = the provider's own
# per-exchange ``marketState`` (yfinance), clock-window inference is the fallback.
#
# Source of truth for the enum values is the yfinance ``marketState`` set
# ``{PREPRE, PRE, REGULAR, POST, POSTPOST, CLOSED}`` (observed REGULAR/PREPRE/
# POSTPOST/PRE in the 2026-06-08 probe; POST/CLOSED are documented but were not
# in that window — the mapping covers the full set regardless). The mapping:
#
#   marketState   →  SessionState   semantics
#   ───────────────────────────────────────────────────────────────────────────
#   REGULAR       →  "live"         regular session in progress (continuous trade)
#   PRE           →  "pre_market"   pre-market session active (extended-hours trade)
#   PREPRE        →  "closed"       overnight before pre-market opens — no trading
#   POST          →  "post_market"  after-hours session active (extended-hours trade)
#   POSTPOST      →  "closed"       after after-hours ends — market fully shut
#   CLOSED        →  "closed"       weekend / holiday / between sessions
#   (unknown str) →  fallback       unrecognized value → clock-window inference
#
# ``"halted"`` has NO yfinance source value (yfinance does not surface a trading
# halt / suspension via ``marketState``); it is reserved so a future signal that
# CAN prove a halt (e.g. a provider ``tradeable``/``quoteType`` flag) maps to an
# honest phase instead of mislabeling a halted name "closed". It is never emitted
# by the current clock/marketState path.
#
# ``"unknown"`` means the EXCHANGE itself is unresolvable (unmapped foreign suffix
# / unrecognized non-US exchange) — distinct from an unrecognized marketState
# string on a known exchange, which falls back to the clock window.
#
# Backward-compat contract: ``live`` is still EXACTLY the regular session (no
# semantic change for callers gating on it); ``closed`` and ``unknown`` retain
# their meaning. ``pre_market`` / ``post_market`` are NEW phases carved out of
# what the 3-state version reported as ``closed`` — a caller that treats anything
# ``!= "live"`` as "not a live quote" stays correct; a caller that pattern-matched
# the literal ``"closed"`` to mean "not live" must widen to the new set.
SessionState = Literal[
    "live",
    "pre_market",
    "post_market",
    "closed",
    "halted",
    "unknown",
]

# yfinance ``marketState`` value → SessionState. Values absent here (an
# unrecognized provider string) signal the caller to fall back to the clock
# window — we never guess a phase from an unknown token.
_MARKET_STATE_MAP: dict[str, SessionState] = {
    "REGULAR": "live",
    "PRE": "pre_market",
    "PREPRE": "closed",
    "POST": "post_market",
    "POSTPOST": "closed",
    "CLOSED": "closed",
    # No yfinance value maps to "halted" — see module docstring; reserved.
}


class _MarketSession:
    """Regular-session window for one exchange, in that exchange's timezone."""

    __slots__ = ("tz", "open", "close")

    def __init__(self, tz: str, open_: time, close: time) -> None:
        self.tz = ZoneInfo(tz)
        self.open = open_
        self.close = close


# Map yfinance ticker suffix → exchange regular session. US (no suffix) is the
# fallback for US-listed names. Each window is in the exchange's local timezone;
# lunch breaks (HK/CN/JP) are folded into a continuous span here — half-days and
# lunch-break minutes can over-report "live", an acceptable minimal-fix tradeoff
# (see BUG-081 note). Markets we can't map fall through to "unknown" rather than
# falsely claiming "closed" on a real intraday quote.
_US_SESSION = _MarketSession("America/New_York", time(9, 30), time(16, 0))
_SESSION_BY_SUFFIX: dict[str, _MarketSession] = {
    "HK": _MarketSession("Asia/Hong_Kong", time(9, 30), time(16, 0)),
    "SS": _MarketSession("Asia/Shanghai", time(9, 30), time(15, 0)),
    "SZ": _MarketSession("Asia/Shanghai", time(9, 30), time(15, 0)),
    "T": _MarketSession("Asia/Tokyo", time(9, 0), time(15, 0)),
    "L": _MarketSession("Europe/London", time(8, 0), time(16, 30)),
    "PA": _MarketSession("Europe/Paris", time(9, 0), time(17, 30)),
    "DE": _MarketSession("Europe/Berlin", time(9, 0), time(17, 30)),
    "TO": _MarketSession("America/Toronto", time(9, 30), time(16, 0)),
    "AX": _MarketSession("Australia/Sydney", time(10, 0), time(16, 0)),
    "KS": _MarketSession("Asia/Seoul", time(9, 0), time(15, 30)),
    "KQ": _MarketSession("Asia/Seoul", time(9, 0), time(15, 30)),
    "TW": _MarketSession("Asia/Taipei", time(9, 0), time(13, 30)),
    "NS": _MarketSession("Asia/Kolkata", time(9, 15), time(15, 30)),
    "BO": _MarketSession("Asia/Kolkata", time(9, 15), time(15, 30)),
    "SI": _MarketSession("Asia/Singapore", time(9, 0), time(17, 0)),
}

# Exact US exchange codes/abbreviations (yfinance ``exchange`` codes + common
# abbreviations) that are NOT recognizable by a substring token. Free-form labels
# (FMP's ``NasdaqGS`` / ``NYSEArca`` / ``New York Stock Exchange``) are caught by
# the substring tokens in :func:`_classify_us_exchange` instead, so this set only
# needs the opaque codes that carry no ``NASDAQ``/``NYSE`` token.
_US_EXCHANGE_CODES = frozenset({"NMS", "NYQ", "NGM", "NCM", "AMEX", "PCX", "BATS", "ASE"})

# Substring tokens that, when present in an upper-cased exchange string, prove a
# US listing. ``contains`` (not exact ``in`` a code set) is mandatory because the
# two providers feed this ONE field incompatibly: yfinance emits opaque codes
# (``NMS`` / ``NYQ``) while FMP emits free-form, non-deterministic labels for the
# same ticker (``NasdaqGS`` / ``NasdaqGM`` / ``NasdaqCM`` / ``NYSEArca`` / the
# full ``New York Stock Exchange``). An exact match silently fails the FMP labels
# → the no-op gate returns ``None`` → a closed-market refresh refetches a US name
# it should have skipped. ``ARCA`` covers the bare ``Arca`` venue label;
# ``NEW YORK STOCK`` covers the spelled-out NYSE name (which contains no ``NYSE``
# substring — "New York" has a space — so the abbreviation token alone misses it).
_US_EXCHANGE_TOKENS = ("NASDAQ", "NYSE", "ARCA", "NEW YORK STOCK")


def _classify_us_exchange(exchange: str | None) -> bool | None:
    """Map a provider exchange string to US-listing membership.

    Returns ``True`` (a recognized US listing), ``False`` (a recognized non-US
    exchange — out of scope here, never returned by this function), or ``None``
    (no exchange hint OR an unrecognized string — the caller decides). The single
    place that turns the raw, cross-provider ``exchange`` field into a market
    judgment, so the no-op gate and the session-state classifier agree by
    construction instead of via two drifting copies.

    ``None`` (not ``False``) for an empty exchange: a suffix-less US ticker often
    arrives with no exchange hint, and the caller defaults that to US.
    """
    if not exchange:
        return None
    s = exchange.strip().upper()
    if not s:
        return None
    if s in _US_EXCHANGE_CODES or any(tok in s for tok in _US_EXCHANGE_TOKENS):
        return True
    return None


def _resolve_market_session(ticker: str | None, exchange: str | None) -> _MarketSession | None:
    """Pick the exchange session for ``ticker``, or ``None`` when undeterminable.

    Resolution order: yfinance ticker suffix (``.HK`` / ``.SS`` / …) → US for a
    suffix-less ticker whose exchange string resolves US (via
    :func:`_classify_us_exchange`, contains-matching the cross-provider field) →
    US for a suffix-less ticker with no exchange hint (the common US case).
    Returns ``None`` for a mapped-foreign suffix or a non-US/unrecognized
    exchange, so the caller can honestly say "unknown" instead of asserting a US
    session for a foreign listing.
    """
    if ticker:
        _, dot, suffix = ticker.rpartition(".")
        if dot:
            return _SESSION_BY_SUFFIX.get(suffix.upper())  # unmapped suffix → None
    # No dotted suffix: a local listing or a US name.
    if exchange and _classify_us_exchange(exchange) is None:
        # Provider names a non-US / unrecognized exchange — don't fake US.
        return None
    return _US_SESSION


def session_close_dt(
    d: date, *, ticker: str | None = None, exchange: str | None = None
) -> datetime | None:
    """The regular-session CLOSE instant on date ``d`` for the resolving exchange,
    as a UTC datetime. ``None`` when the exchange can't be resolved.

    This is the honest ``as_of`` for a daily bar when the provider gave no quote
    timestamp: a close print belongs to the close, not to that calendar day's
    midnight UTC. Stamping midnight systematically OVERSTATES age by the hours
    from midnight to the close (~20h for US equities, whose 16:00 ET close is
    20:00/21:00 UTC) — the root of the "79h ago" report.
    """
    session = _resolve_market_session(ticker, exchange)
    if session is None:
        return None
    local_close = datetime.combine(d, session.close, tzinfo=session.tz)
    return local_close.astimezone(timezone.utc)


def _coerce_quote_dt(value: object) -> datetime | None:
    """Coerce a provider quote timestamp to a tz-aware UTC datetime, or ``None``.

    Handles the shapes the two providers actually emit: FMP ``timestamp`` (unix
    epoch seconds, int) and yfinance ``regularMarketTime`` (unix epoch seconds,
    int) — plus datetime / ISO-string for robustness. Sub-second-zero, naive, and
    millisecond-epoch inputs are normalized; anything unparseable → ``None`` (the
    caller then falls back to the session-close approximation).
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, bool):  # bool is an int subclass — never a timestamp
        return None
    if isinstance(value, (int, float)):
        epoch = float(value)
        if epoch <= 0:
            return None
        if epoch > 1e12:  # milliseconds → seconds
            epoch /= 1000.0
        try:
            return datetime.fromtimestamp(epoch, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        if s.isdigit():
            return _coerce_quote_dt(int(s))
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def derive_price_as_of(
    quote_timestamp: object,
    last_bar_date: date | None,
    *,
    ticker: str | None = None,
    exchange: str | None = None,
    fetched_at: datetime | None = None,
) -> tuple[datetime, bool]:
    """Resolve a price's observation time. Returns ``(as_of, approximate)``.

    ``approximate`` is True when the provider gave no usable quote timestamp and
    we had to infer ``as_of`` from the last bar — the caller flags this with
    ``DEGRADED_QUOTE_TS_MISSING`` so the freshness reads as best-effort.

    Chain (first that resolves wins):
      1. ``quote_timestamp`` — the provider's authoritative observation instant.
      2. session close of ``last_bar_date`` — the bar's true close, NOT midnight
         (and never later than ``fetched_at``: a still-open session has no close
         yet, so the fetch instant is the safest floor).
      3. midnight UTC of ``last_bar_date`` — only when the exchange is unresolved.
      4. ``fetched_at`` (or now) — no bar, no timestamp.
    """
    qt = _coerce_quote_dt(quote_timestamp)
    if qt is not None:
        return qt, False
    if last_bar_date is not None:
        close = session_close_dt(last_bar_date, ticker=ticker, exchange=exchange)
        if close is not None and (fetched_at is None or close <= fetched_at):
            return close, True
        return datetime.combine(last_bar_date, time.min, tzinfo=timezone.utc), True
    if fetched_at is not None:
        return fetched_at, True
    return datetime.now(tz=timezone.utc), True


def compute_session_state(
    as_of: str | None,
    *,
    market_state: str | None = None,
    ticker: str | None = None,
    exchange: str | None = None,
    now: datetime | None = None,
) -> SessionState:
    """Classify a price into one of seven session phases (see ``SessionState``).

    Two signal tiers, primary first:

    1. **``market_state``** — the provider's own per-exchange phase
       (yfinance ``marketState``: REGULAR / PRE / PREPRE / POST / POSTPOST /
       CLOSED). When present and recognized, it is authoritative: it already
       distinguishes pre/post-market from the regular session and from the
       overnight gap, per exchange, without us re-deriving the calendar. Mapped
       through ``_MARKET_STATE_MAP``. An UNRECOGNIZED string falls through to (2).
    2. **Clock window** (fallback, the legacy path, used when ``market_state`` is
       ``None`` or unrecognized) — ``"live"`` only when the resolving exchange's
       regular session is in progress AND today's bar is present; otherwise
       ``"closed"``; ``"unknown"`` when the market can't be resolved (an unmapped
       foreign suffix / unrecognized non-US exchange) — never falsely "closed" on
       a real foreign intraday quote (BUG-081). The fallback cannot distinguish
       pre/post-market (no extended-hours window is modeled), so it only ever
       emits ``live`` / ``closed`` / ``unknown`` — pre/post phases require the
       ``market_state`` signal.

    Computed in the *resolving* exchange's timezone (not always ET): a HK/A-share/
    JP intraday quote sits in ET overnight, so the prior US-only logic stamped it
    "closed" and the freshness pill showed a live quote as a prior-day close.
    Resolving per-ticker fixes that; the US path (suffix-less ticker) is unchanged.

    The client can't derive session state from ``as_of`` alone — its notion of
    "today" is the viewer's local date, which drifts from the exchange date.

    Holidays need no calendar: on a market holiday there is no bar for today, so
    ``as_of < today`` → ``"closed"`` (clock path). Not modeled in the fallback:
    half-day early closes and lunch-break minutes read ``"live"`` (continuous-span
    sessions). When ``market_state`` is present these edge cases are handled by the
    provider's own classification instead.

    Note the signal asymmetry: ``market_state`` resolves the phase directly and
    needs no ``as_of``/exchange resolution; the clock fallback still requires a
    parseable ``as_of`` and a resolvable exchange. ``market_state`` therefore can
    classify pre/post even when ``as_of`` is missing.
    """
    mapped = _MARKET_STATE_MAP.get(market_state.strip().upper()) if market_state else None
    if mapped is not None:
        return mapped
    if not as_of:
        return "closed"
    try:
        as_of_date = date.fromisoformat(as_of[:10])
    except ValueError:
        return "closed"
    session = _resolve_market_session(ticker, exchange)
    if session is None:
        return "unknown"
    now_local = now.astimezone(session.tz) if now else datetime.now(tz=session.tz)
    in_regular_session = (
        now_local.weekday() < 5 and session.open <= now_local.time() < session.close
    )
    if in_regular_session and as_of_date >= now_local.date():
        return "live"
    return "closed"


def _coerce_as_of_dt(value: str | datetime) -> datetime | None:
    """Coerce a provenance ``as_of`` (ISO string or datetime) to a UTC datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def has_newer_session_since(
    as_of: str | datetime,
    *,
    ticker: str | None = None,
    exchange: str | None = None,
    now: datetime | None = None,
) -> bool | None:
    """Is there a regular-session close newer than ``as_of`` settled as of ``now``?

    The calendar gate for rate-safe refresh. Returns:

    * ``True``  — the market is live now, OR a newer settled close exists → a
      provider refetch can yield something new.
    * ``False`` — the market is closed and ``as_of`` already is (≥) the latest
      settled regular-session close → refetching is a guaranteed no-op (a close
      print is immutable until the next open), so the caller may skip the network.
    * ``None``  — the exchange can't be resolved (unmapped foreign suffix /
      unknown non-US exchange) → the caller must NOT assume closed; refetch.

    Safety is asymmetric, which is the whole design: a false *positive* ("newer"
    on a holiday when there is none) costs one wasted fetch that returns the same
    number — harmless. A false *negative* ("no-op" while the session is live)
    would show a stale price — forbidden. The only hard guarantee needed is
    "never ``False`` while the session is live", which rides on the same
    in-session test as :func:`compute_session_state`. That guarantee holds
    WITHOUT a trading calendar: a holiday degrades to a harmless false positive
    (nominal session window, no bar → refetch → unchanged ``as_of``), never a
    false negative — so no ``pandas-market-calendars`` dependency is needed.
    """
    session = _resolve_market_session(ticker, exchange)
    if session is None:
        return None
    as_of_dt = _coerce_as_of_dt(as_of)
    if as_of_dt is None:
        return True  # untrustworthy as_of → fetch (single-flight bounds the cost)
    now_local = now.astimezone(session.tz) if now else datetime.now(tz=session.tz)
    # Live regular session → a newer print is always possible; no as_of compare.
    if now_local.weekday() < 5 and session.open <= now_local.time() < session.close:
        return True
    # Closed: pin the most recent regular session whose close has already passed.
    if now_local.weekday() < 5 and now_local.time() >= session.close:
        last_session_date = now_local.date()  # today's close has settled
    else:
        # Weekend, or a weekday before its open → walk back to the prior weekday.
        d = now_local.date() - timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        last_session_date = d
    last_close = session_close_dt(last_session_date, ticker=ticker, exchange=exchange)
    if last_close is None:
        return None
    return as_of_dt < last_close
