"""Tests for compute/market.py — technical_payload (pure) + get_technicals (门一收口).

ADR yfinance 收口: get_technicals must pull the price series via
DataLayer.fetch_canonical(PRICE), never yfinance directly.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from finrobot.engine.compute.coordinators.market import get_technicals, technical_payload
from finrobot.engine.data.interface import ProviderError
from finrobot.engine.data.normalize.contracts import NormalizedPrice, PriceBar, Provenance

UTC = timezone.utc
NOW = datetime(2026, 5, 30, tzinfo=UTC)


def _hist(closes: list[float]) -> list[dict[str, float]]:
    return [{"close": c} for c in closes]


class TestTechnicalPayload:
    def test_insufficient_history(self) -> None:
        out = technical_payload(_hist([1.0] * 10))
        assert out == {"available": False, "reason": "insufficient_history"}

    def test_uptrend_when_smas_stacked(self) -> None:
        # Monotonically rising series → SMA20 > SMA50 > SMA200 → uptrend.
        closes = [float(i) for i in range(1, 221)]
        out = technical_payload(_hist(closes))
        assert out["available"] is True
        assert out["trend"] == "uptrend"
        assert out["sma20"] > out["sma50"] > out["sma200"]
        assert out["current_price"] == 220.0
        assert out["range_position"] == pytest.approx(1.0)

    def test_range_position_midpoint(self) -> None:
        closes = [10.0] * 19 + [20.0, 0.0, 10.0]  # high 20, low 0, current 10
        out = technical_payload(_hist(closes))
        assert out["high_52w"] == 20.0
        assert out["low_52w"] == 0.0
        assert out["range_position"] == pytest.approx(0.5)

    def test_52w_range_uses_intraday_high_low_when_present(self) -> None:
        # Closes never exceed 100, but an intraday spike to 120 and dip to 80 are
        # the real 52-week extremes (Yahoo/Bloomberg convention). The snapshot
        # must use them, not the close-only range.
        bars: list[dict[str, float]] = [{"close": 100.0, "high": 100.0, "low": 100.0}] * 19
        bars.append({"close": 100.0, "high": 120.0, "low": 80.0})
        out = technical_payload(bars)
        assert out["high_52w"] == 120.0
        assert out["low_52w"] == 80.0
        # current 100 in [80, 120] → halfway.
        assert out["range_position"] == pytest.approx(0.5)


class _FakeLayer:
    def __init__(self, price: NormalizedPrice | None = None, exc: Exception | None = None) -> None:
        self._price = price
        self._exc = exc

    async def fetch_canonical(self, data_type: str, ticker: str):  # type: ignore[no-untyped-def]
        if self._exc is not None:
            raise self._exc
        return self._price


def _price(closes: list[float]) -> NormalizedPrice:
    bars = [PriceBar(date=datetime(2026, 1, 1, tzinfo=UTC).date(), close=c) for c in closes]
    return NormalizedPrice(
        ticker="AAPL",
        current_price=closes[-1],
        bars=bars,
        provenance=Provenance(provider="fmp", as_of=NOW, fetched_at=NOW),
    )


class TestGetTechnicals:
    async def test_computes_from_canonical_price(self) -> None:
        layer = _FakeLayer(price=_price([float(i) for i in range(1, 221)]))
        out = await get_technicals("AAPL", layer)  # type: ignore[arg-type]
        assert out["available"] is True
        assert out["trend"] == "uptrend"

    async def test_provider_error_returns_unavailable(self) -> None:
        layer = _FakeLayer(exc=ProviderError("upstream down"))
        out = await get_technicals("AAPL", layer)  # type: ignore[arg-type]
        assert out == {"available": False, "reason": "no_data"}
