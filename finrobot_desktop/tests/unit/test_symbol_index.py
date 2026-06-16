"""Unit tests for the homepage ticker autocomplete index (symbol_index).

Acceptance baseline frozen BEFORE implementation (spec
``specs/research/股票搜索-typeahead自动补全-设计-2026-06-16.md`` §8.2/§8.3).
Expected results trace to external truth (market-cap ordering of the real SEC
universe, verified live 2026-06-16: NVDA/AAPL/MSFT … descending).
"""

from __future__ import annotations

import pytest

from finrobot.engine.data.symbol_index import (
    SymbolEntry,
    SymbolIndex,
    build_index_from_payload,
)
from finrobot.engine.data.ticker import validate_ticker

# SEC company_tickers.json shape: dict keyed by stringified rank "0".."N",
# insertion order = market-cap descending (the file's natural order). One junk
# row (illegal char) that MUST be excluded by the load-bearing invariant.
_FAKE_SEC = {
    "0": {"cik_str": 1, "ticker": "NVDA", "title": "NVIDIA CORP"},
    "1": {"cik_str": 2, "ticker": "AAPL", "title": "Apple Inc."},
    "2": {"cik_str": 3, "ticker": "MSFT", "title": "MICROSOFT CORP"},
    "3": {"cik_str": 4, "ticker": "AMAT", "title": "Applied Materials Inc"},
    "4": {"cik_str": 5, "ticker": "APO", "title": "Apollo Global Management"},
    "5": {"cik_str": 6, "ticker": "APP", "title": "AppLovin Corp"},
    "6": {"cik_str": 7, "ticker": "MU", "title": "Micron Technology Inc"},
    "7": {"cik_str": 8, "ticker": "BRK-B", "title": "BERKSHIRE HATHAWAY INC"},
    "8": {"cik_str": 9, "ticker": "BRK-A", "title": "BERKSHIRE HATHAWAY INC"},
    "9": {"cik_str": 10, "ticker": "AAOI", "title": "APPLIED OPTOELECTRONICS"},
    "10": {"cik_str": 11, "ticker": "BAD;X", "title": "Junk Co"},  # invalid -> excluded
}


@pytest.fixture
def index() -> SymbolIndex:
    return build_index_from_payload(_FAKE_SEC)


def _symbols(hits) -> list[str]:
    return [h.symbol for h in hits]


# --- build / invariant -----------------------------------------------------

def test_build_excludes_invalid_symbols(index: SymbolIndex) -> None:
    """Load-bearing invariant: every indexed symbol passes validate_ticker, so a
    suggestion can never be a symbol the workspace then 422s on. The junk row is
    dropped."""
    assert "BAD;X" not in {e.symbol for e in index.entries}
    for e in index.entries:
        # must not raise and must already be canonical (idempotent)
        assert validate_ticker(e.symbol) == e.symbol


def test_build_preserves_market_cap_rank(index: SymbolIndex) -> None:
    ranks = {e.symbol: e.rank for e in index.entries}
    assert ranks["NVDA"] < ranks["AAPL"] < ranks["MSFT"] < ranks["MU"]


# --- acceptance table 8.2 --------------------------------------------------

def test_exact_symbol_ranks_first(index: SymbolIndex) -> None:
    assert _symbols(index.search("AAPL"))[0] == "AAPL"


def test_exact_symbol_beats_bigger_name_match(index: SymbolIndex) -> None:
    """Typing the exact ticker APP surfaces AppLovin first even though Apple
    (bigger, name starts with 'app') also matches."""
    assert _symbols(index.search("APP"))[0] == "APP"


def test_prefix_ap_surfaces_apple_top3(index: SymbolIndex) -> None:
    """'ap' has NO symbol-prefix hit on AAPL (AAPL starts 'AA'); AAPL matches via
    the company-name word 'Apple' and must still rank in the top 3 on market cap,
    above smaller symbol-prefix hits like APO/APP."""
    top3 = _symbols(index.search("ap"))[:3]
    assert "AAPL" in top3
    assert top3[0] == "AAPL"


def test_prefix_nvd_nvidia_first(index: SymbolIndex) -> None:
    assert _symbols(index.search("nvd"))[0] == "NVDA"


def test_company_name_match(index: SymbolIndex) -> None:
    assert "AAPL" in _symbols(index.search("apple"))


def test_micro_ranks_msft_before_mu(index: SymbolIndex) -> None:
    """Both Microsoft and Micron match 'micro' by name; the bigger cap (MSFT)
    must come first."""
    hits = _symbols(index.search("micro"))
    assert hits.index("MSFT") < hits.index("MU")


def test_brk_returns_both_classes(index: SymbolIndex) -> None:
    hits = _symbols(index.search("brk"))
    assert "BRK-B" in hits and "BRK-A" in hits
    assert hits.index("BRK-B") < hits.index("BRK-A")  # B is the bigger/earlier class


def test_dotted_share_class_query_canonicalizes(index: SymbolIndex) -> None:
    """User types 'brk.b' (financial-press dot form); must match the canonical
    hyphen symbol the providers (and SEC) use, so selecting it navigates to a
    resolvable ticker."""
    assert _symbols(index.search("brk.b"))[0] == "BRK-B"


def test_limit_respected(index: SymbolIndex) -> None:
    assert len(index.search("a", limit=2)) == 2


# --- exact-match bonus calibration (real-rank ordering, spec "大盘股排第一") ----
# Built with real SEC ranks so the bonus magnitude is actually exercised (the
# small acceptance fixture above can't, since every rank < the bonus).

def _idx(*entries: tuple[str, str, int]) -> SymbolIndex:
    return SymbolIndex(
        [
            SymbolEntry(sym, name, rank, tuple(name.lower().replace(",", " ").split()))
            for sym, name, rank in entries
        ]
    )


def test_micro_cap_exact_does_not_bury_megacap_name() -> None:
    """User types 'ap': the mega-cap name match AAPL (Apple, rank 2) must rank
    above the micro-cap EXACT ticker AP (Ampco-Pittsburgh, rank 4193). Otherwise
    a $60M shell buries Apple — violates the spec's '大盘股排第一'."""
    idx = _idx(("AAPL", "Apple Inc.", 2), ("AP", "Ampco-Pittsburgh Corp", 4193))
    assert idx.search("ap")[0].symbol == "AAPL"
    assert idx.search("AP")[0].symbol == "AAPL"


def test_mid_cap_exact_beats_megacap_name() -> None:
    """User types the exact ticker 'app': AppLovin (exact, rank 90) should win
    over Apple (name match, rank 2) — typing a real ticker is a strong intent."""
    idx = _idx(("AAPL", "Apple Inc.", 2), ("APP", "AppLovin Corp", 90))
    assert idx.search("app")[0].symbol == "APP"


def test_micro_cap_exact_does_not_bury_tesla() -> None:
    idx = _idx(("TSLA", "Tesla Inc.", 6), ("TE", "Tdh Holdings", 1886))
    assert idx.search("te")[0].symbol == "TSLA"


# --- dirty input / degradation --------------------------------------------

@pytest.mark.parametrize("q", ["", "   ", "zzzz", "'; --", "苹果", "A" * 50])
def test_dirty_input_safe_empty_or_no_crash(index: SymbolIndex, q: str) -> None:
    hits = index.search(q)  # must never raise
    assert isinstance(hits, list)
    if q.strip() in ("", "zzzz", "'; --", "苹果") or len(q) > 12:
        assert hits == []


def test_empty_payload_yields_empty_index_no_raise() -> None:
    for payload in ({}, None, []):
        idx = build_index_from_payload(payload)  # type: ignore[arg-type]
        assert idx.entries == []
        assert idx.search("a") == []


def test_duplicate_symbol_kept_once_best_rank() -> None:
    payload = {
        "0": {"cik_str": 1, "ticker": "FOO", "title": "Foo A"},
        "1": {"cik_str": 2, "ticker": "FOO", "title": "Foo B"},
    }
    idx = build_index_from_payload(payload)
    foos = [e for e in idx.entries if e.symbol == "FOO"]
    assert len(foos) == 1
    assert foos[0].rank == 0  # earliest (bigger cap) wins
