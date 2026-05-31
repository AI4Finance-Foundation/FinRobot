"""Unit tests for finrobot.engine.compute.market — earnings calendar.

The technical snapshot (technical_payload / get_technicals) is covered by
test_market_technicals.py. Here we cover the FMP earnings-calendar no-key fast
path (no HTTP needed). The index/ETF display helpers were removed when market.py
moved onto DataLayer.fetch_canonical (门一收口, ADR-0006).
"""

from __future__ import annotations

import pytest

from finrobot.engine.compute.market import fetch_earnings_calendar


@pytest.mark.asyncio
async def test_fetch_earnings_calendar_no_key_returns_empty():
    """fetch_earnings_calendar returns [] immediately when no API key.

    Source: market.py docstring — 'Returns an empty list (not an error)
    when no key is provided'.
    """
    result = await fetch_earnings_calendar(fmp_api_key=None)
    assert result == []


@pytest.mark.asyncio
async def test_fetch_earnings_calendar_empty_string_key_returns_empty():
    """Empty string is falsy — treated same as None."""
    result = await fetch_earnings_calendar(fmp_api_key="")
    assert result == []
