"""``_current_ev_ebitda_override`` must actually return the canonical TTM
EV/EBITDA (W1-C2 follow-up).

The W1-C2 fix (single authoritative current EV/EBITDA) wired the standalone
/historical-bands route to ``_current_ev_ebitda_override``, but the helper
guarded ``isinstance(fin, FinancialData)`` on the result of
``fetch_canonical(FINANCIALS)`` — which returns a ``NormalizedFinancials``, not
a ``FinancialData``. So the guard was always False, the override was always
None, and the band silently kept falling back to the trailing-ANNUAL
``samples[-1]`` multiple — i.e. the W1-C2 caliber flip the fix was meant to
close was still live. The helper must ``extract_financial_data`` (FINANCIALS +
PRICE) exactly like the /financials route before computing the multiple.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from finrobot.engine.data.interface import DataResult
from finrobot.engine.data.normalize.financials import normalize_financials
from finrobot.engine.data.normalize.price import normalize_price
from finrobot.engine.data.types import DataType
from finrobot.routes.valuation import _current_ev_ebitda_override


def _make_fin():
    raw = DataResult(
        data=dict(
            revenue=100e9,
            ebitda=35e9,
            net_income=20e9,
            gross_margin=0.47,
            operating_margin=0.28,
            pe_ratio=28.5,
            market_cap=3e12,
            shares_outstanding=15e9,
            current_price=200.0,
            total_debt=50e9,
            total_cash=20e9,
        ),
        provider="yfinance",
        ticker="AAPL",
        data_type="financials",
        timestamp=datetime.now(tz=timezone.utc),
    )
    return normalize_financials(raw)


def _make_price():
    raw = DataResult(
        data={
            "current_price": 200.0,
            "price_history": [{"date": "2024-12-01", "close": 200.0}],
        },
        provider="yfinance",
        ticker="AAPL",
        data_type="price",
        timestamp=datetime.now(tz=timezone.utc),
    )
    return normalize_price(raw)


class _StubLayer:
    """fetch_canonical returns the canonical (NormalizedFinancials/Price) shapes
    the real data layer hands the route — NOT pre-extracted FinancialData."""

    async def fetch_canonical(self, data_type: DataType | str, ticker: str):
        if DataType(data_type) == DataType.PRICE:
            return _make_price()
        return _make_fin()


@pytest.mark.asyncio
async def test_current_ev_ebitda_override_returns_ttm_multiple_not_none():
    # EV = market_cap + (total_debt − total_cash) = 3e12 + 30e9 = 3.03e12
    # TTM EV/EBITDA = 3.03e12 / 35e9 = 86.571…
    override = await _current_ev_ebitda_override("AAPL", _StubLayer(), "ev_ebitda")
    assert override is not None, "override must not be inert (was the W1-C2 isinstance bug)"
    assert override == pytest.approx((3e12 + 30e9) / 35e9, rel=1e-9)


@pytest.mark.asyncio
async def test_current_ev_ebitda_override_none_for_p_fcf_metric():
    # Only ev_ebitda gets an EV/EBITDA override; p_fcf must stay None.
    override = await _current_ev_ebitda_override("AAPL", _StubLayer(), "p_fcf")
    assert override is None
