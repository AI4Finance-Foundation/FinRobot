"""market_cap_on_live_price must never mint a non-finite / negative cap
(W3-B路 · finiteness + sign).

cached_price / cached_shares / live_price were sign-guarded but ``cached_market_cap``
was not, and ``live_price <= 0`` lets NaN/Inf through (both comparisons False for
NaN). So a corrupt cached cap could be divided into a negative share count, and a
NaN live price minted a NaN cap shown right beside a price. A cap is valid only if
finite and positive.
"""

from __future__ import annotations

import math

import pytest

from finrobot.engine.primitives.market_cap import market_cap_on_live_price


@pytest.mark.parametrize("bad_live", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_live_price_returns_cached_not_nan(bad_live: float) -> None:
    mc = market_cap_on_live_price(
        cached_market_cap=100.0, cached_shares=10.0, cached_price=10.0, live_price=bad_live
    )
    assert mc == 100.0
    assert mc is not None and math.isfinite(mc)


def test_negative_cached_cap_not_minted_into_negative_shares() -> None:
    # Corrupt (negative) cached cap, no reported shares: the derive branch must
    # NOT compute shares = -1000/10 and mint a -5000 cap. Returns None.
    mc = market_cap_on_live_price(
        cached_market_cap=-1000.0, cached_shares=None, cached_price=10.0, live_price=5.0
    )
    assert mc is None


def test_nan_cached_shares_falls_back_to_derive() -> None:
    # NaN shares are unusable → derive from cap/price (1000/10=100), ×5 = 500.
    mc = market_cap_on_live_price(
        cached_market_cap=1000.0, cached_shares=float("nan"), cached_price=10.0, live_price=5.0
    )
    assert mc == pytest.approx(500.0)


def test_nan_cached_cap_in_derive_returns_none() -> None:
    mc = market_cap_on_live_price(
        cached_market_cap=float("nan"), cached_shares=None, cached_price=10.0, live_price=5.0
    )
    assert mc is None
