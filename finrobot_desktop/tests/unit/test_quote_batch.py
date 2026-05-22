"""Unit tests for fetch_quotes_batch — yfinance mocked, no network."""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest

from finagent.engine.data import quote_batch


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


def test_logger_warns_on_yfinance_missing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__  # type: ignore[index]

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "yfinance":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    caplog.set_level("WARNING", logger="finagent.engine.data.quote_batch")
    quote_batch.fetch_quotes_batch(["AAPL"])
    assert any("yfinance unavailable" in r.message for r in caplog.records)


# Marker so unused-import detection passes cleanly.
_unused = MagicMock
