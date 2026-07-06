"""Tests for engine/compute/coordinators/segment_extractor.build_sotp_breakdown.

The SOTP-floor coordinator (Batch 3B v1): consumes DataLayer.fetch_segments,
maps each reportable segment onto a deterministic comparable multiple, and hands
the legs to the pure compute_sotp_breakdown operator. A fake DataLayer feeds
crafted SEC segment payloads; the real operator computes the floor arithmetic.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from finrobot.engine.compute.coordinators.segment_extractor import build_sotp_breakdown
from finrobot.engine.data.layer import DataLayer
from finrobot.engine.models.financial import SOTPBreakdown


class _SegResult:
    """Minimal DataResult stand-in — build_sotp_breakdown reads .data + .warnings."""

    def __init__(self, data: dict[str, Any], warnings: list[str] | None = None) -> None:
        self.data = data
        self.warnings = warnings or []


class _FakeLayer:
    def __init__(
        self, result: _SegResult | None = None, *, price_target: dict[str, Any] | None = None
    ) -> None:
        self._result = result
        self._price_target = price_target
        self.calls = 0

    async def fetch_segments(self, ticker: str) -> _SegResult | None:
        self.calls += 1
        return self._result

    async def fetch_price_target(self, ticker: str) -> _SegResult | None:
        # Batch 3B v2 street scenario band source; None → band drops (floor still ships).
        return _SegResult(self._price_target) if self._price_target is not None else None


def _segments_result(
    segments: dict[str, Any], *, currency: str = "USD", end: str = "2024-12-31"
) -> _SegResult:
    return _SegResult(
        data={
            "segments": segments,
            "period": {"end": end},
            "accession": "0000000000-24-000001",
            "currency": currency,
        }
    )


# Net cash, ~TSLA-scale shares/price — a clean option-value market.
_TWO_SEGMENTS = {
    "Automotive": {"gross_profit": 20e9},
    "EnergyGenerationAndStorage": {"gross_profit": 1e9},
}


async def _run(
    layer: _FakeLayer,
    *,
    net_debt: float = -10e9,
    shares_outstanding: float = 3.2e9,
    current_price: float = 250.0,
    option_ev_if_success: float | None = None,
    option_anchor_source: str | None = None,
) -> SOTPBreakdown | None:
    """Invoke the coordinator with the fake layer cast to its typed param and
    ~TSLA-scale market defaults (net cash, option-value cap)."""
    return await build_sotp_breakdown(
        cast(DataLayer, layer),
        "TSLA",
        net_debt=net_debt,
        shares_outstanding=shares_outstanding,
        current_price=current_price,
        option_ev_if_success=option_ev_if_success,
        option_anchor_source=option_anchor_source,
    )


class TestBuildSotpBreakdownGates:
    async def test_non_positive_shares_returns_none_without_fetch(self):
        layer = _FakeLayer(_segments_result(_TWO_SEGMENTS))
        out = await _run(layer, shares_outstanding=0.0)
        assert out is None
        assert layer.calls == 0  # gated before any SEC fetch

    async def test_non_positive_price_returns_none_without_fetch(self):
        layer = _FakeLayer(_segments_result(_TWO_SEGMENTS))
        out = await _run(layer, current_price=0.0)
        assert out is None
        assert layer.calls == 0

    async def test_fetch_segments_none_returns_none(self):
        layer = _FakeLayer(None)
        assert await _run(layer) is None

    async def test_non_usd_currency_dropped(self):
        layer = _FakeLayer(_segments_result(_TWO_SEGMENTS, currency="CNY"))
        assert await _run(layer) is None

    async def test_single_modelable_segment_returns_none(self):
        layer = _FakeLayer(_segments_result({"Automotive": {"gross_profit": 20e9}}))
        assert await _run(layer) is None

    async def test_segment_without_gross_profit_skipped_below_floor(self):
        segs = {
            "Automotive": {"gross_profit": 20e9},
            "EnergyGenerationAndStorage": {"gross_profit": None},
        }
        layer = _FakeLayer(_segments_result(segs))
        # Only one valuable leg survives → below the 2-segment floor → None.
        assert await _run(layer) is None


class TestBuildSotpBreakdownArithmetic:
    async def test_known_multiples_and_floor(self):
        layer = _FakeLayer(_segments_result(_TWO_SEGMENTS))
        out = await _run(layer)
        assert out is not None
        by_name = {s.name: s for s in out.modelable_segments}
        assert by_name["Automotive"].multiple == 6.0
        # v2 (2026-07-06): energy leg is the solar/storage peer-derived median 9.6×.
        assert by_name["Energy generation and storage"].multiple == pytest.approx(9.6)
        # ev_floor = 20e9×6 + 1e9×9.6 = 129.6e9; equity_floor = 129.6e9 − (−10e9) = 139.6e9.
        assert out.ev_floor == pytest.approx(129.6e9)
        assert out.equity_floor == pytest.approx(139.6e9)
        assert out.market_equity == pytest.approx(250.0 * 3.2e9)
        assert out.implied_option_ev == pytest.approx(250.0 * 3.2e9 - 139.6e9)

    async def test_energy_peer_provenance_and_auto_captive_disclosure(self):
        # Slice ① (v2): the energy multiple's provenance names the peer set + as-of;
        # the auto leg discloses WHY ex-captive-finance can't be computed.
        layer = _FakeLayer(_segments_result(_TWO_SEGMENTS))
        out = await _run(layer)
        assert out is not None
        by_name = {s.name: s for s in out.modelable_segments}
        energy = by_name["Energy generation and storage"].multiple_source
        assert "solar/storage peer median" in energy
        assert "ENPH" in energy and "as-of 2026-07-06" in energy
        auto = by_name["Automotive"].multiple_source
        assert "netReceivables" in auto and "captive" in auto.lower()
        assert "金融待核 F2" in auto

    async def test_unknown_segment_uses_default_multiple(self):
        segs = {
            "Automotive": {"gross_profit": 20e9},
            "Services": {"gross_profit": 2e9, "label": "Services"},
        }
        layer = _FakeLayer(_segments_result(segs))
        out = await _run(layer)
        assert out is not None
        svc = {s.name: s for s in out.modelable_segments}["Services"]
        assert svc.multiple == 6.0  # _DEFAULT_EV_GROSS_PROFIT
        assert "default conservative" in svc.multiple_source

    async def test_external_anchor_surfaces_success_probability(self):
        # A genuine external SUCCESS-state ceiling (if one existed) surfaces the
        # implied probability. In production it stays None — a 12-month street
        # target is the wrong caliber (see TestScenarioBandAndSuccessCeiling).
        layer = _FakeLayer(_segments_result(_TWO_SEGMENTS))
        out = await _run(layer, option_ev_if_success=900e9, option_anchor_source="hypothetical")
        assert out is not None
        assert out.option_ev_if_success == pytest.approx(900e9)
        assert out.implied_success_probability == pytest.approx(out.implied_option_ev / 900e9)


# --- External anchor: FMP /price-target-consensus (TSLA, probed 2026-07-06) ----
_TSLA_TARGETS: dict[str, Any] = {
    "low": 360.0,
    "consensus": 443.70,
    "median": 440.0,
    "high": 540.0,
    "analyst_count": 41,
    "source": "FMP /price-target-consensus",
}


class TestScenarioBandAndSuccessCeiling:
    async def test_street_band_attached_and_robotaxi_success_withheld(self):
        layer = _FakeLayer(_segments_result(_TWO_SEGMENTS), price_target=_TSLA_TARGETS)
        out = await _run(layer, current_price=393.45)
        assert out is not None
        # Slice ②: the robotaxi-success ceiling / probability stays None + discloses
        # the refusal (a 12-month analyst target is the wrong caliber).
        assert out.option_ev_if_success is None
        assert out.implied_success_probability is None
        assert any("robotaxi-success probability withheld" in w for w in out.warnings)
        assert any("金融待核 F3" in w for w in out.warnings)
        # Slice ③: the street band is attached; range_position is STREET positioning
        # (NOT a success probability), (393.45 − 360) / (540 − 360) ≈ 0.1858.
        band = out.scenario_band
        assert band is not None
        assert (band.bear, band.base, band.bull) == (360.0, 443.70, 540.0)
        assert band.range_position == pytest.approx((393.45 - 360.0) / (540.0 - 360.0))
        assert band.confidence == "low"
        assert band.analyst_count == 41
        # C: the reverse-SOTP cash-flow floor rides as an independent present-value
        # anchor (== the breakdown's price_floor) + the same-caliber floor/price
        # coverage; NO floor→street cross-caliber ratio.
        assert band.cash_flow_floor == pytest.approx(out.price_floor)
        assert band.floor_coverage == pytest.approx(out.price_floor / 393.45)

    async def test_band_dropped_when_targets_unavailable(self):
        layer = _FakeLayer(_segments_result(_TWO_SEGMENTS))  # price_target=None
        out = await _run(layer)
        assert out is not None
        # The reverse-SOTP floor still ships; only the street band drops + discloses.
        assert out.scenario_band is None
        assert any("scenario band dropped" in w for w in out.warnings)
        assert out.price_floor > 0
