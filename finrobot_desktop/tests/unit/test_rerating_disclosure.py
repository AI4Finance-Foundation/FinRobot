"""Multiples methods must disclose the re-rating they IMPLICITLY assume.

Pricing a target at a peer median P/E (comps_pe) or reverting it to its own
historical EV/EBITDA band (ev_ebitda) silently presumes the target's OWN
multiple converges from where it trades today to that anchor. Two independent
external reviews flagged the MSFT report for anchoring a $621 comps_pe target on
a peer median forward P/E of 31.9x while MSFT itself trades at 19.8x forward —
an unstated +61% re-rating — and a $632 ev_ebitda target on the same silent
"revert to own historical band" premise.

This slice is PURE TRANSPARENCY: compute the implied re-rating and disclose it
(always in ``assumptions``; also as a warning when the shift is large). It must
change NO number the methods output (mid/low/high/confidence) and touch none of
the suppression / refusal branches. These tests pin exactly that:

- the disclosure appears on the disclosing paths (forward + trailing/core),
- it is OMITTED on the mixed-caliber fallback (a trailing peer median applied to
  a forward EPS is not an apples-to-apples self-vs-peer comparison — 绝不混口径),
- it is symmetric (up = "expand", down = "compress"),
- ``current_price=None`` discloses nothing and leaves every output number byte-equal,
- the disclosure strings carry NO ``$`` amount and NO ticker (the two failure modes
  the narrative scrubber punished for the cyclical-suppression reason string).
"""

from __future__ import annotations

import pytest

from finrobot.engine.compute.operators.valuation_aggregator import (
    _comps_pe_method,
    _ev_ebitda_method,
)
from finrobot.engine.models.financial import CompanyFinancials, PeerComps

# The common tail of every re-rating WARNING (both methods) — a stable, unique
# detector so a test can count / exclude the re-rating warning without matching
# the always-on assumptions clause or any pre-existing method warning.
_WARN_TAIL = "multiple shift is warranted"


def _pc(
    *,
    median_forward_pe: float | None = None,
    forward_pe_sample_n: int = 0,
    median_pe: float | None = None,
    pe_sample_n: int = 0,
    target_forward_pe: float | None = None,
    target_pe: float | None = None,
    target_net_income: float | None = None,
    ticker: str = "ZZZ",
) -> PeerComps:
    """Minimal PeerComps knobbed for a single comps_pe sub-path.

    Only the fields the leaf reads on the exercised path are set; sample sizes
    default to ≥4 in the callers so neither the n<3 refusal nor the thin-sample
    downweight fires and the warnings list holds only the re-rating entry.
    """
    target = CompanyFinancials(
        ticker=ticker,
        name=ticker,
        revenue=50e9,
        market_cap=500e9,
        net_income=target_net_income,
        forward_pe=target_forward_pe,
        pe_ratio=target_pe,
    )
    peer = target.model_copy(update={"ticker": "PEER1"})
    pc = PeerComps(target=target, peers=[peer], median_pe=median_pe)
    pc.median_forward_pe = median_forward_pe
    pc.forward_pe_sample_n = forward_pe_sample_n
    pc.pe_sample_n = pe_sample_n
    return pc


class TestCompsPeReratingDisclosure:
    def test_forward_path_discloses_and_warns_on_large_re_rating(self) -> None:
        # peer forward median 31.9x, forward EPS 10.0 → mid 319; price 198 → self
        # forward P/E 19.8x; ratio 319/198 = 1.61 (> 0.25 from parity → warns).
        # This is the MSFT case the external reviews named.
        pc = _pc(median_forward_pe=31.9, forward_pe_sample_n=5, target_forward_pe=19.8)
        warnings: list[str] = []
        m = _comps_pe_method(pc, 10.0, 2.4e9, warnings, current_price=198.0)
        assert m is not None
        assert m.mid == pytest.approx(31.9 * 10.0)  # the number itself is unchanged
        assert m.assumptions is not None
        assert "implied re-rating 19.8× → 31.9× forward P/E (1.61×)" in m.assumptions
        rr = [w for w in warnings if _WARN_TAIL in w]
        assert len(rr) == 1
        assert "expand from 19.8× to 31.9×" in rr[0]

    def test_small_gap_discloses_in_assumptions_without_warning(self) -> None:
        # peer 21.0x, EPS 10 → mid 210; price 200 → self 20.0x; ratio 1.05 (< 0.25
        # from parity) → always-on assumptions clause, but NO warning.
        pc = _pc(median_forward_pe=21.0, forward_pe_sample_n=5, target_forward_pe=20.0)
        warnings: list[str] = []
        m = _comps_pe_method(pc, 10.0, 2.4e9, warnings, current_price=200.0)
        assert m is not None
        assert m.assumptions is not None
        assert "implied re-rating 20.0× → 21.0× forward P/E (1.05×)" in m.assumptions
        assert not any(_WARN_TAIL in w for w in warnings)

    def test_no_price_discloses_nothing_and_changes_no_number(self) -> None:
        # current_price=None must leave every output number byte-equal to the priced
        # run and emit no disclosure — locks "pure transparency, zero behavior change".
        pc = _pc(median_forward_pe=31.9, forward_pe_sample_n=5, target_forward_pe=19.8)
        priced_w: list[str] = []
        noprice_w: list[str] = []
        priced = _comps_pe_method(pc, 10.0, 2.4e9, priced_w, current_price=198.0)
        noprice = _comps_pe_method(pc, 10.0, 2.4e9, noprice_w, current_price=None)
        assert priced is not None and noprice is not None
        assert (noprice.low, noprice.mid, noprice.high, noprice.confidence) == (
            priced.low,
            priced.mid,
            priced.high,
            priced.confidence,
        )
        assert "re-rating" not in (noprice.assumptions or "")
        assert not any(_WARN_TAIL in w for w in noprice_w)
        # sanity: the fixture IS a disclosing path when a price is present
        assert "re-rating" in (priced.assumptions or "")

    def test_mixed_caliber_fallback_is_not_disclosed(self) -> None:
        # median_forward_pe absent → the leaf applies a TRAILING peer median (25.0x)
        # to a FORWARD EPS. Comparing that anchor to a self forward P/E would mix
        # calibers, so NO re-rating disclosure is emitted even with a price. (This is
        # also why test_comps_pe_row_carries_caliber_assumption keeps passing.)
        pc = _pc(median_pe=25.0, pe_sample_n=5, target_pe=20.0)
        warnings: list[str] = []
        m = _comps_pe_method(pc, 10.0, 2.4e9, warnings, current_price=150.0)
        assert m is not None
        assert m.mid == pytest.approx(25.0 * 10.0)  # sub-path fired (median_pe × forward EPS)
        assert (
            m.assumptions
            == "anchored to peer median P/E 25.0× × forward EPS (as-reported peer P/E)"
        )
        assert not any(_WARN_TAIL in w for w in warnings)

    def test_trailing_path_discloses_and_is_symmetric_on_de_rating(self) -> None:
        # Trailing path (no forward EPS): peer trailing median 20.0x, trailing EPS
        # 25e9/2.5e9 = 10 → mid 200; price 400 → self 40.0x; ratio 200/400 = 0.50 →
        # a de-rating, disclosed with the symmetric "compress" verb.
        pc = _pc(median_pe=20.0, pe_sample_n=5, target_pe=40.0, target_net_income=25e9)
        warnings: list[str] = []
        m = _comps_pe_method(pc, None, 2.5e9, warnings, current_price=400.0)
        assert m is not None
        assert m.mid == pytest.approx(200.0)
        assert m.assumptions is not None
        assert "implied re-rating 40.0× → 20.0× P/E (0.50×)" in m.assumptions
        rr = [w for w in warnings if _WARN_TAIL in w]
        assert len(rr) == 1
        assert "compress from 40.0× to 20.0×" in rr[0]


class TestEvEbitdaReratingDisclosure:
    def test_discloses_and_warns_on_large_re_rating(self) -> None:
        # band (25,35) → mid multiple 30.0x; forward EBITDA 10e9, shares 1e9, net
        # debt 0; price 200 → current EV 200e9 → current implied 20.0x; ratio 1.50.
        warnings: list[str] = []
        m = _ev_ebitda_method(10e9, (25.0, 35.0), 1e9, 0.0, warnings=warnings, current_price=200.0)
        assert m is not None
        assert m.mid == pytest.approx(300.0)  # (250 + 350) / 2 — the price band is unchanged
        assert m.assumptions is not None
        assert (
            "implied re-rating: price-implied EV/TTM-EBITDA 20.0× → own 5y trailing band mid 30.0× (1.50×)"
            in m.assumptions
        )
        rr = [w for w in warnings if _WARN_TAIL in w]
        assert len(rr) == 1
        assert "expand from 20.0× to the trailing band mid 30.0×" in rr[0]

    def test_small_gap_discloses_in_assumptions_without_warning(self) -> None:
        # price 280 → current implied 28.0x vs band mid 30.0x; ratio 1.07 (< 0.25).
        warnings: list[str] = []
        m = _ev_ebitda_method(10e9, (25.0, 35.0), 1e9, 0.0, warnings=warnings, current_price=280.0)
        assert m is not None
        assert m.assumptions is not None
        assert (
            "price-implied EV/TTM-EBITDA 28.0× → own 5y trailing band mid 30.0× (1.07×)"
            in m.assumptions
        )
        assert not any(_WARN_TAIL in w for w in warnings)

    def test_symmetric_on_de_rating(self) -> None:
        # band (18,24) → mid 21.0x; price 300 → current implied 30.0x; ratio 0.70 →
        # compress (a de-rating: today's multiple is above the historical band).
        warnings: list[str] = []
        m = _ev_ebitda_method(10e9, (18.0, 24.0), 1e9, 0.0, warnings=warnings, current_price=300.0)
        assert m is not None
        assert m.assumptions is not None
        assert (
            "implied re-rating: price-implied EV/TTM-EBITDA 30.0× → own 5y trailing band mid 21.0× (0.70×)"
            in m.assumptions
        )
        rr = [w for w in warnings if _WARN_TAIL in w]
        assert len(rr) == 1
        assert "compress from 30.0× to the trailing band mid 21.0×" in rr[0]

    def test_no_price_discloses_nothing_and_changes_no_number(self) -> None:
        priced_w: list[str] = []
        noprice_w: list[str] = []
        priced = _ev_ebitda_method(
            10e9, (25.0, 35.0), 1e9, 0.0, warnings=priced_w, current_price=200.0
        )
        noprice = _ev_ebitda_method(
            10e9, (25.0, 35.0), 1e9, 0.0, warnings=noprice_w, current_price=None
        )
        assert priced is not None and noprice is not None
        assert (noprice.low, noprice.mid, noprice.high, noprice.confidence) == (
            priced.low,
            priced.mid,
            priced.high,
            priced.confidence,
        )
        assert noprice.assumptions is None  # ev_ebitda carried no assumptions before this slice
        assert not any(_WARN_TAIL in w for w in noprice_w)
        assert priced.assumptions is not None and "re-rating" in priced.assumptions


def test_rerating_disclosure_strings_have_no_dollar_or_ticker() -> None:
    """Every re-rating string that can reach ``price_target_basis`` prose must be
    scrubber-safe: no naked ``$`` (washed to "[target withheld]" on the withheld
    path) and no ticker baked in (a hardcoded ticker contaminates every OTHER
    report). Mirrors test_cyclical_suppression_reason_has_no_dollar_example_or_
    foreign_ticker for the disclosure family.
    """
    c_warn: list[str] = []
    cm = _comps_pe_method(
        _pc(median_forward_pe=31.9, forward_pe_sample_n=5, target_forward_pe=19.8, ticker="MU"),
        10.0,
        2.4e9,
        c_warn,
        current_price=198.0,
    )
    e_warn: list[str] = []
    em = _ev_ebitda_method(10e9, (25.0, 35.0), 1e9, 0.0, warnings=e_warn, current_price=200.0)
    assert cm is not None and cm.assumptions is not None
    assert em is not None and em.assumptions is not None
    strings = [cm.assumptions, em.assumptions, *c_warn, *e_warn]
    assert c_warn and e_warn  # both large-gap runs DID warn (else the check is vacuous)
    for s in strings:
        assert "$" not in s, f"naked $ surfaces into scrubber-scrubbed prose: {s}"
        assert "MU" not in s, f"ticker leaks into a per-report disclosure string: {s}"


class TestStructuredReratingRatio:
    """P0-1.2 companion: the SAME code that builds the prose disclosure must set
    the structured ``rerating_ratio`` (the confidence dial GRADES on it — no prose
    parsing), and must leave it None exactly where the prose is omitted (mixed
    caliber / no price). Prose and structure may never disagree."""

    def test_comps_pe_forward_path_sets_structured_ratio(self) -> None:
        pc = _pc(median_forward_pe=31.9, forward_pe_sample_n=5, target_forward_pe=19.8)
        m = _comps_pe_method(pc, 10.0, 2.4e9, [], current_price=198.0)
        assert m is not None
        assert m.rerating_ratio == pytest.approx(319.0 / 198.0)
        assert "(1.61×)" in (m.assumptions or "")  # prose twin agrees

    def test_comps_pe_mixed_caliber_and_no_price_leave_ratio_none(self) -> None:
        mixed = _comps_pe_method(
            _pc(median_pe=25.0, pe_sample_n=5, target_pe=20.0),
            10.0,
            2.4e9,
            [],
            current_price=150.0,
        )
        assert mixed is not None and mixed.rerating_ratio is None
        noprice = _comps_pe_method(
            _pc(median_forward_pe=31.9, forward_pe_sample_n=5, target_forward_pe=19.8),
            10.0,
            2.4e9,
            [],
            current_price=None,
        )
        assert noprice is not None and noprice.rerating_ratio is None

    def test_ev_ebitda_sets_structured_ratio_and_none_without_price(self) -> None:
        # current EV = 100×1e9 + 5e9 = 105e9 → price-implied 10.5×; band mid 15.0×
        # → ratio 1.4286.
        priced = _ev_ebitda_method(10e9, (12.0, 18.0), 1e9, 5e9, warnings=[], current_price=100.0)
        assert priced is not None
        assert priced.rerating_ratio == pytest.approx(15.0 / 10.5)
        noprice = _ev_ebitda_method(10e9, (12.0, 18.0), 1e9, 5e9, warnings=[], current_price=None)
        assert noprice is not None and noprice.rerating_ratio is None


class TestEvEbitdaSingleCaliberContract:
    """batch2 lock: the ev_ebitda row is now SINGLE-CALIBER — its band (own 5y trailing
    EV/EBITDA multiples) multiplies the target's CURRENT TTM operating EBITDA
    (income.ebitda = OI + D&A), NOT the FMP forward consensus. A trailing band on a
    forward denominator hid an upward bias (forward EBITDA > trailing ⇒ a higher target);
    these pins RED if anyone re-wires the denominator back to forward — the口径 label /
    prose would drift back to "forward" and the caliber gap would return.
    """

    def test_denominator_is_the_value_passed_first_no_forward_rescale(self) -> None:
        # Structural: mid = ((p25+p75)/2 × denom − net_debt) / shares with denom = the
        # first positional arg (now the TTM EBITDA the caller passes), no forward re-scale.
        ttm, shares, nd = 20e9, 2e9, 4e9
        m = _ev_ebitda_method(ttm, (10.0, 14.0), shares, nd, warnings=[], current_price=None)
        assert m is not None
        assert m.low == pytest.approx((10.0 * ttm - nd) / shares)
        assert m.high == pytest.approx((14.0 * ttm - nd) / shares)

    def test_source_and_prose_pin_ttm_caliber_never_forward(self) -> None:
        warnings: list[str] = []
        m = _ev_ebitda_method(
            10e9,
            (25.0, 35.0),
            1e9,
            0.0,
            band_sample_n=500,
            warnings=warnings,
            current_price=200.0,
        )
        assert m is not None
        # 口径 label pins the TTM denominator, never "forward".
        assert "ttm_ebitda" in m.source
        assert "forward" not in m.source.lower()
        # Re-rating prose compares two SAME-caliber multiples (both trailing/TTM).
        assert m.assumptions is not None and "EV/TTM-EBITDA" in m.assumptions
        assert "forward" not in m.assumptions.lower()
        # Method self-description: TTM operating EBITDA + explicit no-growth-credit bias
        # disclosure (condition ii), and no stale "forward EBITDA" caliber label.
        joined = " ".join(m.warnings)
        assert "TTM operating EBITDA" in joined
        assert "forward-growth credit" in joined
        assert "forward EBITDA" not in joined
        # The large-gap re-rating WARNING no longer carries the old caliber tail
        # ("a trailing-year band applied to forward EBITDA") — same caliber now.
        rr = [w for w in warnings if _WARN_TAIL in w]
        assert len(rr) == 1 and "forward" not in rr[0].lower()
