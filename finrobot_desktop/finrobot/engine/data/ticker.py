"""The single backend source of truth for ticker-symbol syntax.

Every pipeline entry point — CLI commands, chat tools, ``/api/runs``, the
Coverage routes, and cmd+K search — funnels user-supplied symbols through
:func:`validate_ticker` so the cache key, the provider fan-out, and anything
persisted to the coverage store all agree on ONE definition. Without this,
junk like ``"苹果"``, ``"AAPL;DROP"`` or an over-long string would slip past
one entry point, get cached, and then be re-fanned to providers forever.

MIRROR of ``desktop/src/utils/ticker.ts`` ``TICKER_RE`` — keep the two in sync.
1–12 chars, upper-case A–Z / digits / ``.`` / ``-`` so exotic-but-real symbols
(``BRK.B``, ``BRK-B``, ``RDS.A``) validate.
"""

from __future__ import annotations

import re

# 1–12 chars: upper-case letters, digits, '.' and '-'. The {1,12} bound (not
# {1,10}) is deliberate so dotted/hyphenated class shares stay in range.
_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,12}$")


def validate_ticker(s: str) -> str:
    """Strip, upper-case, and regex-validate a single ticker symbol.

    Returns the normalised (stripped + upper-cased) symbol on success.
    Raises ``ValueError`` with a user-facing message on any miss — empty
    input, illegal characters (CJK, punctuation, whitespace), or > 12 chars.
    """
    normalised = s.strip().upper()
    if not _TICKER_RE.match(normalised):
        raise ValueError(
            f"Invalid ticker '{s}'. Use A-Z/0-9/./- up to 12 chars, e.g. AAPL or BRK.B"
        )
    return normalised


# Non-US-equity market suffixes (Shanghai/Shenzhen/Hong Kong + the common
# Yahoo-style aliases). A bare 6-digit code is a mainland A-share board number
# (e.g. 600519 Kweichow Moutai, 000001 Ping An). Used by callers — like the
# backtest engine — that only model US-equity microstructure and must reject
# anything else rather than emit an untrustworthy result (BUG-068).
_NON_US_SUFFIXES = (".SS", ".SZ", ".SH", ".HK")
_A_SHARE_CODE_RE = re.compile(r"^\d{6}$")


def is_us_equity_ticker(ticker: str) -> bool:
    """Best-effort check that a (validated) ticker is a US-listed equity.

    Returns ``False`` for A-share / HK symbols — ``.SS``/``.SZ``/``.SH``/``.HK``
    suffixes and bare 6-digit mainland board codes. This is intentionally a
    coarse allow-by-default heuristic: anything that doesn't look like a CN/HK
    symbol is treated as US. Callers that need a hard gate (backtest) use it to
    reject, not to silently route.
    """
    t = ticker.strip().upper()
    if t.endswith(_NON_US_SUFFIXES):
        return False
    if _A_SHARE_CODE_RE.match(t):
        return False
    return True
