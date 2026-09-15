"""market_cap_on_live_price (class C1): a served market_cap must equal
shares × the served current_price.

Confirmed live bug (probe 2026-06-09): /api/data/{t}/price grafted the FINANCIALS
cache's absolute market_cap — priced at that snapshot's own (prior-close) price —
onto a payload already showing a fresher live current_price, so market_cap /
current_price ≠ the true share count. AAPL +1.92%, MU −9.0%, NVDA −1.73%, and
/price disagreed with /financials on the same field. This primitive recomputes the
cap from a price-consistent share count so the two epochs can't be spliced.
"""

from __future__ import annotations

import pytest

from finrobot.engine.primitives.market_cap import market_cap_on_live_price


def test_marks_to_live_with_reported_shares():
    """AAPL probe: cap frozen at prior close 307.34, live 301.54, shares known."""
    mc = market_cap_on_live_price(
        cached_market_cap=4_514_011_993_040,
        cached_shares=14_687_356_000,
        cached_price=307.34,
        live_price=301.54,
    )
    assert mc == pytest.approx(14_687_356_000 * 301.54)
    assert mc == pytest.approx(4_428_825_328_240, rel=1e-9)  # = FMP live marketCap


def test_derives_shares_when_missing():
    """MU probe: shares absent → implied = cap/cached_price, then × live price."""
    mc = market_cap_on_live_price(
        cached_market_cap=974_369_997_300,
        cached_shares=None,
        cached_price=864.01,
        live_price=949.28,
    )
    implied_shares = 974_369_997_300 / 864.01
    assert mc == pytest.approx(implied_shares * 949.28)


def test_no_live_price_returns_cached_unchanged():
    assert (
        market_cap_on_live_price(
            cached_market_cap=100.0, cached_shares=10.0, cached_price=10.0, live_price=None
        )
        == 100.0
    )
    assert (
        market_cap_on_live_price(
            cached_market_cap=100.0, cached_shares=10.0, cached_price=10.0, live_price=0.0
        )
        == 100.0
    )


def test_no_usable_inputs_returns_cached():
    assert (
        market_cap_on_live_price(
            cached_market_cap=None, cached_shares=None, cached_price=None, live_price=300.0
        )
        is None
    )


def test_same_epoch_is_identity():
    """cached price == live price → marking is a no-op (the US-issuer common case)."""
    mc = market_cap_on_live_price(
        cached_market_cap=3_000e9, cached_shares=15e9, cached_price=200.0, live_price=200.0
    )
    assert mc == pytest.approx(3_000e9)


def test_marked_cap_is_consistent_with_live_price():
    """The invariant: marked_cap / live_price == the share count used."""
    mc = market_cap_on_live_price(
        cached_market_cap=974_369_997_300,
        cached_shares=1_127_730_000,
        cached_price=864.01,
        live_price=949.28,
    )
    assert mc is not None
    assert mc / 949.28 == pytest.approx(1_127_730_000)
