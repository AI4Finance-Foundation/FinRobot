"""compute_signal must reject non-finite prices (W3-B路 · input validation).

The sign guards check ``entry_price <= 0`` / ``target_price <= 0`` and the
entry==target degeneracy, but NaN/Inf pass all of them (NaN/Inf comparisons are
False, +Inf > 0 is True), and current_price was not validated at all. A
non-finite price then produces NaN actual_move / expected_move and a meaningless
verdict. Reject it explicitly rather than emit a confident-looking classification
from garbage.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from finrobot.engine.compute.operators.signal import compute_signal

UTC = timezone.utc
ENTRY = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    "override",
    [
        {"entry_price": float("nan")},
        {"target_price": float("inf")},
        {"current_price": float("nan")},
        {"current_price": float("inf")},
    ],
)
def test_compute_signal_rejects_nonfinite_prices(override: dict[str, float]) -> None:
    base = dict(
        target_price=110.0,
        entry_price=100.0,
        current_price=105.0,
        entry_date=ENTRY,
        now=ENTRY.replace(day=4),
    )
    base.update(override)
    with pytest.raises(ValueError):
        compute_signal(**base)  # type: ignore[arg-type]
