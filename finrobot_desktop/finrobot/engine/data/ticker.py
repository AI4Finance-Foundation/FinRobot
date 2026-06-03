"""The single backend source of truth for ticker-symbol syntax.

Every pipeline entry point — CLI commands, chat tools, ``/api/runs``, the
Coverage routes, and cmd+K search — funnels user-supplied symbols through
:func:`validate_ticker` so the cache key, the provider fan-out, and anything
persisted to the coverage store all agree on ONE definition. Without this,
junk like ``"苹果"``, ``"AAPL;DROP"`` or an over-long string would slip past
one entry point, get cached, and then be re-fanned to providers forever.

MIRROR of ``ui/src/utils/ticker.ts`` ``TICKER_RE`` — keep the two in sync.
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
