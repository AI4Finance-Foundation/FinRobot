import pytest
from finagent.engine.models.financial import CompanyFinancials, PeerComps
from finagent.engine.compute.multiples import calculate_ev, calculate_multiples, calculate_peer_statistics

def _make_company(ticker, revenue, ebitda, net_income, market_cap,
                  total_debt=0, total_cash=0, gross_margin=0.4, operating_margin=0.2):
    return CompanyFinancials(
        ticker=ticker, revenue=revenue, ebitda=ebitda,
        net_income=net_income, market_cap=market_cap,
        total_debt=total_debt, total_cash=total_cash,
        gross_margin=gross_margin, operating_margin=operating_margin,
    )

def test_calculate_ev():
    assert calculate_ev(100, 30, 10) == 120

def test_calculate_multiples_known_values():
    """market_cap=500, debt=30, cash=10 → EV=520; revenue=100, ebitda=35"""
    c = _make_company("X", revenue=100, ebitda=35, net_income=10,
                      market_cap=500, total_debt=30, total_cash=10)
    calculate_multiples(c)
    assert abs(c.enterprise_value - 520) < 1e-9
    assert abs(c.ev_ebitda - 520/35) < 1e-9
    assert abs(c.ev_revenue - 520/100) < 1e-9

def test_calculate_multiples_negative_earnings():
    c = _make_company("X", revenue=100, ebitda=35, net_income=-5, market_cap=500)
    calculate_multiples(c)
    assert c.pe_ratio is None

def test_calculate_multiples_negative_ebitda():
    c = _make_company("X", revenue=100, ebitda=-5, net_income=10, market_cap=500)
    calculate_multiples(c)
    assert c.ev_ebitda is None

def test_calculate_multiples_zero_debt_cash():
    c = _make_company("X", revenue=100, ebitda=35, net_income=10, market_cap=500)
    calculate_multiples(c)
    assert c.enterprise_value == 500

def test_peer_statistics_exact():
    companies = [
        _make_company("A", 100, 30, 10, 500, 20, 5),
        _make_company("B", 120, 40, 15, 600, 30, 10),
        _make_company("C", 80, 25, 8, 400, 10, 5),
    ]
    for c in companies:
        calculate_multiples(c)
    target = _make_company("T", 100, 35, 12, 550)
    comps = PeerComps(target=target, peers=companies)
    calculate_peer_statistics(comps)
    assert comps.median_ev_ebitda is not None
    assert comps.mean_ev_ebitda is not None
    # verify median is the middle value
    evs = sorted(c.ev_ebitda for c in companies if c.ev_ebitda is not None)
    assert abs(comps.median_ev_ebitda - evs[1]) < 1e-9

def test_peer_statistics_excludes_none_pe():
    companies = [
        _make_company("A", 100, 30, 10, 500),
        _make_company("B", 100, 30, -5, 500),  # negative earnings → pe=None
        _make_company("C", 100, 30, 8, 400),
    ]
    for c in companies:
        calculate_multiples(c)
    target = _make_company("T", 100, 35, 12, 550)
    comps = PeerComps(target=target, peers=companies)
    calculate_peer_statistics(comps)
    # median P/E computed from only A and C (B excluded)
    assert abs(comps.median_pe - 50.0) < 1e-9

def test_peer_statistics_all_none_pe():
    companies = [
        _make_company("A", 100, 30, -1, 500),
        _make_company("B", 100, 30, -2, 500),
        _make_company("C", 100, 30, -3, 400),
    ]
    for c in companies:
        calculate_multiples(c)
    target = _make_company("T", 100, 35, 12, 550)
    comps = PeerComps(target=target, peers=companies)
    calculate_peer_statistics(comps)
    assert comps.median_pe is None

def test_single_peer_median_equals_mean():
    c = _make_company("A", 100, 30, 10, 500)
    calculate_multiples(c)
    target = _make_company("T", 100, 35, 12, 550)
    comps = PeerComps(target=target, peers=[c])
    calculate_peer_statistics(comps)
    assert comps.median_ev_ebitda == comps.mean_ev_ebitda
