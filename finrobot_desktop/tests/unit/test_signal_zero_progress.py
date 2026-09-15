"""Rule 1 must not score zero price movement as a hit (W3-B路 · direction guard).

The W2-F2 fix added a ``actual_move >= 0`` direction guard, but ``>= 0`` still
admits ``actual_move == 0`` — current_price == entry_price, i.e. the position has
produced ZERO P&L. Combined with a small-expected-move thesis (entry already
within 10% of target), that scored a no-move position as a confirmed "hit",
inflating the hit-rate. Rule 2 already uses a strict ``>``; Rule 1's direction
guard must match (strict ``> 0``) — a hit requires actual movement toward target.
"""

from __future__ import annotations

from datetime import datetime, timezone

from finrobot.engine.compute.operators.signal import compute_signal

UTC = timezone.utc
ENTRY = datetime(2026, 1, 1, tzinfo=UTC)


def test_zero_progress_in_band_is_not_hit() -> None:
    # entry=100, target=105 (entry already 4.76% from target); current=100 == entry
    # → actual_move = 0 (no P&L). |100-105|/105 = 4.76% sits inside the ±10% band,
    # but with zero movement it must NOT be a hit.
    verdict = compute_signal(
        target_price=105,
        entry_price=100,
        current_price=100,
        entry_date=ENTRY,
        now=ENTRY.replace(day=4),  # within the 7-day grace window
    )
    assert verdict != "hit"
    assert verdict == "watching"
