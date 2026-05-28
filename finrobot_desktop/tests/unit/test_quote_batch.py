"""Unit tests for fetch_quotes_batch — yfinance mocked, no network."""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest

from finrobot.engine.data import quote_batch


def _make_yf_stub(quotes: dict[str, float | None]) -> types.ModuleType:
    """Build a fake yfinance module returning the given last_price per symbol."""
    fake = types.ModuleType("yfinance")

    class _FastInfo:
        def __init__(self, price: float | None) -> None:
            self.last_price = price

    class _Ticker:
        def __init__(self, symbol: str) -> None:
            self.fast_info = _FastInfo(quotes.get(symbol.upper()))

    class _Tickers:
        def __init__(self, joined: str) -> None:
            self.tickers = {s.upper(): _Ticker(s) for s in joined.split()}

    fake.Ticker = _Ticker  # type: ignore[attr-defined]
    fake.Tickers = _Tickers  # type: ignore[attr-defined]
    return fake


@pytest.fixture(autouse=True)
def _restore_yfinance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make sure other tests don't leak our stubbed yfinance."""
    monkeypatch.delitem(sys.modules, "yfinance", raising=False)


def test_empty_input_returns_empty_dict() -> None:
    assert quote_batch.fetch_quotes_batch([]) == {}
    assert quote_batch.fetch_quotes_batch(["", "  "]) == {}


def test_happy_path_three_tickers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        _make_yf_stub({"AAPL": 187.32, "MSFT": 412.10, "NVDA": 905.5}),
    )
    out = quote_batch.fetch_quotes_batch(["AAPL", "MSFT", "NVDA"])
    assert out == {"AAPL": 187.32, "MSFT": 412.10, "NVDA": 905.5}


def test_missing_ticker_returns_none_for_that_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        _make_yf_stub({"AAPL": 187.32, "ZZZZ": None}),
    )
    out = quote_batch.fetch_quotes_batch(["AAPL", "ZZZZ"])
    assert out["AAPL"] == 187.32
    assert out["ZZZZ"] is None


def test_case_normalised_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "yfinance", _make_yf_stub({"AAPL": 187.32}))
    out = quote_batch.fetch_quotes_batch(["aapl"])
    assert out == {"AAPL": 187.32}


def test_yfinance_missing_returns_all_none(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force ImportError on `import yfinance` inside the helper.
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__  # type: ignore[index]

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "yfinance":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    out = quote_batch.fetch_quotes_batch(["AAPL", "MSFT"])
    assert out == {"AAPL": None, "MSFT": None}


def test_batch_init_failure_falls_back_to_per_ticker(monkeypatch: pytest.MonkeyPatch) -> None:
    """If yf.Tickers raises, fallback to single-ticker path per symbol."""

    fake = types.ModuleType("yfinance")

    class _FastInfo:
        def __init__(self, price: float | None) -> None:
            self.last_price = price

    class _Ticker:
        def __init__(self, sym: str) -> None:
            self.fast_info = _FastInfo({"AAPL": 100.0, "MSFT": 200.0}.get(sym.upper()))

    def _bad_tickers(_joined: str) -> Any:
        raise OSError("network down")

    fake.Ticker = _Ticker  # type: ignore[attr-defined]
    fake.Tickers = _bad_tickers  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", fake)

    out = quote_batch.fetch_quotes_batch(["AAPL", "MSFT"])
    assert out == {"AAPL": 100.0, "MSFT": 200.0}


def test_attribute_error_on_one_ticker_is_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """One bad ticker shouldn't poison the others."""
    fake = types.ModuleType("yfinance")

    class _FastInfoBad:
        @property
        def last_price(self) -> float:
            raise AttributeError("kaboom")

    class _FastInfoGood:
        last_price = 50.0

    class _Ticker:
        def __init__(self, sym: str) -> None:
            self.fast_info = _FastInfoBad() if sym.upper() == "BAD" else _FastInfoGood()

    class _Tickers:
        def __init__(self, joined: str) -> None:
            self.tickers = {s.upper(): _Ticker(s) for s in joined.split()}

    fake.Ticker = _Ticker  # type: ignore[attr-defined]
    fake.Tickers = _Tickers  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", fake)

    out = quote_batch.fetch_quotes_batch(["GOOD", "BAD"])
    assert out == {"GOOD": 50.0, "BAD": None}


def test_yfinance_rate_limit_propagates_as_QuoteFetchRateLimited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Yahoo 429 must NOT be silently mapped to None.

    Before this guard a single rate-limit error inside the batch loop
    was caught and the ticker's slot filled with ``None``. The async
    cache then wrote that None across L1+L2 for the full TTL, taking
    the landing dashboard cold even after the upstream recovered.
    Now the batch raises ``QuoteFetchRateLimited`` so the cache layer
    preserves stale values instead.
    """
    fake = types.ModuleType("yfinance")
    fake_exceptions = types.ModuleType("yfinance.exceptions")

    class YFException(Exception):
        pass

    class YFRateLimitError(YFException):
        pass

    class _FastInfoGood:
        last_price = 50.0

    class _FastInfoLimited:
        @property
        def last_price(self) -> float:
            raise YFRateLimitError("Too Many Requests")

    class _Ticker:
        def __init__(self, sym: str) -> None:
            self.fast_info = _FastInfoLimited() if sym.upper() == "LIMIT" else _FastInfoGood()

    class _Tickers:
        def __init__(self, joined: str) -> None:
            self.tickers = {s.upper(): _Ticker(s) for s in joined.split()}

    fake.Ticker = _Ticker  # type: ignore[attr-defined]
    fake.Tickers = _Tickers  # type: ignore[attr-defined]
    fake_exceptions.YFException = YFException  # type: ignore[attr-defined]
    fake_exceptions.YFRateLimitError = YFRateLimitError  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    monkeypatch.setitem(sys.modules, "yfinance.exceptions", fake_exceptions)

    with pytest.raises(quote_batch.QuoteFetchRateLimited):
        quote_batch.fetch_quotes_batch(["GOOD", "LIMIT"])


def test_fetch_one_rate_limit_raises_QuoteFetchRateLimited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The single-ticker fallback path also has to raise on 429.

    The async cached entry point fans out to ``_fetch_one`` per ticker;
    if it swallowed the rate limit the cache would still write None.
    """
    fake = types.ModuleType("yfinance")
    fake_exceptions = types.ModuleType("yfinance.exceptions")

    class YFException(Exception):
        pass

    class YFRateLimitError(YFException):
        pass

    class _FastInfoLimited:
        @property
        def last_price(self) -> float:
            raise YFRateLimitError("HTTP 429 Too Many Requests")

    class _Ticker:
        def __init__(self, _sym: str) -> None:
            self.fast_info = _FastInfoLimited()

    fake.Ticker = _Ticker  # type: ignore[attr-defined]
    fake_exceptions.YFException = YFException  # type: ignore[attr-defined]
    fake_exceptions.YFRateLimitError = YFRateLimitError  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    monkeypatch.setitem(sys.modules, "yfinance.exceptions", fake_exceptions)

    with pytest.raises(quote_batch.QuoteFetchRateLimited):
        quote_batch._fetch_one("AAPL")


def test_fetch_one_message_only_rate_limit_still_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When yfinance surfaces 429 as bare RuntimeError/YFException without
    the typed subclass, message-sniffing must still catch it.

    Real-world repro: ``yfinance.data._make_request`` historically threw
    ``Exception('HTTP Error 429')`` on some code paths before yfinance
    added the typed ``YFRateLimitError`` class. The fix must handle both.
    """
    fake = types.ModuleType("yfinance")

    class _FastInfoLimited:
        @property
        def last_price(self) -> float:
            raise RuntimeError("Too Many Requests. Rate limited.")

    class _Ticker:
        def __init__(self, _sym: str) -> None:
            self.fast_info = _FastInfoLimited()

    fake.Ticker = _Ticker  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    monkeypatch.delitem(sys.modules, "yfinance.exceptions", raising=False)

    with pytest.raises(quote_batch.QuoteFetchRateLimited):
        quote_batch._fetch_one("AAPL")


def test_logger_warns_on_yfinance_missing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__  # type: ignore[index]

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "yfinance":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    caplog.set_level("WARNING", logger="finrobot.engine.data.quote_batch")
    quote_batch.fetch_quotes_batch(["AAPL"])
    assert any("yfinance unavailable" in r.message for r in caplog.records)


# ─────────────────────────────────────────────────────────────────────────────
# Async cached entry point
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cached_warm_hit_skips_yfinance(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Second call within TTL must return from cache without invoking the
    underlying yfinance helper. Eliminates the 7-second fan-out from the
    dashboard hit-rate + recent-research endpoints."""
    monkeypatch.setenv("HOME", str(tmp_path))
    quote_batch.reset_quote_cache_singleton()

    yf_calls: list[str] = []

    def fake_one(symbol: str) -> float | None:
        yf_calls.append(symbol)
        return 200.0

    monkeypatch.setattr(quote_batch, "_fetch_one", fake_one)

    out1 = await quote_batch.fetch_quotes_batch_cached(["AAPL", "MSFT"])
    assert out1 == {"AAPL": 200.0, "MSFT": 200.0}
    assert sorted(yf_calls) == ["AAPL", "MSFT"]

    out2 = await quote_batch.fetch_quotes_batch_cached(["AAPL"])
    assert out2 == {"AAPL": 200.0}
    assert sorted(yf_calls) == ["AAPL", "MSFT"]  # no extra fetch — L1 hit

    quote_batch.reset_quote_cache_singleton()


@pytest.mark.asyncio
async def test_cached_empty_batch_is_noop(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    quote_batch.reset_quote_cache_singleton()
    out = await quote_batch.fetch_quotes_batch_cached([])
    assert out == {}
    quote_batch.reset_quote_cache_singleton()


@pytest.mark.asyncio
async def test_cached_cold_path_fans_out_per_ticker_concurrently(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """4 ticker cold fetch must run concurrently, not in a serial loop.

    Uses ``threading.Barrier(4)`` rather than a wall-time threshold so the
    assertion is timing-independent — slow CI runners won't flake. A
    concurrent fan-out has 4 threads sitting at ``barrier.wait()``
    simultaneously and clears it in one step; a serial loop would have
    only 1 thread inside ``_fetch_one`` at any moment and deadlock the
    barrier until its timeout, raising ``BrokenBarrierError``.

    Without per-ticker concurrency the lifespan warmup blocks ~6s on
    sequential yfinance HTTPS round-trips — see
    docs/superpowers/plans/2026-05-23-storage-overhaul-and-landing-perf.md.
    """
    import threading

    monkeypatch.setenv("HOME", str(tmp_path))
    quote_batch.reset_quote_cache_singleton()

    barrier = threading.Barrier(parties=4, timeout=2.0)

    def gated(symbol: str) -> float | None:
        barrier.wait()  # blocks until 4 concurrent threads arrive
        return 100.0

    monkeypatch.setattr(quote_batch, "_fetch_one", gated)

    out = await quote_batch.fetch_quotes_batch_cached(["A", "B", "C", "D"])
    assert out == {"A": 100.0, "B": 100.0, "C": 100.0, "D": 100.0}
    assert barrier.n_waiting == 0  # all 4 cleared the barrier cleanly

    quote_batch.reset_quote_cache_singleton()


# Marker so unused-import detection passes cleanly.
_unused = MagicMock
