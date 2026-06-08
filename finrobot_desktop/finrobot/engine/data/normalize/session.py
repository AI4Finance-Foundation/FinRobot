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

from datetime import date, datetime, time, timezone
from typing import Literal
from zoneinfo import ZoneInfo

SessionState = Literal["live", "closed", "unknown"]


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

# US exchange codes (yfinance/FMP) — used when a ticker carries no suffix but
# the provider reports an exchange, to confirm a US session vs. fall to unknown.
_US_EXCHANGE_CODES = frozenset(
    {"NMS", "NYQ", "NGM", "NCM", "NASDAQ", "NYSE", "AMEX", "PCX", "BATS", "ASE"}
)


def _resolve_market_session(ticker: str | None, exchange: str | None) -> _MarketSession | None:
    """Pick the exchange session for ``ticker``, or ``None`` when undeterminable.

    Resolution order: yfinance ticker suffix (``.HK`` / ``.SS`` / …) → US for a
    suffix-less ticker carrying a known US exchange code → US for a suffix-less
    ticker with no exchange hint (the common US case). Returns ``None`` for a
    suffix we don't map, so the caller can honestly say "unknown" instead of
    asserting a US session for a foreign listing.
    """
    if ticker:
        _, dot, suffix = ticker.rpartition(".")
        if dot:
            return _SESSION_BY_SUFFIX.get(suffix.upper())  # unmapped suffix → None
    # No dotted suffix: a local listing or a US name.
    if exchange and exchange.upper() not in _US_EXCHANGE_CODES:
        # Provider names a non-US exchange we don't recognize — don't fake US.
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
    ticker: str | None = None,
    exchange: str | None = None,
    now: datetime | None = None,
) -> SessionState:
    """Classify ``current_price`` as a live intraday quote or a session close.

    Returns ``"live"`` only when the resolving exchange's regular session is in
    progress AND today's bar is present; ``"closed"`` when the session is over
    or no today-bar exists; and ``"unknown"`` when the market can't be resolved
    (an unmapped foreign suffix / unrecognized non-US exchange) — never falsely
    "closed" on a real foreign intraday quote (BUG-081).

    Computed in the *resolving* exchange's timezone (not always ET): a HK/A-share/
    JP intraday quote sits in ET overnight, so the prior US-only logic stamped it
    "closed" and the freshness pill showed a live quote as a prior-day close.
    Resolving per-ticker fixes that; the US path (suffix-less ticker) is unchanged.

    The client can't derive session state from ``as_of`` alone — its notion of
    "today" is the viewer's local date, which drifts from the exchange date.

    Holidays need no calendar: on a market holiday there is no bar for today, so
    ``as_of < today`` → ``"closed"``. Not modeled: half-day early closes and
    lunch-break minutes read ``"live"`` (continuous-span sessions). Pre/post-market
    quotes report ``"closed"`` (only the regular session counts as live).
    """
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
