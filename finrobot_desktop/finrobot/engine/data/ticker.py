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

# US share-class canonicalization. Vendors split on the separator: the dotted
# form ``BRK.B`` is the financial-press convention, but the providers want the
# HYPHEN form — probed 2026-06-10: yfinance (the primary, always-on provider)
# returns prices for BRK-B / BF-B / BRK-A and "no data / delisted" for BRK.B /
# BF.B / BRK.A. Without a chokepoint, ``BRK.B`` and ``BRK-B`` split into two
# cache / coverage slots for one security AND the dotted form a user naturally
# types silently resolves to nothing. We canonicalize the dot → hyphen, but ONLY
# for a probed allowlist of class letters {A, B}: single-letter *exchange*
# suffixes (``RIO.L`` London, ``7203.T`` Tokyo — both probed, resolve only
# dotted) MUST keep the dot, and A/B are never Yahoo exchange codes. The
# alpha-root anchor excludes numeric-root foreign symbols (7203.T); multi-char
# foreign suffixes (.SS/.HK/.PA/.DE/...) never match the single-letter group.
# (FMP's class-share convention is [待验] — key usage limit hit during probing —
# but FMP is an optional fallback behind yfinance, so a worst-case dot-preferring
# FMP still fails over to the hyphen-correct yfinance.)
_US_SHARE_CLASS_SUFFIXES = frozenset({"A", "B"})
_SHARE_CLASS_RE = re.compile(r"^([A-Z][A-Z0-9]{0,5})\.([A-Z])$")


def _canonicalize_share_class(symbol: str) -> str:
    """Map a US dotted share-class symbol (``BRK.B``) to the hyphen form
    (``BRK-B``) the providers require, leaving exchange-suffixed foreign symbols
    (``RIO.L``, ``BMW.DE``, ``600519.SS``) and plain tickers untouched."""
    m = _SHARE_CLASS_RE.match(symbol)
    if m is not None and m.group(2) in _US_SHARE_CLASS_SUFFIXES:
        return f"{m.group(1)}-{m.group(2)}"
    return symbol


def validate_ticker(s: str) -> str:
    """Strip, upper-case, regex-validate, and canonicalize a single ticker.

    Returns the normalised symbol on success — stripped, upper-cased, and with US
    share-class dot forms folded to the hyphen the providers accept (``brk.b`` →
    ``BRK-B``) so one security never splits across two cache / coverage slots.
    Raises ``ValueError`` with a user-facing message on any miss — empty input,
    illegal characters (CJK, punctuation, whitespace), or > 12 chars.
    """
    normalised = s.strip().upper()
    if not _TICKER_RE.match(normalised):
        raise ValueError(
            f"Invalid ticker '{s}'. Use A-Z/0-9/./- up to 12 chars, e.g. AAPL or BRK.B"
        )
    return _canonicalize_share_class(normalised)


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
