import pytest
from datetime import datetime, timezone
from finagent.engine.data.interface import DataResult
from finagent.engine.compute.extractor import (
    extract_financial_data, extract_company_financials, extract_price_history,
)

def _make_financials_result(**overrides):
    data = dict(
        revenue=100e9, ebitda=35e9, net_income=20e9,
        gross_margin=0.47, operating_margin=0.28,
        pe_ratio=28.5, market_cap=3e12,
        shares_outstanding=15e9, current_price=200.0,
        total_debt=50e9, total_cash=20e9,
    )
    data.update(overrides)
    return DataResult(
        data=data, provider="yfinance", ticker="AAPL",
        data_type="financials", timestamp=datetime.now(tz=timezone.utc),
    )

def _make_price_result():
    prices = [{"date": "2024-01-01", "close": 180.0},
              {"date": "2024-06-01", "close": 220.0},
              {"date": "2024-12-01", "close": 200.0}]
    return DataResult(
        data={"current_price": 200.0, "price_history": prices},
        provider="yfinance", ticker="AAPL",
        data_type="price", timestamp=datetime.now(tz=timezone.utc),
    )

def test_extract_financial_data_valid():
    fd = extract_financial_data(_make_financials_result(), _make_price_result())
    assert fd.ticker == "AAPL"
    assert fd.income.revenue == 100e9
    assert fd.income.ebitda == 35e9
    assert fd.income.gross_margin == 0.47

def test_extract_financial_data_missing_revenue_raises():
    with pytest.raises(ValueError, match="revenue"):
        extract_financial_data(_make_financials_result(revenue=None), _make_price_result())

def test_extract_financial_data_computes_ev():
    fd = extract_financial_data(_make_financials_result(), _make_price_result())
    # EV = 3e12 + 50e9 - 20e9 = 3.03e12
    assert abs(fd.valuation.enterprise_value - 3.03e12) < 1e6

def test_extract_financial_data_ev_ebitda():
    fd = extract_financial_data(_make_financials_result(), _make_price_result())
    assert fd.valuation.ev_ebitda is not None
    assert abs(fd.valuation.ev_ebitda - fd.valuation.enterprise_value / fd.income.ebitda) < 1e-6

def test_extract_financial_data_ev_ebitda_none_when_negative_ebitda():
    fd = extract_financial_data(_make_financials_result(ebitda=-1e9), _make_price_result())
    assert fd.valuation.ev_ebitda is None

def test_extract_financial_data_zero_debt_cash():
    fd = extract_financial_data(
        _make_financials_result(total_debt=0, total_cash=0), _make_price_result()
    )
    assert abs(fd.valuation.enterprise_value - fd.market.market_cap) < 1

def test_extract_company_financials_has_debt_cash():
    cf = extract_company_financials(_make_financials_result())
    assert cf.total_debt == 50e9
    assert cf.total_cash == 20e9

def test_extract_financial_data_missing_shares_outstanding_warns():
    """When shares_outstanding is missing, derive from market_cap/price and warn."""
    fr = _make_financials_result()
    del fr.data["shares_outstanding"]
    fd = extract_financial_data(fr, _make_price_result())
    # Derived: market_cap / current_price = 3e12 / 200 = 15e9
    assert fd.market.shares_outstanding == pytest.approx(15e9, rel=1e-6)
    assert any("shares_outstanding" in w for w in fd.warnings)


def test_extract_financial_data_zero_shares_outstanding_warns():
    """When shares_outstanding is 0, derive from market_cap/price and warn."""
    fd = extract_financial_data(
        _make_financials_result(shares_outstanding=0), _make_price_result()
    )
    assert fd.market.shares_outstanding == pytest.approx(15e9, rel=1e-6)
    assert any("shares_outstanding" in w for w in fd.warnings)


def test_extract_price_history_valid():
    ph = extract_price_history(_make_price_result())
    assert ph.ticker == "AAPL"
    assert ph.high_52w == 220.0
    assert ph.low_52w == 180.0
    assert abs(ph.avg_price - (180.0 + 220.0 + 200.0) / 3) < 1e-6
