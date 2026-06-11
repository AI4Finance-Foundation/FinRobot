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

from finrobot.engine.compute.operators.cyclical_peers import cyclical_peer_group
from finrobot.engine.compute.operators.multiples import (
    PEER_PB_SANITY_MAX,
    calculate_multiples,
    calculate_peer_statistics,
)
from finrobot.engine.compute.operators.valuation_aggregator import (
    _comps_pb_method,
    aggregate_valuation,
)
from finrobot.engine.pipelines._helpers import _inject_cyclical_peers
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
        out = _inject_cyclical_peers(payload, "MU")
        # storage cohort is prepended (high-affinity Tier 1) ahead of the logic semis
        assert out["industry_screen"][:3] == ["WDC", "STX", "SNDK"]
        assert "NVDA" in out["industry_screen"]
        # other tiers untouched
        assert out["stock_peers"] == ["LRCX"]

    def test_does_not_mutate_cached_payload(self):
        payload = {"industry_screen": ["NVDA"]}
        _inject_cyclical_peers(payload, "MU")
        # original dict is never mutated (cache safety)
        assert payload["industry_screen"] == ["NVDA"]

    def test_dedups_when_cohort_member_already_present(self):
        payload = {"industry_screen": ["WDC", "NVDA"]}
        out = _inject_cyclical_peers(payload, "MU")
        assert out["industry_screen"].count("WDC") == 1

    def test_non_cyclical_returns_payload_unchanged(self):
        payload = {"industry_screen": ["MSFT", "GOOGL"]}
        out = _inject_cyclical_peers(payload, "AAPL")
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
        assert any("comps_pb" in w and "样本仅 2" in w for w in warnings)

    def test_refuses_on_premise_mismatch_over_10x(self):
        warnings: list[str] = []
        # target P/B 50x vs peer median 2x = 25x mismatch → premise rejected.
        comps = self._comps_with_median(2.0, 4, target_bvps=40.0, target_pb=50.0)
        m = _comps_pb_method(comps, warnings)
        assert m is None
        assert any("comps_pb" in w and "相差" in w for w in warnings)

    def test_falls_back_when_target_bvps_unavailable(self):
        warnings: list[str] = []
        comps = self._comps_with_median(2.0, 4, target_bvps=None)
        m = _comps_pb_method(comps, warnings)
        assert m is None
        assert any("每股账面价值不可得" in w for w in warnings)


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
