"""Earnings-surprise aggregates must be finite (W3-B路 · finiteness).

``_coerce_positive_float`` gated ``f > 0``: that correctly drops NaN and -Inf
but **+Inf passes** (`inf > 0` is True), so a corrupt estimate leaks +Inf into
avg_eps_surprise_pct / avg_revenue_surprise_pct. ``_surprise_pct`` guarded
None / zero-estimate but not a non-finite actual/estimated, so an Inf actual
yields an Inf surprise. Either way the analyst sees an Inf% surprise — a
multiple/aggregate must be a real number or None.
"""

from __future__ import annotations

import pytest

from finrobot.engine.compute.operators.earnings import _surprise_pct
from finrobot.engine.compute.operators.forward_estimates import _coerce_positive_float


@pytest.mark.parametrize("bad", [float("inf"), float("nan"), float("-inf")])
def test_coerce_positive_float_rejects_nonfinite(bad: float) -> None:
    assert _coerce_positive_float(bad) is None


def test_coerce_positive_float_keeps_normal_positive() -> None:
    assert _coerce_positive_float(12.5) == 12.5


@pytest.mark.parametrize(
    "actual,est",
    [
        (float("inf"), 1.0),
        (float("nan"), 1.0),
        (float("-inf"), 1.0),
        (1.0, float("inf")),
        (1.0, float("nan")),
    ],
)
def test_surprise_pct_rejects_nonfinite(actual: float, est: float) -> None:
    assert _surprise_pct(actual, est) is None


def test_surprise_pct_normal() -> None:
    # actual 1.10 vs estimate 1.00 → +10% surprise.
    assert _surprise_pct(1.10, 1.00) == pytest.approx(10.0)
