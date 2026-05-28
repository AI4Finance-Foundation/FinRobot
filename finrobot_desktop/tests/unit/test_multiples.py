import pytest
from finrobot.engine.models.financial import CompanyFinancials, PeerComps
from finrobot.engine.compute.multiples import (
    calculate_ebitda_operating,
    calculate_ebitda_reported,
    calculate_ev,
    calculate_multiples,
    calculate_peer_statistics,
)


# External baseline: TSLA TTM Q2'25–Q1'26, raw FMP quarterly statements
# (income statement summed; D&A from the cash-flow statement, which carries the
# 2026-03-31 quarter's 1.59B that the income statement dropped to 0). Net income
# cross-checked against SEC XBRL us-gaap:NetIncomeLoss (3.862B, within 0.4%).
_TSLA_OPERATING_INCOME = 4_897_000_000.0
_TSLA_DA_CASHFLOW = 6_291_000_000.0
_TSLA_NET_INCOME = 3_876_000_000.0
_TSLA_INCOME_TAX = 1_511_000_000.0
_TSLA_INTEREST_EXPENSE = 339_000_000.0


def test_ebitda_operating_is_ebit_plus_da():
    # 4.897B EBIT + 6.291B D&A = 11.188B (Damodaran operating caliber).
    assert (
        calculate_ebitda_operating(_TSLA_OPERATING_INCOME, _TSLA_DA_CASHFLOW)
        == 11_188_000_000.0
    )


def test_ebitda_reported_is_bottom_up_sum():
    # NI 3.876B + tax 1.511B + interest 0.339B + D&A 6.291B = 12.017B (street caliber).
    assert (
        calculate_ebitda_reported(
            _TSLA_NET_INCOME,
            _TSLA_INCOME_TAX,
            _TSLA_INTEREST_EXPENSE,
            _TSLA_DA_CASHFLOW,
        )
        == 12_017_000_000.0
    )


def test_ebitda_reported_exceeds_operating_for_cash_rich_issuer():
    """TSLA's large interest income lands in net income, so the bottom-up
    caliber sits above operating EBITDA — the gap is the non-operating income
    EV/EBITDA should not credit."""
    operating = calculate_ebitda_operating(_TSLA_OPERATING_INCOME, _TSLA_DA_CASHFLOW)
    reported = calculate_ebitda_reported(
        _TSLA_NET_INCOME, _TSLA_INCOME_TAX, _TSLA_INTEREST_EXPENSE, _TSLA_DA_CASHFLOW
    )
    assert operating is not None and reported is not None
    assert reported > operating


@pytest.mark.parametrize(
    "func,args",
    [
        (calculate_ebitda_operating, (None, 6.291e9)),
        (calculate_ebitda_operating, (4.897e9, None)),
        (calculate_ebitda_reported, (None, 1.5e9, 0.3e9, 6.3e9)),
        (calculate_ebitda_reported, (3.8e9, None, 0.3e9, 6.3e9)),
        (calculate_ebitda_reported, (3.8e9, 1.5e9, None, 6.3e9)),
        (calculate_ebitda_reported, (3.8e9, 1.5e9, 0.3e9, None)),
    ],
)
def test_ebitda_returns_none_when_component_missing(func, args):
    """Never fabricate EBITDA from a partial set of components."""
    assert func(*args) is None


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


def test_calculate_multiples_sub_floor_ev_ebitda_marked_not_meaningful():
    """TSM-style yfinance USD/TWD unit mismatch produces EV/EBITDA = 0.158x.
    Pre-fix this would poison the peer median; we now return None so the
    statistic ignores it (validator still fails loudly downstream too).

    Setup: EV=$100B, EBITDA reported as $1T (TWD-into-USD mismatch) →
    ratio 0.1x → below the sanity floor."""
    c = _make_company(
        "TSM", revenue=80e9, ebitda=1000e9, net_income=30e9, market_cap=100e9
    )
    c = calculate_multiples(c)
    assert c.ev_ebitda is None
    # ev_revenue is still meaningful — only ev_ebitda hits the sanity floor.
    assert c.ev_revenue is not None


def test_calculate_multiples_at_floor_boundary_inclusive():
    """The sanity floor is 0.5x (aligned with validate_peer_comps). Guard the
    inclusive boundary so legitimate distressed-quarter prints don't fall off."""
    # EV = 50, EBITDA = 100 → ev_ebitda = 0.5x exactly
    c = _make_company("BOUNDARY", revenue=200, ebitda=100, net_income=10, market_cap=50)
    c = calculate_multiples(c)
    assert c.ev_ebitda == 0.5


def test_calculate_multiples_cyclical_trough_preserved():
    """Real cyclical-trough multiples (shipping/steel/auto sectors at the
    bottom of the cycle) print 0.6-3x. These are economically meaningful
    signals, not unit-mismatch noise — they must NOT be silently dropped.
    Pre-alignment (floor=1.0x) this case was incorrectly swallowed."""
    # EV = 80, EBITDA = 100 → ev_ebitda = 0.8x (genuine cyclical trough)
    c = _make_company("CYCLICAL", revenue=300, ebitda=100, net_income=20, market_cap=80)
    c = calculate_multiples(c)
    assert c.ev_ebitda == 0.8


def test_calculate_multiples_above_ceiling_marked_not_meaningful():
    """EBITDA-collapse cases producing >300x are garbage (post-write-down
    survivors with near-zero EBITDA). Guard the upper bound too."""
    # EV = 1000, EBITDA = 2 → ev_ebitda = 500x
    c = _make_company("COLLAPSE", revenue=100, ebitda=2, net_income=1, market_cap=1000)
    c = calculate_multiples(c)
    assert c.ev_ebitda is None


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


class TestSanityFloorSymmetry:
    """All three multiples have a floor; verify each independently."""

    def test_pe_below_floor_returns_none(self) -> None:
        """PE < 1.0x signals FX/unit mismatch (net_income inflated by wrong currency).

        TSM artifact bug: yfinance mis-tagged financialCurrency=USD, causing net_income
        in TWD (large) vs market_cap in USD, collapsing PE to sub-1x. After FX override
        is applied net_income is correct TWD; this test guards the compute floor.

        Setup: market_cap=50, net_income=100 → raw PE=0.5x (below 1.0 floor).
        """
        c = _make_company("TSM", revenue=100, ebitda=30, net_income=100, market_cap=50)
        c = calculate_multiples(c)
        assert c.pe_ratio is None, f"Expected None for PE=0.5x, got {c.pe_ratio}"

    def test_pe_at_floor_boundary_included(self) -> None:
        """PE=1.0x exactly is the boundary — must be included, not dropped."""
        c = _make_company("X", revenue=100, ebitda=30, net_income=500, market_cap=500)
        c = calculate_multiples(c)
        assert c.pe_ratio == pytest.approx(1.0)

    def test_pe_above_ceiling_returns_none(self) -> None:
        """PE > 300x is garbage (e.g. write-down survivors). Must return None."""
        c = _make_company("X", revenue=100, ebitda=30, net_income=1, market_cap=500)
        c = calculate_multiples(c)
        assert c.pe_ratio is None

    def test_ev_revenue_below_floor_returns_none(self) -> None:
        """EV/Revenue < 0.1x signals FX mismatch. Must return None."""
        # EV = 1 (market_cap=1, debt=0, cash=0), revenue=100 → 0.01x
        c = _make_company("X", revenue=100, ebitda=5, net_income=3, market_cap=1)
        c = calculate_multiples(c)
        assert c.ev_revenue is None

    def test_ev_revenue_normal_range_preserved(self) -> None:
        """EV/Revenue within [0.1x, 100x] must not be dropped."""
        # EV=500, revenue=100 → 5x
        c = _make_company("X", revenue=100, ebitda=30, net_income=10, market_cap=500)
        c = calculate_multiples(c)
        assert c.ev_revenue is not None
        assert c.ev_revenue == pytest.approx(5.0)


class TestPeerStatisticsSampleSizeWarnings:
    """Sample-size warnings are emitted when peers are excluded from statistics."""

    def _comps_with_one_nm_evebitda(self) -> PeerComps:
        peers = [
            calculate_multiples(_make_company("A", 100, 10, 5, 180)),  # EV/EBITDA=18x
            calculate_multiples(_make_company("B", 100, 10, 5, 250)),  # 25x
            calculate_multiples(_make_company("C", 100, 10, 5, 300)),  # 30x
            calculate_multiples(_make_company("TSM", 80e9, 1000e9, 30e9, 100e9)),  # NM
        ]
        target = calculate_multiples(_make_company("T", 100, 10, 5, 200))
        return PeerComps(target=target, peers=peers)

    def test_warning_emitted_when_peer_dropped_from_ev_ebitda(self) -> None:
        """5 peers, 1 NM EV/EBITDA → warning says 'n=3 of 4'."""
        comps = calculate_peer_statistics(self._comps_with_one_nm_evebitda())
        ev_ebitda_warnings = [w for w in comps.warnings if "EV/EBITDA" in w]
        assert ev_ebitda_warnings, f"Expected EV/EBITDA sample-size warning, got: {comps.warnings}"
        assert "n=3 of 4" in ev_ebitda_warnings[0]

    def test_no_warning_when_all_peers_have_valid_ev_ebitda(self) -> None:
        """All peers have valid EV/EBITDA → no sample-size warning."""
        peers = [
            calculate_multiples(_make_company("A", 100, 10, 5, 180)),
            calculate_multiples(_make_company("B", 100, 10, 5, 250)),
            calculate_multiples(_make_company("C", 100, 10, 5, 300)),
        ]
        target = calculate_multiples(_make_company("T", 100, 10, 5, 200))
        comps = PeerComps(target=target, peers=peers)
        result = calculate_peer_statistics(comps)
        ev_ebitda_warnings = [w for w in result.warnings if "EV/EBITDA" in w]
        assert not ev_ebitda_warnings

    def test_warning_five_peers_one_dropped(self) -> None:
        """Explicit 5-peer, 1-drop scenario from the task spec."""
        peers = [
            calculate_multiples(_make_company("A", 100, 10, 5, 180)),
            calculate_multiples(_make_company("B", 100, 10, 5, 250)),
            calculate_multiples(_make_company("C", 100, 10, 5, 300)),
            calculate_multiples(_make_company("D", 100, 10, 5, 220)),
            calculate_multiples(_make_company("BAD", 80e9, 1000e9, 30e9, 100e9)),  # NM
        ]
        target = calculate_multiples(_make_company("T", 100, 10, 5, 200))
        comps = PeerComps(target=target, peers=peers)
        result = calculate_peer_statistics(comps)
        ev_ebitda_warnings = [w for w in result.warnings if "EV/EBITDA" in w]
        assert ev_ebitda_warnings
        assert "n=4 of 5" in ev_ebitda_warnings[0]
