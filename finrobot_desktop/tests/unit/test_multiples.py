from finrobot.engine.models.financial import CompanyFinancials, PeerComps
from finrobot.engine.compute.multiples import (
    calculate_ev,
    calculate_multiples,
    calculate_peer_statistics,
)


def _make_company(
    ticker,
    revenue,
    ebitda,
    net_income,
    market_cap,
    total_debt=0,
    total_cash=0,
    gross_margin=0.4,
    operating_margin=0.2,
):
    return CompanyFinancials(
        ticker=ticker,
        revenue=revenue,
        ebitda=ebitda,
        net_income=net_income,
        market_cap=market_cap,
        total_debt=total_debt,
        total_cash=total_cash,
        gross_margin=gross_margin,
        operating_margin=operating_margin,
    )


def test_calculate_ev():
    assert calculate_ev(100, 30, 10) == 120


def test_calculate_multiples_known_values():
    """market_cap=500, debt=30, cash=10 → EV=520; revenue=100, ebitda=35"""
    c = _make_company(
        "X", revenue=100, ebitda=35, net_income=10, market_cap=500, total_debt=30, total_cash=10
    )
    c = calculate_multiples(c)
    assert abs(c.enterprise_value - 520) < 1e-9
    assert abs(c.ev_ebitda - 520 / 35) < 1e-9
    assert abs(c.ev_revenue - 520 / 100) < 1e-9


def test_calculate_multiples_negative_earnings():
    c = _make_company("X", revenue=100, ebitda=35, net_income=-5, market_cap=500)
    c = calculate_multiples(c)
    assert c.pe_ratio is None


def test_calculate_multiples_negative_ebitda():
    c = _make_company("X", revenue=100, ebitda=-5, net_income=10, market_cap=500)
    c = calculate_multiples(c)
    assert c.ev_ebitda is None


def test_calculate_multiples_sub_unit_ev_ebitda_marked_not_meaningful():
    """TSM-style yfinance USD/TWD unit mismatch produces EV/EBITDA = 0.158x.
    Pre-fix this would poison the peer median; we now return None so the
    statistic ignores it (validator still fails loudly downstream too).

    Setup: EV=$100B, EBITDA reported as $1T (TWD-into-USD mismatch) →
    ratio 0.1x → below the meaningful floor."""
    c = _make_company(
        "TSM", revenue=80e9, ebitda=1000e9, net_income=30e9, market_cap=100e9
    )
    c = calculate_multiples(c)
    assert c.ev_ebitda is None
    # ev_revenue is still meaningful — only ev_ebitda hits the sanity floor.
    assert c.ev_revenue is not None


def test_calculate_multiples_just_above_floor_still_meaningful():
    """Anything ≥ 1.0x is treated as a real cyclical / distressed signal,
    not garbage. Guard the inclusive boundary."""
    # EV = 100, EBITDA = 100 → ev_ebitda = 1.0x exactly
    c = _make_company("BOUNDARY", revenue=200, ebitda=100, net_income=10, market_cap=100)
    c = calculate_multiples(c)
    assert c.ev_ebitda == 1.0


def test_calculate_peer_statistics_excludes_not_meaningful_ev_ebitda():
    """End-to-end: a foreign-ADR with NM ev_ebitda must not skew the median.
    Without the sanity floor, TSM at 0.158x would drag median(18, 25, 30, 0.158)
    down by ~10x. With the floor, TSM's ev_ebitda is None and the median
    is computed over the three valid peers."""
    peers = [
        calculate_multiples(_make_company("A", revenue=100, ebitda=10, net_income=5, market_cap=180)),  # 18x
        calculate_multiples(_make_company("B", revenue=100, ebitda=10, net_income=5, market_cap=250)),  # 25x
        calculate_multiples(_make_company("C", revenue=100, ebitda=10, net_income=5, market_cap=300)),  # 30x
        calculate_multiples(_make_company("TSM", revenue=80e9, ebitda=1000e9, net_income=30e9, market_cap=100e9)),  # NM
    ]
    target = calculate_multiples(_make_company("T", 100, 10, 5, 200))
    comps = PeerComps(target=target, peers=peers)
    result = calculate_peer_statistics(comps)
    # Median of the three meaningful peers (18, 25, 30) = 25, not contaminated by TSM
    assert result.median_ev_ebitda == 25.0


def test_calculate_multiples_zero_debt_cash():
    c = _make_company("X", revenue=100, ebitda=35, net_income=10, market_cap=500)
    c = calculate_multiples(c)
    assert c.enterprise_value == 500


def test_peer_statistics_exact():
    companies = [
        calculate_multiples(_make_company("A", 100, 30, 10, 500, 20, 5)),
        calculate_multiples(_make_company("B", 120, 40, 15, 600, 30, 10)),
        calculate_multiples(_make_company("C", 80, 25, 8, 400, 10, 5)),
    ]
    target = _make_company("T", 100, 35, 12, 550)
    comps = PeerComps(target=target, peers=companies)
    comps = calculate_peer_statistics(comps)
    assert comps.median_ev_ebitda is not None
    assert comps.mean_ev_ebitda is not None
    # verify median is the middle value
    evs = sorted(c.ev_ebitda for c in companies if c.ev_ebitda is not None)
    assert abs(comps.median_ev_ebitda - evs[1]) < 1e-9


def test_peer_statistics_excludes_none_pe():
    companies = [
        calculate_multiples(_make_company("A", 100, 30, 10, 500)),
        calculate_multiples(_make_company("B", 100, 30, -5, 500)),  # negative earnings → pe=None
        calculate_multiples(_make_company("C", 100, 30, 8, 400)),
    ]
    target = _make_company("T", 100, 35, 12, 550)
    comps = PeerComps(target=target, peers=companies)
    comps = calculate_peer_statistics(comps)
    # median P/E computed from only A and C (B excluded)
    assert abs(comps.median_pe - 50.0) < 1e-9


def test_peer_statistics_all_none_pe():
    companies = [
        calculate_multiples(_make_company("A", 100, 30, -1, 500)),
        calculate_multiples(_make_company("B", 100, 30, -2, 500)),
        calculate_multiples(_make_company("C", 100, 30, -3, 400)),
    ]
    target = _make_company("T", 100, 35, 12, 550)
    comps = PeerComps(target=target, peers=companies)
    comps = calculate_peer_statistics(comps)
    assert comps.median_pe is None


def test_single_peer_median_equals_mean():
    c = _make_company("A", 100, 30, 10, 500)
    c = calculate_multiples(c)
    target = _make_company("T", 100, 35, 12, 550)
    comps = PeerComps(target=target, peers=[c])
    comps = calculate_peer_statistics(comps)
    assert comps.median_ev_ebitda == comps.mean_ev_ebitda
