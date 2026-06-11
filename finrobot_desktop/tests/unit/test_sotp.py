"""Scenario SOTP (Batch 3B v1) — 5 boundary tests.

Mock-only (no SEC network — watchdog-safe). Expected values are anchored to
EXTERNAL authoritative sources, not to the implementation:

  · TSLA FY2025 segments — SEC 10-K accession 0001628280-26-003952 (filed
    2026-01-29): Automotive revenue $69.526B / segment gross profit $13.292B;
    Energy generation and storage revenue $12.771B / segment gross profit
    $3.802B. (Design spec §1, table from the original 10-K XBRL; independently
    corroborated by BofA / media: Tesla Energy ~$12.77B @ ~30% margin.)
  · The reverse-SOTP arithmetic mirrors reverse-DCF: floor = Σ(metric×multiple) −
    net_debt; implied_option_ev = market_equity − equity_floor (pure subtraction);
    implied_success_probability = implied_option_ev / option_ev_if_success.
  · The member-normalization join is the load-bearing extraction subtlety: segment
    gross profit rides ``StatementBusinessSegmentsAxis`` while segment revenue
    rides ``ProductOrServiceAxis``, with DIFFERENT label strings — they must be
    matched by normalized member key, never by label.
"""

from __future__ import annotations

import pytest

from finrobot.engine.compute.operators.sotp import compute_sotp_breakdown, value_segment
from finrobot.engine.data.providers.edgar_provider import (
    EdgarToolsProvider,
    _normalize_segment_member,
    extract_segment_facts,
)


# --- External SEC anchors (TSLA FY2025 10-K 0001628280-26-003952) -------------
TSLA_AUTO_GP = 13.292e9
TSLA_ENERGY_GP = 3.802e9
TSLA_AUTO_REV = 69.526e9
TSLA_ENERGY_REV = 12.771e9


class _FakeQuery:
    """Minimal edgartools ``xbrl.query().by_concept(c).execute()`` stand-in."""

    def __init__(self, rows_by_concept: dict[str, list[dict[str, object]]]) -> None:
        self._rows = rows_by_concept
        self._concept: str | None = None

    def by_concept(self, concept: str) -> "_FakeQuery":
        self._concept = concept
        return self

    def execute(self) -> list[dict[str, object]]:
        return self._rows.get(self._concept or "", [])


class _FakeXBRL:
    def __init__(self, rows_by_concept: dict[str, list[dict[str, object]]]) -> None:
        self._rows = rows_by_concept

    def query(self) -> _FakeQuery:
        return _FakeQuery(self._rows)


def _tsla_xbrl() -> _FakeXBRL:
    """A faithful FY2025 segment fixture: GP on the segment axis (different label
    strings), revenue on the product axis — exactly the two-axis shape the real
    10-K emits (verified by direct probe), so the join is exercised honestly."""
    period = {"period_start": "2025-01-01", "period_end": "2025-12-31"}
    return _FakeXBRL(
        {
            "GrossProfit": [
                {
                    **period,
                    "is_dimensioned": True,
                    "dimension": "us-gaap:StatementBusinessSegmentsAxis",
                    "member": "tsla:AutomotiveSegmentMember",
                    "dimension_member_label": "Automotive segment",
                    "numeric_value": TSLA_AUTO_GP,
                    "unit_ref": "usd",
                },
                {
                    **period,
                    "is_dimensioned": True,
                    "dimension": "us-gaap:StatementBusinessSegmentsAxis",
                    "member": "tsla:EnergyGenerationAndStorageSegmentMember",
                    "dimension_member_label": "Energy generation and storage segment",
                    "numeric_value": TSLA_ENERGY_GP,
                    "unit_ref": "usd",
                },
            ],
            "RevenueFromContractWithCustomerExcludingAssessedTax": [
                {
                    **period,
                    "is_dimensioned": True,
                    "dimension": "srt:ProductOrServiceAxis",
                    "member": "tsla:AutomotiveRevenuesMember",  # note: different label
                    "numeric_value": TSLA_AUTO_REV,
                },
                {
                    **period,
                    "is_dimensioned": True,
                    "dimension": "srt:ProductOrServiceAxis",
                    "member": "tsla:EnergyGenerationAndStorageMember",
                    "numeric_value": TSLA_ENERGY_REV,
                },
            ],
        }
    )


# --- Boundary 1: TSLA segment extraction matches SEC anchols via member join ---
def test_boundary_1_tsla_segment_extraction_matches_sec_anchors() -> None:
    data, warnings = extract_segment_facts(_tsla_xbrl())
    segs = data["segments"]
    assert set(segs) == {"Automotive", "EnergyGenerationAndStorage"}
    # Revenue (ProductOrServiceAxis) JOINED onto gross profit (segment axis) by
    # normalized member key, despite different label strings.
    assert segs["Automotive"]["revenue"] == pytest.approx(TSLA_AUTO_REV)
    assert segs["Automotive"]["gross_profit"] == pytest.approx(TSLA_AUTO_GP)
    assert segs["EnergyGenerationAndStorage"]["revenue"] == pytest.approx(TSLA_ENERGY_REV)
    assert segs["EnergyGenerationAndStorage"]["gross_profit"] == pytest.approx(TSLA_ENERGY_GP)
    assert data["currency"] == "USD"
    assert data["period"] == {"start": "2025-01-01", "end": "2025-12-31"}
    assert warnings == []  # both legs have a matched revenue member


# --- Boundary 2: the member-normalization join key (load-bearing) -------------
@pytest.mark.parametrize(
    ("member", "expected"),
    [
        ("tsla:AutomotiveSegmentMember", "Automotive"),
        ("tsla:AutomotiveRevenuesMember", "Automotive"),
        ("tsla:EnergyGenerationAndStorageSegmentMember", "EnergyGenerationAndStorage"),
        ("tsla:EnergyGenerationAndStorageMember", "EnergyGenerationAndStorage"),
        ("", None),
        (None, None),
    ],
)
def test_boundary_2_member_normalization_join_key(member: str | None, expected: str | None) -> None:
    # GP axis ("...SegmentMember") and revenue axis ("...RevenuesMember") must
    # normalize to the SAME key — that identity IS the cross-axis join.
    assert _normalize_segment_member(member) == expected


# --- Boundary 3: TSLA reverse-SOTP arithmetic (floor + implied option) --------
def test_boundary_3_tsla_reverse_sotp_arithmetic() -> None:
    # Conservative comparable multiples (coordinator's F2 proxies): auto 6x,
    # energy 10x EV/gross-profit. Market inputs from the design spec §6.1 (live
    # probe 2026-06-10): price ~$388.88, ~3.22B shares, ~net cash $23B.
    legs = [
        value_segment(
            name="Automotive",
            metric_label="FY2025 segment gross profit",
            metric_value=TSLA_AUTO_GP,
            multiple=6.0,
            multiple_source="auto OEM peer proxy EV/gross-profit",
        ),
        value_segment(
            name="Energy generation and storage",
            metric_label="FY2025 segment gross profit",
            metric_value=TSLA_ENERGY_GP,
            multiple=10.0,
            multiple_source="storage/utility peer proxy EV/gross-profit",
        ),
    ]
    b = compute_sotp_breakdown(
        ticker="TSLA",
        modelable_segments=legs,
        net_debt=-23e9,
        shares_outstanding=3.22e9,
        current_price=388.88,
    )
    # ev_floor = 13.292*6 + 3.802*10 = 79.752 + 38.02 = 117.772B
    assert b.ev_floor == pytest.approx(117.772e9, rel=1e-6)
    # equity_floor = ev_floor - net_debt = 117.772 - (-23) = 140.772B
    assert b.equity_floor == pytest.approx(140.772e9, rel=1e-6)
    # market_equity = 388.88 * 3.22e9 = 1252.1936B
    assert b.market_equity == pytest.approx(388.88 * 3.22e9)
    # implied_option_ev = market - equity_floor (pure subtraction)
    assert b.implied_option_ev == pytest.approx(b.market_equity - b.equity_floor)
    # At conservative multiples the option share is honestly LARGE (>0.5) — TSLA
    # is the canonical option-value name; most of cap is optionality.
    assert b.implied_option_pct > 0.5
    assert b.implied_option_pct == pytest.approx(b.implied_option_ev / b.market_equity)
    assert b.floor_exceeds_market is False
    assert b.price_floor == pytest.approx(b.equity_floor / 3.22e9)


# --- Boundary 4: floor_exceeds_market rejection (not an option-premium name) ---
def test_boundary_4_floor_exceeds_market_flags_non_option_name() -> None:
    # A name whose deterministic cash-flow floor already EXCEEDS its market cap is
    # NOT an option-premium name — SOTP option decomposition does not apply (it
    # should run ordinary multi-method, possibly a BUY). Mirrors reverse-DCF's
    # growth_unreachable degeneracy guard.
    legs = [
        value_segment(
            name="SegA",
            metric_label="gp",
            metric_value=50e9,
            multiple=10.0,
            multiple_source="x",
        ),
    ]
    b = compute_sotp_breakdown(
        ticker="CHEAP",
        modelable_segments=legs,
        net_debt=0.0,
        shares_outstanding=1e9,
        current_price=100.0,  # market_equity = 100B < ev_floor 500B
    )
    assert b.equity_floor == pytest.approx(500e9)
    assert b.market_equity == pytest.approx(100e9)
    assert b.floor_exceeds_market is True
    assert b.implied_option_ev < 0  # legal negative — not clamped
    assert b.implied_option_pct < 0
    assert any("floor exceeds market" in w for w in b.warnings)


# --- Boundary 5: market exceeds full-success SOTP ceiling (implied prob > 1) ---
def test_boundary_5_market_exceeds_success_ceiling() -> None:
    # When an external sell-side success-state ceiling is supplied and the market-
    # implied option value exceeds even it, implied_success_probability > 1 — a
    # stronger over-pricing signal than reverse-DCF unreachable.
    legs = [
        value_segment(
            name="Auto",
            metric_label="gp",
            metric_value=TSLA_AUTO_GP,
            multiple=6.0,
            multiple_source="x",
        ),
        value_segment(
            name="Energy",
            metric_label="gp",
            metric_value=TSLA_ENERGY_GP,
            multiple=10.0,
            multiple_source="y",
        ),
    ]
    # implied_option_ev ≈ 1252.19 − 140.77 ≈ $1111.4B; a success ceiling BELOW
    # that (e.g. a $500B sell-side robotaxi-success cap) → implied prob > 1.
    b = compute_sotp_breakdown(
        ticker="TSLA",
        modelable_segments=legs,
        net_debt=-23e9,
        shares_outstanding=3.22e9,
        current_price=388.88,
        option_ev_if_success=500e9,
        option_anchor_source="hypothetical sell-side robotaxi-success ceiling $500B",
    )
    assert b.implied_success_probability is not None
    assert b.implied_success_probability == pytest.approx(b.implied_option_ev / 500e9)
    assert b.implied_success_probability > 1
    assert b.market_exceeds_success_ceiling is True
    assert any("exceeds even the full-success" in w for w in b.warnings)


# --- Guard: SEC segment route stays OFF capabilities() (never primary) --------
def test_segment_route_not_in_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "finrobot.engine.data.providers.edgar_provider.set_identity", lambda *_: None
    )
    prov = EdgarToolsProvider("Tester tester@example.com")
    caps = [str(c) for c in prov.capabilities()]
    assert not any("segment" in c.lower() for c in caps)


# --- Guard: single-segment issuer degenerates (extract yields <2, no value) ---
def test_single_segment_issuer_yields_no_floor() -> None:
    # A non-dimensioned / single-segment XBRL → no segment-axis gross profit → the
    # extractor returns an empty segments dict + a warning (the coordinator then
    # drops the SOTP channel; SOTP degenerates to ordinary valuation).
    empty = _FakeXBRL(
        {"GrossProfit": [], "RevenueFromContractWithCustomerExcludingAssessedTax": []}
    )
    data, warnings = extract_segment_facts(empty)
    assert data["segments"] == {}
    assert any("single-segment" in w or "non-dimensioned" in w for w in warnings)
