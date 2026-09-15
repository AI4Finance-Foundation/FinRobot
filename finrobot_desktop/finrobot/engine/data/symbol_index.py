"""Local US-equity symbol index for the homepage ticker autocomplete.

The whole SEC ``company_tickers.json`` universe (~10k US symbols) is fetched
ONCE, cached to ``~/.finrobot/symbol_index.json``, and searched in-memory — so a
per-keystroke typeahead never touches a live provider and carries zero FMP
rate-limit exposure. Suggestions are market-cap ranked: the SEC file's natural
order is market-cap descending (verified live 2026-06-16: NVDA/AAPL/MSFT …), so
``ap`` surfaces AAPL first.

Every indexed symbol is funnelled through :func:`validate_ticker` (the single
ticker chokepoint) so a suggestion can never be a symbol the workspace then
422s on — the load-bearing invariant for this feature. A fetch failure degrades
to a stale cache or an empty index; it never raises (core contract ②: never
refuse, just offer less).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from finrobot.engine.data.ticker import validate_ticker

logger = logging.getLogger(__name__)

_SEC_URL = "https://www.sec.gov/files/company_tickers.json"
_CACHE_PATH = Path.home() / ".finrobot" / "symbol_index.json"
_MAX_AGE_DAYS = 1
_FETCH_TIMEOUT = 20.0
_WORD_SPLIT_RE = re.compile(r"[^a-z0-9]+")

# Corporate filler words excluded from company-name matching: nobody searches for
# them, and matching on them is pure noise (a query "c" should not surface NVIDIA
# via "NVIDIA Corp" or Amazon via "Amazon Com"). Real name words ("Apple",
# "Coca", "Cisco") are kept.
_NAME_STOPWORDS = frozenset(
    {
        "corp",
        "corporation",
        "inc",
        "incorporated",
        "co",
        "com",
        "company",
        "companies",
        "cos",
        "holding",
        "holdings",
        "group",
        "grp",
        "ltd",
        "limited",
        "plc",
        "llc",
        "lp",
        "llp",
        "the",
        "and",
        "class",
        "common",
        "series",
        "trust",
    }
)

# How many market-cap ranks an exact ticker match is "worth". Calibrated against
# the live SEC universe (2026-06-16): big enough to lift a mid-cap exact match
# (APP / AppLovin, rank 90) above a mega-cap name match (AAPL / Apple, rank 2)
# when the user types "app"; small enough that a micro-cap exact match
# (AP / Ampco-Pittsburgh, rank 4193) does NOT bury that same mega-cap when the
# user types "ap" (Apple should win). Valid window 88–1880; 1000 sits mid-window.
_EXACT_MATCH_RANK_BONUS = 1000

# The exact-ticker bonus only applies to queries this long or longer. A 1–2 char
# query is usually someone mid-typing toward a bigger company, so market cap wins
# there ("a" → Apple/Amazon, not Agilent/Antero), while a deliberate full-ish
# ticker ("app" → AppLovin, "aapl" → Apple) still gets promoted.
_EXACT_BONUS_MIN_QUERY_LEN = 3


@dataclass(frozen=True)
class SymbolEntry:
    """One indexed security. ``symbol`` is the canonical (validate_ticker) form;
    ``rank`` is the SEC file position (0 = largest market cap)."""

    symbol: str
    name: str
    rank: int
    name_words: tuple[str, ...]


@dataclass(frozen=True)
class SymbolHit:
    symbol: str
    name: str


class SymbolIndex:
    """In-memory searchable view over the symbol universe."""

    def __init__(self, entries: list[SymbolEntry]) -> None:
        self.entries = entries
        self._by_symbol = {e.symbol: e for e in entries}

    def search(self, q: str, limit: int = 8) -> list[SymbolHit]:
        """Rank matches for ``q`` by market cap, with a bounded bonus for an exact
        symbol match (see ``_EXACT_MATCH_RANK_BONUS``): a match is symbol-prefix
        OR company-name word-prefix; an exact symbol hit on a query of
        ``_EXACT_BONUS_MIN_QUERY_LEN``+ chars is promoted by a fixed number of
        ranks so the intended ticker surfaces without burying a far bigger
        company — but short (1–2 char) queries rank purely by market cap so a
        prefix toward a mega-cap isn't buried by a tiny exact ticker. Junk /
        empty / over-long queries return ``[]`` — never raise."""
        q_norm = (q or "").strip().upper()  # tolerate None/empty defensively
        if not q_norm:
            return []
        # Canonical query variant (brk.b -> BRK-B) via the shared chokepoint so a
        # dot-typed class share matches the hyphen symbol SEC/providers use.
        # Junk (CJK / illegal chars / > 12 chars) adds no variant and matches
        # nothing.
        sym_variants = {q_norm}
        try:
            sym_variants.add(validate_ticker(q))
        except ValueError:
            pass
        q_word = q.strip().lower()
        exact_bonus = _EXACT_MATCH_RANK_BONUS if len(q_norm) >= _EXACT_BONUS_MIN_QUERY_LEN else 0

        scored: list[tuple[int, str]] = []  # (score, symbol); lower score ranks first
        for e in self.entries:
            exact = e.symbol in sym_variants
            sym_prefix = any(e.symbol.startswith(v) for v in sym_variants)
            name_prefix = any(w.startswith(q_word) for w in e.name_words)
            if not (exact or sym_prefix or name_prefix):
                continue
            score = e.rank - (exact_bonus if exact else 0)
            scored.append((score, e.symbol))
        scored.sort()
        return [SymbolHit(s, self._by_symbol[s].name) for _, s in scored[:limit]]


def _name_words(name: str) -> tuple[str, ...]:
    return tuple(w for w in _WORD_SPLIT_RE.split(name.lower()) if w and w not in _NAME_STOPWORDS)


def build_index_from_payload(payload: Any) -> SymbolIndex:
    """Build the index from the SEC ``company_tickers.json`` payload (a dict
    keyed by rank, or our cached list of rows). Pure and total: bad / empty
    payloads yield an empty index, never raise. Symbols failing
    :func:`validate_ticker` are dropped (the invariant); the first occurrence
    (best market-cap rank) of a symbol wins."""
    if isinstance(payload, dict):
        rows: list[Any] = list(payload.values())
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []

    entries: list[SymbolEntry] = []
    seen: set[str] = set()
    for rank, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        raw_sym = row.get("ticker")
        name = row.get("title")
        if not isinstance(raw_sym, str) or not isinstance(name, str):
            continue
        try:
            symbol = validate_ticker(raw_sym)
        except ValueError:
            continue  # invariant: never index an unresolvable symbol
        if symbol in seen:
            continue
        seen.add(symbol)
        entries.append(SymbolEntry(symbol, name.strip(), rank, _name_words(name)))
    return SymbolIndex(entries)


# --------------------------------------------------------------------------
# Disk cache + fetch (best-effort; cache write failure must never break a fetch)
# --------------------------------------------------------------------------


def _read_cache(path: Path, *, require_fresh: bool) -> list[Any] | None:
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if require_fresh and not _cache_is_fresh(data):
        return None
    syms = data.get("symbols")
    return syms if isinstance(syms, list) else None


def _cache_is_fresh(data: dict[str, Any]) -> bool:
    ts = data.get("fetched")
    if not isinstance(ts, str):
        return False
    try:
        fetched = datetime.fromisoformat(ts)
    except ValueError:
        return False
    age = datetime.now(timezone.utc) - fetched
    return 0 <= age.total_seconds() and age.days < _MAX_AGE_DAYS


def _write_cache(path: Path, index: SymbolIndex) -> None:
    rows = [{"ticker": e.symbol, "title": e.name} for e in index.entries]
    payload = {"fetched": datetime.now(timezone.utc).isoformat(), "symbols": rows}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    except OSError as exc:  # disk full / perms — caching is an optimization
        logger.warning("symbol index cache write failed: %s", exc)


async def _fetch_sec(user_agent: str) -> Any | None:
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT) as client:
            resp = await client.get(_SEC_URL, headers=headers)
            resp.raise_for_status()
            return resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("symbol index SEC fetch failed: %s", exc)
        return None


async def load_symbol_index(
    user_agent: str, *, cache_path: Path = _CACHE_PATH, force: bool = False
) -> SymbolIndex:
    """Return a built index, preferring a fresh on-disk cache. On a cache miss,
    fetch SEC once and rewrite the cache. On fetch failure, fall back to a stale
    cache if present, else an empty index — never raises."""
    if not force:
        cached = _read_cache(cache_path, require_fresh=True)
        if cached is not None:
            return build_index_from_payload(cached)
    payload = await _fetch_sec(user_agent)
    if payload is None:
        stale = _read_cache(cache_path, require_fresh=False)
        return build_index_from_payload(stale if stale is not None else [])
    index = build_index_from_payload(payload)
    if index.entries:
        _write_cache(cache_path, index)
        return index
    # A non-None SEC payload that builds to 0 entries means the response shape
    # changed (field rename / error body) — don't silently blank the typeahead:
    # warn and prefer a stale cache over an empty index (T2#4 "never silently
    # degrade to empty").
    logger.warning(
        "symbol index: SEC payload yielded 0 entries (possible schema drift) — falling back to cache"
    )
    stale = _read_cache(cache_path, require_fresh=False)
    if stale is not None:
        fallback = build_index_from_payload(stale)
        if fallback.entries:
            return fallback
    return index


# --------------------------------------------------------------------------
# Process-global singleton (warmed at startup, single-flighted on first use)
# --------------------------------------------------------------------------

_INDEX: SymbolIndex | None = None
_LOCK = asyncio.Lock()
# A successful SEC fetch always yields ~10k entries, so an EMPTY index always
# means a failed load (transient fetch error, no cache). We don't cache that as
# final: it's retried, but at most once per backoff so an outage can't turn the
# typeahead into a per-keystroke SEC hammer.
_RETRY_AFTER_S = 60.0
_next_retry_at = 0.0  # monotonic deadline; only consulted when the index is empty


async def _load_into_global(user_agent: str) -> SymbolIndex:
    """Load + publish the global index, arming the retry backoff on an empty
    (failed) result. Caller must hold ``_LOCK``."""
    global _INDEX, _next_retry_at
    _INDEX = await load_symbol_index(user_agent)
    if not _INDEX.entries:
        _next_retry_at = time.monotonic() + _RETRY_AFTER_S
    return _INDEX


async def warm_symbol_index(user_agent: str) -> SymbolIndex:
    """Force a (re)load of the global index. Used by the startup warm task; safe
    to fire-and-forget."""
    async with _LOCK:
        return await _load_into_global(user_agent)


async def ensure_symbol_index(user_agent: str) -> SymbolIndex:
    """Return the warmed index. A populated index is served immediately and stays
    put (refreshed only by the daily on-disk cache / next startup warm). An empty
    index — a transient SEC failure with no cache — is retried at most once per
    ``_RETRY_AFTER_S`` so a single blip doesn't disable the typeahead for the
    whole session, without fetching per keystroke during an outage."""
    idx = _INDEX
    if idx is not None and idx.entries:
        return idx
    if idx is not None and time.monotonic() < _next_retry_at:
        return idx  # empty, but inside the backoff window -> serve degraded
    async with _LOCK:
        idx = _INDEX
        if idx is not None and idx.entries:
            return idx
        if idx is not None and time.monotonic() < _next_retry_at:
            return idx
        return await _load_into_global(user_agent)


def get_symbol_index() -> SymbolIndex:
    """Synchronous accessor — returns an empty index if not yet warmed."""
    return _INDEX if _INDEX is not None else SymbolIndex([])
