"""Unit tests for finrobot.engine.compute.market — deterministic helpers.

Only the pure, synchronous helpers are tested here:
- _build_market_index_list: converts raw price tuples → MarketIndex objects
- fetch_earnings_calendar: returns [] when no FMP key (no HTTP needed)

The async fetch_market_indices / fetch_sector_etfs call real yfinance and are
covered by integration tests tagged @pytest.mark.integration.

Expected values are derived from manual arithmetic — no LLM-generated numbers.
"""
from __future__ import annotations

import pytest

from finrobot.engine.compute.market import (
    _build_market_index_list,
    MarketIndex,
)


# ---------------------------------------------------------------------------
# _build_market_index_list
# ---------------------------------------------------------------------------

def test_build_market_index_list_basic_arithmetic():
    """Price change and change_pct are computed correctly.

    Manual:
      latest=5230.50, prev=5218.00
      change = 5230.50 - 5218.00 = 12.50
      change_pct = (12.50 / 5218.00) * 100 = 0.2395...% ≈ 0.2396
    """
    symbol_map = {"^GSPC": "S&P 500"}
    prices = {"^GSPC": (5230.50, 5218.00)}
    result = _build_market_index_list(symbol_map, prices)

    assert len(result) == 1
    item = result[0]
    assert item.symbol == "^GSPC"
    assert item.name == "S&P 500"
    assert item.price == pytest.approx(5230.50, abs=0.001)
    assert item.change == pytest.approx(12.50, abs=0.001)
    assert item.change_pct == pytest.approx((12.5 / 5218.0) * 100, abs=0.001)


def test_build_market_index_list_negative_change():
    """Negative daily change produces negative change and change_pct.

    Manual: latest=16300.0, prev=16400.0
    change = -100.0, change_pct = (-100/16400)*100 = -0.6098%.
    """
    symbol_map = {"^IXIC": "NASDAQ"}
    prices = {"^IXIC": (16300.0, 16400.0)}
    result = _build_market_index_list(symbol_map, prices)

    assert result[0].change == pytest.approx(-100.0, abs=0.001)
    assert result[0].change_pct == pytest.approx(-0.6098, abs=0.01)


def test_build_market_index_list_missing_symbol_skipped():
    """Symbols missing from prices dict are skipped (graceful degradation)."""
    symbol_map = {"^GSPC": "S&P 500", "^IXIC": "NASDAQ"}
    prices = {"^GSPC": (5230.0, 5218.0)}  # ^IXIC missing
    result = _build_market_index_list(symbol_map, prices)

    assert len(result) == 1
    assert result[0].symbol == "^GSPC"


def test_build_market_index_list_empty_prices():
    """Empty prices dict → empty result list (no crash)."""
    symbol_map = {"^GSPC": "S&P 500"}
    result = _build_market_index_list(symbol_map, {})
    assert result == []


def test_build_market_index_list_zero_prev_price():
    """prev==0 → change_pct returns 0.0 (no ZeroDivisionError).

    Edge case: market halt or data error where previous close is 0.
    """
    symbol_map = {"XSP": "Mini SPX"}
    prices = {"XSP": (100.0, 0.0)}  # zero prev
    result = _build_market_index_list(symbol_map, prices)

    assert len(result) == 1
    assert result[0].change_pct == pytest.approx(0.0)


def test_build_market_index_list_returns_market_index_objects():
    """Return type is list[MarketIndex]."""
    symbol_map = {"XLK": "Tech"}
    prices = {"XLK": (220.0, 218.5)}
    result = _build_market_index_list(symbol_map, prices)
    assert isinstance(result[0], MarketIndex)


def test_build_market_index_list_multiple_symbols():
    """Multiple symbols are all converted correctly."""
    symbol_map = {"A": "Alpha", "B": "Beta", "C": "Gamma"}
    prices = {
        "A": (100.0, 99.0),
        "B": (50.0, 51.0),
        "C": (200.0, 200.0),  # unchanged
    }
    result = _build_market_index_list(symbol_map, prices)

    assert len(result) == 3
    by_sym = {r.symbol: r for r in result}

    assert by_sym["A"].change == pytest.approx(1.0)
    assert by_sym["B"].change == pytest.approx(-1.0)
    assert by_sym["C"].change == pytest.approx(0.0)
    assert by_sym["C"].change_pct == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# fetch_earnings_calendar — no-key fast path (no HTTP)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_earnings_calendar_no_key_returns_empty():
    """fetch_earnings_calendar returns [] immediately when no API key.

    Source: market.py docstring — 'Returns an empty list (not an error)
    when no key is provided'.
    """
    from finrobot.engine.compute.market import fetch_earnings_calendar

    result = await fetch_earnings_calendar(fmp_api_key=None)
    assert result == []


@pytest.mark.asyncio
async def test_fetch_earnings_calendar_empty_string_key_returns_empty():
    """Empty string is falsy — treated same as None."""
    from finrobot.engine.compute.market import fetch_earnings_calendar

    result = await fetch_earnings_calendar(fmp_api_key="")
    assert result == []
