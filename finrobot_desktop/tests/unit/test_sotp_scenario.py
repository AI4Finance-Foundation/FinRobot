"""Forward SOTP scenario band (Batch 3B v2) — operator boundaries + coordinator wiring.

Expected values anchor to EXTERNAL authoritative sources, not the implementation:
the TSLA street distribution is the FMP ``/price-target-consensus`` payload probed
live 2026-07-06 — targetLow $360 / targetConsensus $443.70 / targetMedian $440 /
targetHigh $540, with 41 analysts contributing targets in the trailing year (FMP
``/price-target-summary`` lastYearCount). ``range_position`` is the pure arithmetic
position of the live price within the street range — a STREET metric, never a
robotaxi-success probability (team-lead guardrail 2026-07-06).
"""

from __future__ import annotations

import math

import pytest

from finrobot.engine.compute.operators.sotp_scenario import compute_scenario_band

# --- External anchors (FMP price-target endpoints, TSLA, probed 2026-07-06) ----
TSLA_LOW = 360.0
TSLA_CONSENSUS = 443.70
TSLA_MEDIAN = 440.0
TSLA_HIGH = 540.0
TSLA_PRICE = 393.45
TSLA_ANALYSTS = 41

_SRC = "FMP /price-target-consensus"


# --- Boundary 1: normal street band + range_position (external TSLA anchors) ---
def test_boundary_1_street_band_range_position() -> None:
    b = compute_scenario_band(
        bear=TSLA_LOW,
        base=TSLA_CONSENSUS,
        bull=TSLA_HIGH,
        median=TSLA_MEDIAN,
        current_price=TSLA_PRICE,
        analyst_count=TSLA_ANALYSTS,
        source=_SRC,
    )
    assert b is not None
    assert (b.bear, b.base, b.bull, b.median) == (TSLA_LOW, TSLA_CONSENSUS, TSLA_HIGH, TSLA_MEDIAN)
    # (393.45 − 360) / (540 − 360) = 33.45 / 180 = 0.185833…  the live price sits
    # near the BEARISH end of the street range (market below consensus $443.70).
    assert b.range_position == pytest.approx((TSLA_PRICE - TSLA_LOW) / (TSLA_HIGH - TSLA_LOW))
    assert b.range_position == pytest.approx(0.185833, abs=1e-5)
    assert b.confidence == "low"  # street-anchored forward is inherently low
    assert b.analyst_count == TSLA_ANALYSTS
    assert b.warnings == []


# --- Boundary 2: thin analyst coverage → confidence very_low + disclosure -------
def test_boundary_2_thin_coverage_downgrades_confidence() -> None:
    b = compute_scenario_band(
        bear=TSLA_LOW,
        base=TSLA_CONSENSUS,
        bull=TSLA_HIGH,
        median=None,
        current_price=TSLA_PRICE,
        analyst_count=3,  # < _THIN_COVERAGE_N
        source=_SRC,
    )
    assert b is not None
    assert b.confidence == "very_low"
    assert any("thin analyst coverage" in w for w in b.warnings)
    # Band is NOT numerically widened — the sourced bounds are unchanged.
    assert (b.bear, b.bull) == (TSLA_LOW, TSLA_HIGH)
    # count unknown likewise downgrades.
    b2 = compute_scenario_band(
        bear=TSLA_LOW,
        base=TSLA_CONSENSUS,
        bull=TSLA_HIGH,
        median=None,
        current_price=TSLA_PRICE,
        analyst_count=None,
        source=_SRC,
    )
    assert b2 is not None and b2.confidence == "very_low"


# --- Boundary 3: price above the bull leg → range_position > 1 (legal signal) ---
def test_boundary_3_price_above_bull_unclamped() -> None:
    b = compute_scenario_band(
        bear=TSLA_LOW,
        base=TSLA_CONSENSUS,
        bull=TSLA_HIGH,
        median=TSLA_MEDIAN,
        current_price=600.0,  # above the $540 street high
        analyst_count=TSLA_ANALYSTS,
        source=_SRC,
    )
    assert b is not None
    assert b.range_position > 1  # NOT clamped
    assert any("above the most bullish" in w for w in b.warnings)


# --- Boundary 4: price below the bear leg → range_position < 0 (legal signal) ---
def test_boundary_4_price_below_bear_unclamped() -> None:
    b = compute_scenario_band(
        bear=TSLA_LOW,
        base=TSLA_CONSENSUS,
        bull=TSLA_HIGH,
        median=TSLA_MEDIAN,
        current_price=300.0,  # below the $360 street low
        analyst_count=TSLA_ANALYSTS,
        source=_SRC,
    )
    assert b is not None
    assert b.range_position < 0  # NOT clamped
    assert any("below the most bearish" in w for w in b.warnings)


# --- Boundary 5: degenerate / missing bounds → None (never fabricate a bound) --
@pytest.mark.parametrize(
    ("bear", "base", "bull", "median", "price"),
    [
        (540.0, 443.70, 360.0, 440.0, TSLA_PRICE),  # inverted: bull <= bear
        (360.0, 443.70, 360.0, 440.0, TSLA_PRICE),  # degenerate: bull == bear
        (None, 443.70, 540.0, 440.0, TSLA_PRICE),  # missing bear
        (360.0, 443.70, None, 440.0, TSLA_PRICE),  # missing bull
        (360.0, None, 540.0, None, TSLA_PRICE),  # no central leg (consensus+median both None)
        (360.0, 443.70, 540.0, 440.0, 0.0),  # non-positive price
        (360.0, 443.70, 540.0, 440.0, math.nan),  # non-finite price
        (-360.0, 443.70, 540.0, 440.0, TSLA_PRICE),  # non-positive bear
    ],
)
def test_boundary_5_degenerate_or_missing_returns_none(
    bear: float | None,
    base: float | None,
    bull: float | None,
    median: float | None,
    price: float,
) -> None:
    b = compute_scenario_band(
        bear=bear,
        base=base,
        bull=bull,
        median=median,
        current_price=price,
        analyst_count=TSLA_ANALYSTS,
        source=_SRC,
    )
    assert b is None


# --- Central-leg fallback: consensus missing but median present → base = median -
def test_central_leg_falls_back_to_median() -> None:
    b = compute_scenario_band(
        bear=TSLA_LOW,
        base=None,
        bull=TSLA_HIGH,
        median=TSLA_MEDIAN,
        current_price=TSLA_PRICE,
        analyst_count=TSLA_ANALYSTS,
        source=_SRC,
    )
    assert b is not None
    assert b.base == pytest.approx(TSLA_MEDIAN)


# --- C (4-point merge): floor anchor is present-value, NO cross-caliber ratio ---
def test_c_floor_anchor_present_value_and_same_caliber_coverage() -> None:
    floor = 40.41  # reverse-SOTP cash-flow floor (present value)
    b = compute_scenario_band(
        bear=TSLA_LOW,
        base=TSLA_CONSENSUS,
        bull=TSLA_HIGH,
        median=TSLA_MEDIAN,
        current_price=TSLA_PRICE,
        analyst_count=TSLA_ANALYSTS,
        source=_SRC,
        cash_flow_floor=floor,
    )
    assert b is not None
    # The floor rides as an INDEPENDENT present-value anchor + the ONLY allowed
    # floor-vs-price relation: floor/price (same caliber, ~10.3%).
    assert b.cash_flow_floor == pytest.approx(floor)
    assert b.floor_coverage == pytest.approx(floor / TSLA_PRICE)
    # 🔴 range_position stays the SAME-caliber street-range position (18.6%), NEVER
    # the forbidden floor→bull cross-caliber ratio (~70.7%) — that number must
    # appear on no field.
    assert b.range_position == pytest.approx((TSLA_PRICE - TSLA_LOW) / (TSLA_HIGH - TSLA_LOW))
    forbidden = (TSLA_PRICE - floor) / (TSLA_HIGH - floor)  # ≈ 0.707
    assert forbidden not in (b.range_position, b.floor_coverage)
    assert b.range_position != pytest.approx(forbidden, abs=0.02)


def test_c_floor_absent_leaves_anchor_and_coverage_none() -> None:
    b = compute_scenario_band(
        bear=TSLA_LOW,
        base=TSLA_CONSENSUS,
        bull=TSLA_HIGH,
        median=None,
        current_price=TSLA_PRICE,
        analyst_count=TSLA_ANALYSTS,
        source=_SRC,  # no cash_flow_floor
    )
    assert b is not None
    assert b.cash_flow_floor is None
    assert b.floor_coverage is None
    assert b.range_position == pytest.approx((TSLA_PRICE - TSLA_LOW) / (TSLA_HIGH - TSLA_LOW))


# Coordinator wiring (band attached + robotaxi-success ceiling withheld) is tested
# in test_segment_extractor.py::TestScenarioBandAndSuccessCeiling — the single home
# for build_sotp_breakdown integration tests. This file stays operator-only.
