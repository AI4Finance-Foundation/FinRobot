"""Cyclical comps (改动点 4): P/B primary multiple + curated peer-pool injection.

Why these exist: the provider industry tags put a memory/storage cyclical (MU) in
a logic-semis bucket whose growth-stock forward P/E × MU's cycle-peak EPS prints a
$2199 fair value (scripts/_cyclical_probe_peers.py). The fix injects the real
storage cohort (WDC/STX/SNDK) into the screen and prices the target off a CYCLE-
STABLE P/B median instead of cycle-distorted EPS. These pin:
  - the curated peer map + Tier-1 injection (deterministic, no LLM / no volatility)
  - P/B computed single-currency only (ADR → None, the forward_pe gate)
  - median_pb + pb_sample_n with the same n<3 / mismatch refusal as P/E
  - the aggregator adds comps_pb for a cyclical, NEVER for a non-cyclical
"""

from __future__ import annotations

import pytest

from finrobot.engine.compute.operators.cyclical_peers import (
    cyclical_peer_group,
    inject_cyclical_peers,
)
from finrobot.engine.compute.operators.multiples import (
    PEER_PB_SANITY_MAX,
    calculate_multiples,
    calculate_peer_statistics,
)
from finrobot.engine.compute.operators.valuation_aggregator import (
    _comps_pb_method,
    _comps_pe_method,
    aggregate_valuation,
    through_cycle_roe,
)
from finrobot.engine.models.financial import CompanyFinancials, PeerComps


def _peer(
    ticker: str,
    *,
    market_cap: float,
    bvps: float | None,
    pb: float | None = None,
    shares: float = 1.0,
    reporting: str = "USD",
    quote: str = "USD",
    net_income: float | None = 1e9,
) -> CompanyFinancials:
    """A peer row carrying book value per share. When pb is None it is computed
    here the way extract_company_financials does (single-currency, book>0)."""
    if pb is None and reporting == quote and bvps is not None and bvps > 0:
        pb = market_cap / (bvps * shares)
    return CompanyFinancials(
        ticker=ticker,
        revenue=10e9,
        net_income=net_income,
        market_cap=market_cap,
        book_value_per_share=bvps,
        pb_ratio=pb,
        reporting_currency=reporting,
        quote_currency=quote,
    )


class TestCyclicalPeerGroup:
    def test_memory_ticker_returns_cohort_excluding_self(self):
        assert set(cyclical_peer_group("MU")) == {"WDC", "STX", "SNDK"}
        assert "MU" not in cyclical_peer_group("MU")

    def test_storage_ticker_returns_cohort_excluding_self(self):
        assert set(cyclical_peer_group("WDC")) == {"MU", "STX", "SNDK"}

    def test_non_cyclical_returns_empty(self):
        assert cyclical_peer_group("AAPL") == ()
        assert cyclical_peer_group("NVDA") == ()

    def test_normalizes_case_and_whitespace(self):
        assert set(cyclical_peer_group(" mu ")) == {"WDC", "STX", "SNDK"}


class TestInjectCyclicalPeers:
    def test_injects_cohort_into_industry_screen_tier1(self):
        payload = {"industry_screen": ["NVDA", "AMD", "AVGO"], "stock_peers": ["LRCX"]}
        out = inject_cyclical_peers(payload, "MU")
        # storage cohort is prepended (high-affinity Tier 1) ahead of the logic semis
        assert out["industry_screen"][:3] == ["WDC", "STX", "SNDK"]
        assert "NVDA" in out["industry_screen"]
        # other tiers untouched
        assert out["stock_peers"] == ["LRCX"]

    def test_does_not_mutate_cached_payload(self):
        payload = {"industry_screen": ["NVDA"]}
        inject_cyclical_peers(payload, "MU")
        # original dict is never mutated (cache safety)
        assert payload["industry_screen"] == ["NVDA"]

    def test_dedups_when_cohort_member_already_present(self):
        payload = {"industry_screen": ["WDC", "NVDA"]}
        out = inject_cyclical_peers(payload, "MU")
        assert out["industry_screen"].count("WDC") == 1

    def test_non_cyclical_returns_payload_unchanged(self):
        payload = {"industry_screen": ["MSFT", "GOOGL"]}
        out = inject_cyclical_peers(payload, "AAPL")
        assert out is payload


class TestPbInMultiples:
    def test_pb_passes_sanity_gate(self):
        # P/B 2.0x (mid-band) survives.
        c = _peer("MU", market_cap=200e9, bvps=50.0, shares=2e9)  # 200e9/(50*2e9)=2.0
        out = calculate_multiples(c)
        assert out.pb_ratio == pytest.approx(2.0)

    def test_pb_out_of_band_nulled_and_recorded(self):
        # P/B above the sanity max is excluded and recorded in sanity_drops.
        c = _peer("X", market_cap=200e9, bvps=1.0, shares=1.0, pb=PEER_PB_SANITY_MAX + 10)
        out = calculate_multiples(c)
        assert out.pb_ratio is None
        assert any("P/B" in d for d in out.sanity_drops)

    def test_pb_none_propagates(self):
        c = _peer("X", market_cap=200e9, bvps=None)
        out = calculate_multiples(c)
        assert out.pb_ratio is None


class TestMedianPb:
    def test_median_and_sample_count(self):
        import statistics

        target = _peer("MU", market_cap=1000e9, bvps=40.0, shares=1.13e9)
        # P/B = market_cap / (bvps × shares): 2.0x, 4.0x, 6.0x respectively.
        peers = [
            _peer("WDC", market_cap=100e9, bvps=50.0, shares=1e9),  # 2.0x
            _peer("STX", market_cap=200e9, bvps=50.0, shares=1e9),  # 4.0x
            _peer("SNDK", market_cap=300e9, bvps=50.0, shares=1e9),  # 6.0x
        ]
        comps = calculate_peer_statistics(PeerComps(target=target, peers=peers))
        pbs = [p.pb_ratio for p in peers if p.pb_ratio is not None]
        assert comps.pb_sample_n == 3
        assert comps.median_pb == pytest.approx(statistics.median(pbs))  # 4.0x

    def test_sndk_1y_history_still_contributes_pb(self):
        """P/B is a CURRENT balance-sheet multiple, so SNDK (1y history) contributes
        — the through-cycle-history exclusion does NOT apply to P/B."""
        target = _peer("MU", market_cap=1000e9, bvps=40.0, shares=1.13e9)
        peers = [_peer("SNDK", market_cap=370e9, bvps=60.0, shares=0.30e9)]
        comps = calculate_peer_statistics(PeerComps(target=target, peers=peers))
        assert comps.pb_sample_n == 1
        assert comps.median_pb is not None


class TestMedianEvEbitdaNmCap:
    """The trailing EV/EBITDA median applies the same NM cap the P/E median does: a
    hyper-growth / sliver-EBITDA peer above the cap is a real, computable multiple that
    stays IN the peer set for the competitive landscape, but is excluded from the median
    so it cannot inflate the number the comp display and the thesis prompt consume."""

    @staticmethod
    def _row(ticker: str, ev_ebitda: float | None) -> CompanyFinancials:
        # Independent fixture: ev_ebitda is set directly to a chosen multiple (the field
        # calculate_peer_statistics actually reads), NOT derived from the implementation's
        # gating — so the test can't go green-and-wrong from same-source contamination.
        return CompanyFinancials(
            ticker=ticker, revenue=100.0, market_cap=500.0, ev_ebitda=ev_ebitda
        )

    def test_nm_high_member_excluded_from_median_but_kept_in_set(self):
        from finrobot.engine.compute.operators.multiples import PEER_EV_EBITDA_NM_CAP

        assert PEER_EV_EBITDA_NM_CAP == 50.0
        # In-band {20, 30} → median 25; the 60x member is NM (> 50) and must drop out.
        peers = [self._row("A", 20.0), self._row("B", 30.0), self._row("NMHI", 60.0)]
        comps = calculate_peer_statistics(PeerComps(target=self._row("T", 28.0), peers=peers))
        assert comps.median_ev_ebitda == pytest.approx(25.0)
        assert comps.mean_ev_ebitda == pytest.approx(25.0)  # mean of {20, 30}, NM excluded
        # The NM peer is STILL in the set, on its row — only its median vote is dropped.
        kept = {p.ticker for p in comps.peers}
        assert "NMHI" in kept
        nm_row = next(p for p in comps.peers if p.ticker == "NMHI")
        assert nm_row.ev_ebitda == pytest.approx(60.0)
        # A thinned EV/EBITDA median is disclosed, never silent.
        assert any("NM EV/EBITDA" in w and "2 of 3" in w for w in comps.warnings)

    def test_all_in_band_set_unchanged(self):
        # Every peer ≤ cap → all three contribute, median is the middle value (30), and
        # no EV/EBITDA NM/sample-size warning is emitted.
        peers = [self._row("A", 20.0), self._row("B", 30.0), self._row("C", 40.0)]
        comps = calculate_peer_statistics(PeerComps(target=self._row("T", 28.0), peers=peers))
        assert comps.median_ev_ebitda == pytest.approx(30.0)
        assert {p.ticker for p in comps.peers} == {"A", "B", "C"}
        assert not any("EV/EBITDA based on" in w for w in comps.warnings)


class TestCompsPbMethod:
    def _comps_with_median(
        self,
        median_pb: float,
        sample_n: int,
        target_bvps: float | None,
        target_pb: float | None = None,
    ) -> PeerComps:
        target = CompanyFinancials(
            ticker="MU",
            revenue=58e9,
            net_income=8e9,
            market_cap=1000e9,
            book_value_per_share=target_bvps,
            pb_ratio=target_pb,
        )
        peers = [_peer(f"P{i}", market_cap=100e9, bvps=25.0, shares=1e9) for i in range(sample_n)]
        comps = PeerComps(target=target, peers=peers)
        comps.median_pb = median_pb
        comps.pb_sample_n = sample_n
        return comps

    def test_prices_target_at_peer_median_pb_times_bvps(self):
        # median P/B 2.0x × target bvps $40 = $80.
        comps = self._comps_with_median(2.0, 4, target_bvps=40.0, target_pb=2.5)
        m = _comps_pb_method(comps)
        assert m is not None
        assert m.method == "comps_pb"
        assert m.mid == pytest.approx(80.0)

    def test_refuses_when_sample_below_three(self):
        warnings: list[str] = []
        comps = self._comps_with_median(2.0, 2, target_bvps=40.0, target_pb=2.5)
        m = _comps_pb_method(comps, warnings)
        assert m is None
        # refusal is tagged comps_pb (not comps_pe) so the analyst sees which multiple退出
        assert any("comps_pb" in w and "sample is only 2" in w for w in warnings)

    def test_refuses_on_premise_mismatch_over_10x(self):
        warnings: list[str] = []
        # target P/B 50x vs peer median 2x = 25x mismatch → premise rejected.
        comps = self._comps_with_median(2.0, 4, target_bvps=40.0, target_pb=50.0)
        m = _comps_pb_method(comps, warnings)
        assert m is None
        assert any("comps_pb" in w and "away from" in w for w in warnings)

    def test_falls_back_when_target_bvps_unavailable(self):
        warnings: list[str] = []
        comps = self._comps_with_median(2.0, 4, target_bvps=None)
        m = _comps_pb_method(comps, warnings)
        assert m is None
        assert any("book value per share unavailable" in w for w in warnings)


class TestAggregatorCyclicalWiring:
    def _peer_comps(self) -> PeerComps:
        target = CompanyFinancials(
            ticker="MU",
            revenue=58e9,
            net_income=8e9,
            market_cap=1000e9,
            book_value_per_share=40.0,
            pb_ratio=2.5,
        )
        peers = [_peer(f"P{i}", market_cap=100e9, bvps=25.0, shares=1e9) for i in range(4)]
        comps = PeerComps(target=target, peers=peers)
        comps.median_pb = 2.0
        comps.pb_sample_n = 4
        return comps

    def test_cyclical_adds_comps_pb_row(self):
        agg = aggregate_valuation(
            ticker="MU",
            current_price=949.88,
            peer_comps=self._peer_comps(),
            shares_outstanding=1.13e9,
            cyclical=True,
        )
        assert any(m.method == "comps_pb" for m in agg.methods)

    def test_non_cyclical_never_adds_comps_pb_row(self):
        agg = aggregate_valuation(
            ticker="MU",
            current_price=949.88,
            peer_comps=self._peer_comps(),
            shares_outstanding=1.13e9,
            cyclical=False,
        )
        assert not any(m.method == "comps_pb" for m in agg.methods)


class TestCyclicalCompsPeSuppression:
    """Issue B: a commodity-cyclical must NOT price comps_pe off forward (cycle-PEAK)
    EPS × growth-stock forward P/E — that口径 prints MU at $2974. Per design §5.2 the
    fallback (b) is to suppress the forward comps_pe row for cyclicals and let
    comps_pb (cycle-stable book value) + the through-cycle P/E (DCF anchor) carry the
    relative-multiple slot. Non-cyclical comps_pe is untouched (forward path bit-exact).
    """

    def _comps_with_forward_pe(self) -> PeerComps:
        # Mirrors the MU artifact shape: logic-semi peer forward median P/E 36.9x,
        # target carries a forward P/E so the refusal guard has a real multiple.
        target = CompanyFinancials(
            ticker="MU",
            revenue=58e9,
            net_income=8e9,
            market_cap=1000e9,
            forward_pe=15.7,
            book_value_per_share=40.0,
            pb_ratio=2.5,
        )
        peers = [_peer(f"P{i}", market_cap=100e9, bvps=25.0, shares=1e9) for i in range(4)]
        comps = PeerComps(target=target, peers=peers)
        comps.median_forward_pe = 36.9
        comps.forward_pe_sample_n = 4
        comps.median_pb = 2.0
        comps.pb_sample_n = 4
        return comps

    def test_cyclical_suppresses_forward_comps_pe(self):
        # Forward EPS present (cycle-peak $58.9) — the pre-fix path would print
        # 36.9x × 58.9 ≈ $2174. Cyclical suppresses it: method returns None.
        warnings: list[str] = []
        comps = self._comps_with_forward_pe()
        m = _comps_pe_method(comps, 58.9, 1.13e9, warnings, cyclical=True)
        assert m is None
        # the suppression is口径-explicit and tagged comps_pe
        assert any("comps_pe" in w and "cyclical" in w and "suppressing" in w for w in warnings)

    def test_cyclical_suppression_reason_has_no_dollar_example_or_foreign_ticker(self):
        """The comps_pe suppression reason surfaces verbatim into price_target_basis
        prose. A hardcoded ticker-specific dollar example ("MU $2974") was wrong twice:
        (a) on the withheld path the narrative scrubber washes the naked $-amount to a
        "[target withheld]" marker (the MU/RIVN basis read "= MU [target withheld]
        spurious value"); (b) the MU figure contaminated every OTHER cyclical's report
        (RIVN cited MU's number). The rationale must stay qualitative — no "$", no
        foreign ticker baked in. The dev-context figures live in code comments instead.
        """
        warnings: list[str] = []
        _comps_pe_method(self._comps_with_forward_pe(), 58.9, 1.13e9, warnings, cyclical=True)
        reason = next(w for w in warnings if "comps_pe" in w and "suppressing" in w)
        assert "$" not in reason, f"naked $-amount surfaces into prose + gets washed: {reason}"
        assert "MU" not in reason, f"hardcoded MU example contaminates other cyclicals: {reason}"

    def test_non_cyclical_forward_comps_pe_unchanged(self):
        # Same inputs, cyclical=False → forward path runs exactly as before:
        # median_forward_pe (36.9x) × forward EPS (58.9) = $2173.41, bit-exact.
        warnings: list[str] = []
        comps = self._comps_with_forward_pe()
        m = _comps_pe_method(comps, 58.9, 1.13e9, warnings, cyclical=False)
        assert m is not None
        assert m.method == "comps_pe"
        assert m.mid == pytest.approx(36.9 * 58.9)
        # default cyclical kwarg also leaves the non-cyclical path untouched
        m_default = _comps_pe_method(self._comps_with_forward_pe(), 58.9, 1.13e9, [])
        assert m_default is not None
        assert m_default.mid == pytest.approx(36.9 * 58.9)

    def test_aggregator_cyclical_has_pb_not_pe(self):
        agg = aggregate_valuation(
            ticker="MU",
            current_price=891.0,
            peer_comps=self._comps_with_forward_pe(),
            shares_outstanding=1.13e9,
            forward_eps=58.9,
            cyclical=True,
        )
        assert any(m.method == "comps_pb" for m in agg.methods)
        assert not any(m.method == "comps_pe" for m in agg.methods)
        # the misleading data-quality diagnostics ("net income ≤ 0" etc.) must NOT
        # fire — the row was declined on口径, not on data
        assert not any("net income ≤ 0" in w for w in agg.warnings)
        assert any("cyclical" in w and "suppressing" in w for w in agg.warnings)

    def test_aggregator_non_cyclical_keeps_pe_row(self):
        agg = aggregate_valuation(
            ticker="MU",
            current_price=891.0,
            peer_comps=self._comps_with_forward_pe(),
            shares_outstanding=1.13e9,
            forward_eps=58.9,
            cyclical=False,
        )
        pe_rows = [m for m in agg.methods if m.method == "comps_pe"]
        assert len(pe_rows) == 1
        assert pe_rows[0].mid == pytest.approx(36.9 * 58.9)


class TestThroughCycleRoe:
    """Through-cycle ROE = mean(net_income / shareholders_equity) — normalizes an
    insurer's underwriting-cycle ROE swing for the comps_pb quality adjustment."""

    def test_mean_of_annual_roe(self):
        # ROE each year = 10/100 … 20/100 → mean 0.13.
        r = through_cycle_roe([10.0, 12.0, 8.0, 15.0, 20.0], [100.0] * 5)
        assert r == pytest.approx(0.13)

    def test_loss_years_kept(self):
        # A negative-ROE year is a real part of the cycle, not dropped.
        r = through_cycle_roe([-5.0, 10.0, 10.0, 10.0, 10.0], [100.0] * 5)
        assert r == pytest.approx((-0.05 + 0.10 * 4) / 5)

    def test_non_positive_equity_year_skipped(self):
        # Only a non-positive-equity year (undefined ratio) is skipped; here that drops
        # the sample below min_years → None (can't trust a sub-cycle window).
        assert (
            through_cycle_roe([10.0, 12.0, 8.0, 15.0, 20.0, 9.0], [100, 0, -50, 100, 100, 100])
            is None
        )

    def test_min_years_guard(self):
        # 4 valid years < default 5 → None (window doesn't span a cycle).
        assert through_cycle_roe([10.0, 12.0, 8.0, 15.0], [100.0] * 4) is None

    def test_none_and_short_lists(self):
        assert through_cycle_roe([], []) is None
        assert through_cycle_roe([None, None], [None, None]) is None


class TestCompsPbRoeAdjustment:
    """comps_pb scales the flat peer-median P/B by target/peer through-cycle ROE for the
    insurer cohort (fields set), and is byte-identical (flat) when they are absent."""

    def _pc(self, *, tgt_roe, peer_roe, median_pb=2.0, bvps=50.0, tgt_pb=3.0):
        target = _peer("T", market_cap=1e9, bvps=bvps, pb=tgt_pb)
        pc = PeerComps(target=target, peers=[_peer("P", market_cap=1e9, bvps=bvps, pb=median_pb)])
        pc.median_pb = median_pb
        pc.pb_sample_n = 5  # ≥3 so _comps_median_refusal doesn't fire
        pc.target_through_cycle_roe = tgt_roe
        pc.peer_median_through_cycle_roe = peer_roe
        return pc

    def test_no_roe_fields_is_flat(self):
        # Banks / non-financials never set the fields → flat median (byte-identical).
        m = _comps_pb_method(self._pc(tgt_roe=None, peer_roe=None))
        assert m is not None and m.mid == pytest.approx(2.0 * 50.0)  # 100

    def test_high_roe_target_scaled_up(self):
        # PGR-shape: target 24% vs peer 12% → ×2.0 → $100 flat becomes $200.
        m = _comps_pb_method(self._pc(tgt_roe=0.24, peer_roe=0.12))
        assert m is not None and m.mid == pytest.approx(2.0 * 2.0 * 50.0)  # 200
        assert "ROE-adjusted ×2.00" in m.assumptions

    def test_low_roe_target_scaled_down(self):
        # AIG-shape: target 8% vs peer 16% → ×0.5 → $100 flat becomes $50.
        m = _comps_pb_method(self._pc(tgt_roe=0.08, peer_roe=0.16))
        assert m is not None and m.mid == pytest.approx(2.0 * 0.5 * 50.0)  # 50

    def test_scale_ratio_clamped(self):
        # target 30% vs peer 5% → raw ×6.0 clamped to the 2.6× cap.
        warns: list[str] = []
        m = _comps_pb_method(self._pc(tgt_roe=0.30, peer_roe=0.05), warns)
        assert m is not None and m.mid == pytest.approx(2.0 * 2.6 * 50.0)  # 260
        assert "clamped from 6.00×" in m.assumptions

    def test_dirty_peer_roe_falls_back_to_flat(self):
        # Peer-median ROE below the 2% divisor floor → unstable ratio → flat + disclose.
        warns: list[str] = []
        m = _comps_pb_method(self._pc(tgt_roe=0.20, peer_roe=0.01), warns)
        assert m is not None and m.mid == pytest.approx(2.0 * 50.0)  # flat 100
        assert any("adjustment skipped" in w for w in warns)

    def test_non_positive_target_roe_falls_back_to_flat(self):
        m = _comps_pb_method(self._pc(tgt_roe=-0.05, peer_roe=0.12))
        assert m is not None and m.mid == pytest.approx(2.0 * 50.0)  # flat 100
