import pytest
from finrobot.engine.models.financial import CompanyFinancials, PeerComps
from finrobot.engine.compute.multiples import (
    calculate_core_pe,
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
    assert calculate_ebitda_operating(_TSLA_OPERATING_INCOME, _TSLA_DA_CASHFLOW) == 11_188_000_000.0


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
    c = _make_company("TSM", revenue=80e9, ebitda=1000e9, net_income=30e9, market_cap=100e9)
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
        calculate_multiples(
            _make_company("A", revenue=100, ebitda=10, net_income=5, market_cap=180)
        ),  # 18x
        calculate_multiples(
            _make_company("B", revenue=100, ebitda=10, net_income=5, market_cap=250)
        ),  # 25x
        calculate_multiples(
            _make_company("C", revenue=100, ebitda=10, net_income=5, market_cap=300)
        ),  # 30x
        calculate_multiples(
            _make_company("TSM", revenue=80e9, ebitda=1000e9, net_income=30e9, market_cap=100e9)
        ),  # NM
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


# ── NOPAT core P/E (calculate_core_pe) ──────────────────────────────────────────
#
# External baseline: NVDA TTM ending 2026-04-26 and its semiconductor peer set,
# live from the FMP provider through extract_company_financials (verified
# 2026-06-01). The defect this fixes: NVDA's as-reported TTM net income $159.6B
# carries ~$27B of non-operating income (mostly a Q1 investment gain), so
# as-reported comps_pe = peer_median_pe 51.83x × trailing EPS $6.59 = $341.58 —
# built on contaminated, cross-sectionally inconsistent earnings. The NOPAT
# caliber strips it: comps_pe = median_core_pe 48.975x × core EPS $5.6452 = $276.47.


def _co_tax(ticker, revenue, op_income, net_income, market_cap, tax):
    """Peer row carrying operating margin (EBIT/revenue) and tax for NOPAT."""
    return calculate_multiples(
        CompanyFinancials(
            ticker=ticker,
            revenue=revenue,
            ebitda=op_income,  # EV/EBITDA not under test here
            net_income=net_income,
            market_cap=market_cap,
            total_debt=0,
            total_cash=0,
            gross_margin=0.5,
            operating_margin=op_income / revenue,
            income_tax_expense=tax,
        )
    )


def _nvda_peer_comps() -> PeerComps:
    # (ticker, revenue, operating_income, net_income, market_cap, income_tax)
    nvda = _co_tax("NVDA", 253_491e6, 162_285e6, 159_613e6, 5_114_021.94e6, 29_830e6)
    peers = [
        _co_tax("AMD", 37_454e6, 4_364e6, 5_009e6, 841_552.66e6, 12e6),  # own tax 0.2% → fallback
        _co_tax("INTC", 53_763e6, -5_079e6, -3_174e6, 576_381.68e6, 1_565e6),  # loss → core None
        _co_tax("TXN", 18_438e6, 6_507e6, 5_367e6, 278_197.22824e6, 781e6),
        _co_tax("QCOM", 44_487e6, 11_355e6, 9_923e6, 264_575.08e6, 1_779e6),
        _co_tax("AVGO", 68_282e6, 27_905e6, 24_972e6, 2_115_308.5159e6, 462e6),  # 1.8% → fallback
        _co_tax("MU", 58_119e6, 28_202e6, 24_115e6, 1_095_025.83e6, 3_864e6),
    ]
    return PeerComps(target=nvda, peers=peers)


def test_core_pe_median_matches_live_baseline():
    comps = calculate_core_pe(_nvda_peer_comps())
    # peer median of core P/E (INTC excluded — negative NOPAT)
    assert comps.median_core_pe == pytest.approx(48.975, rel=1e-3)


def test_core_pe_strips_non_operating_income_from_target():
    """NVDA core net income (NOPAT) sits well below as-reported net income — the
    ~$27B of TTM non-operating gains are removed."""
    comps = calculate_core_pe(_nvda_peer_comps())
    t = comps.target
    assert t.effective_tax_rate == pytest.approx(0.1575, rel=1e-3)
    assert t.core_net_income == pytest.approx(136_731e6, rel=1e-3)
    assert t.core_net_income < t.net_income  # non-operating income stripped


def test_core_pe_degenerate_tax_falls_back_to_peer_median():
    """AMD (own effective tax 0.2%) and AVGO (1.8%) are below the in-band floor,
    so both adopt the peer-set median rate instead of their tax-holiday rate."""
    comps = calculate_core_pe(_nvda_peer_comps())
    by = {p.ticker: p for p in comps.peers}
    fallback = by["TXN"].effective_tax_rate  # an in-band own rate contributes to the median
    assert by["AMD"].effective_tax_rate == pytest.approx(0.1381, rel=1e-3)
    assert by["AVGO"].effective_tax_rate == pytest.approx(0.1381, rel=1e-3)
    # in-band peers keep their own rate
    assert by["QCOM"].effective_tax_rate == pytest.approx(0.1520, rel=1e-3)
    assert fallback == pytest.approx(0.1270, rel=1e-3)


def test_core_pe_excludes_negative_nopat_peer():
    comps = calculate_core_pe(_nvda_peer_comps())
    intc = next(p for p in comps.peers if p.ticker == "INTC")
    assert intc.core_net_income < 0
    assert intc.core_pe_ratio is None


def test_core_pe_all_degenerate_uses_statutory_fallback():
    """When no peer yields an in-band rate, the statutory 21% is the last resort."""
    peers = [
        _co_tax("A", 100, 20, 19, 500, 0.5),  # 0.5/19.5 ≈ 2.6% → below floor
        _co_tax("B", 100, 25, 24, 600, 0.5),  # 0.5/24.5 ≈ 2.0% → below floor
    ]
    target = _co_tax("T", 100, 30, 29, 550, 0.5)  # 0.5/29.5 ≈ 1.7% → below floor
    comps = calculate_core_pe(PeerComps(target=target, peers=peers))
    assert comps.target.effective_tax_rate == pytest.approx(0.21)


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
