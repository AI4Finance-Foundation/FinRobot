"""Multiples must be finite-or-None (W3-B路 · operator finiteness).

The sanity / FCF / peer-statistics paths all guarded None and magnitude but not
finiteness: `NaN < lo` and `NaN > hi` are both False, so the garbage gate that
exists to keep junk multiples out of the comps medians let the worst junk
(NaN / ±Inf) straight through — and one NaN peer poisons the whole median that
feeds the comps_pe valuation. A multiple shown to an analyst must be a real
number or explicitly None, never NaN/Inf.
"""

from __future__ import annotations

import math

import pytest

from finrobot.engine.compute.operators.multiples import (
    _sanity,
    calculate_peer_statistics,
    compute_ttm_fcf,
    fcf_yield,
)
from finrobot.engine.models.financial import CompanyFinancials, PeerComps


def _company(ticker: str, **kw: float) -> CompanyFinancials:
    base = dict(
        ticker=ticker,
        revenue=100e9,
        ebitda=35e9,
        net_income=12e9,
        market_cap=550e9,
        total_debt=0.0,
        total_cash=0.0,
        gross_margin=0.4,
        operating_margin=0.2,
    )
    base.update(kw)
    return CompanyFinancials(**base)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_sanity_rejects_nonfinite(bad: float) -> None:
    # The garbage gate must reject the worst garbage, not just out-of-band magnitudes.
    assert _sanity(bad, 0.5, 300.0) is None


@pytest.mark.parametrize(
    "ocf,capex",
    [
        (float("nan"), 10.0),
        (float("inf"), 10.0),
        (100.0, float("nan")),
        (float("inf"), float("inf")),
    ],
)
def test_compute_ttm_fcf_rejects_nonfinite(ocf: float, capex: float) -> None:
    assert compute_ttm_fcf(ocf, capex) is None


@pytest.mark.parametrize(
    "fcf,mc",
    [(float("nan"), 1e9), (float("inf"), 1e9), (100.0, float("nan")), (100.0, float("inf"))],
)
def test_fcf_yield_rejects_nonfinite(fcf: float, mc: float) -> None:
    assert fcf_yield(fcf, mc) is None


def test_peer_statistics_excludes_nonfinite_ev_ebitda() -> None:
    good1 = _company("A")
    good1.ev_ebitda = 10.0
    good2 = _company("B")
    good2.ev_ebitda = 20.0
    poison = _company("C")
    poison.ev_ebitda = float("nan")  # one bad peer must not poison the median
    result = calculate_peer_statistics(
        PeerComps(target=_company("T"), peers=[good1, good2, poison])
    )
    assert result.median_ev_ebitda is not None
    assert math.isfinite(result.median_ev_ebitda)
    assert result.median_ev_ebitda == pytest.approx(15.0)  # median of [10, 20], NaN dropped
