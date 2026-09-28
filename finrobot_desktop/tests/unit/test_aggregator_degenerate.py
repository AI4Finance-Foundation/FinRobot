"""EV/EBITDA football-field method must drop, not fabricate, when debt > EV
(W3-B路 · degenerate-state).

A deeply-levered firm whose current net debt exceeds the implied enterprise
value across the WHOLE p25–p75 band has negative implied equity at both ends.
The method floored ``low`` to $0.01 and set ``high = max(low, raw_high)``, so it
emitted a fabricated ``[0.01, 0.01]`` range that entered the football field as a
real valuation method — the sibling LBO grid already drops such degenerate cells
(asymmetric guard). The honest behaviour is to drop the row (return None) when
even the optimistic p75 multiple cannot cover the debt, while still keeping a
band that only goes underwater at the pessimistic p25 end.
"""

from __future__ import annotations

import pytest

from finrobot.engine.compute.operators.valuation_aggregator import _ev_ebitda_method


def test_ev_ebitda_method_drops_when_debt_exceeds_whole_band() -> None:
    # net_debt 100B > p75·ebitda 80B → implied equity negative at both ends.
    assert _ev_ebitda_method(10e9, (5.0, 8.0), 1e9, 100e9) is None


def test_ev_ebitda_method_keeps_band_underwater_only_at_p25() -> None:
    # net_debt 60B: underwater at p25 (50B) but covered at p75 (80B) → keep,
    # floor the low end to ~0 (near-wipeout) but expose the real p75 upside.
    r = _ev_ebitda_method(10e9, (5.0, 8.0), 1e9, 60e9)
    assert r is not None
    assert r.high == pytest.approx(20.0)
    assert r.low >= 0.01


def test_ev_ebitda_method_healthy_firm_unchanged() -> None:
    # net_debt 10B → both ends comfortably positive; ordinary range.
    r = _ev_ebitda_method(10e9, (5.0, 8.0), 1e9, 10e9)
    assert r is not None
    assert r.low == pytest.approx(40.0)
    assert r.high == pytest.approx(70.0)
