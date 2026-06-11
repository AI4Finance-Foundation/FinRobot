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
    def __init__(self, result: _SegResult | None = None) -> None:
        self._result = result
        self.calls = 0

    async def fetch_segments(self, ticker: str) -> _SegResult | None:
        self.calls += 1
        return self._result


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
        assert by_name["Energy generation and storage"].multiple == 10.0
        # ev_floor = 20e9×6 + 1e9×10 = 130e9; equity_floor = 130e9 − (−10e9) = 140e9.
        assert out.ev_floor == pytest.approx(130e9)
        assert out.equity_floor == pytest.approx(140e9)
        assert out.market_equity == pytest.approx(250.0 * 3.2e9)
        assert out.implied_option_ev == pytest.approx(250.0 * 3.2e9 - 140e9)
        # [金融待核 F2] proxy caliber must surface in the leg source.
        assert "金融待核 F2" in by_name["Automotive"].multiple_source

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
        layer = _FakeLayer(_segments_result(_TWO_SEGMENTS))
        out = await _run(layer, option_ev_if_success=900e9, option_anchor_source="MS bull SOTP")
        assert out is not None
        assert out.option_ev_if_success == pytest.approx(900e9)
        assert out.implied_success_probability == pytest.approx(out.implied_option_ev / 900e9)
