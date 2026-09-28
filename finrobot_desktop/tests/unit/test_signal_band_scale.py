"""Rule 1's hit band must scale with the EXPECTED MOVE, not the absolute price
level (W3-B路 · direction symmetry).

Rule 1 measured proximity as ``|current − target| / target_price``. That makes
the ±10% band a fraction of the absolute price, so:

1. A small-move / high-price thesis over-credits: entry 1000 → target 1010
   (a $10 move); current 1004 has moved only 40% of the way, yet sits 0.6% from
   the $1010 target and was scored a confirmed "hit".
2. A LONG thesis and its mirror SHORT get different dollar bands (±10% of a high
   target vs ±10% of a low target), so mirrored prices can disagree.

Rule 2 already normalises by ``expected_move``; Rule 1 must too — then the band
is "within 10% of the move distance from target", scale-free and LONG/SHORT
symmetric.
"""

from __future__ import annotations

from datetime import datetime, timezone

from finrobot.engine.compute.operators.signal import compute_signal

UTC = timezone.utc
ENTRY = datetime(2026, 1, 1, tzinfo=UTC)


def test_small_move_high_price_not_over_credited() -> None:
    # entry=1000, target=1010 (expected_move=10). current=1004 has moved 4 = 40%
    # of the move — NOT a hit (Rule 2's 50% threshold not met) — but it sits 0.6%
    # from the absolute target. The old target_price denominator scored it "hit".
    verdict = compute_signal(
        target_price=1010,
        entry_price=1000,
        current_price=1004,
        entry_date=ENTRY,
        now=ENTRY.replace(day=4),
    )
    assert verdict != "hit"
    assert verdict == "watching"


def test_long_short_mirror_symmetric_at_band_edge() -> None:
    # LONG entry100/target110 and mirror SHORT entry100/target90, both at a price
    # exactly 10% of the move (1.0) past the target → identical verdict.
    long_v = compute_signal(
        target_price=110,
        entry_price=100,
        current_price=111,
        entry_date=ENTRY,
        now=ENTRY.replace(day=4),
    )
    short_v = compute_signal(
        target_price=90,
        entry_price=100,
        current_price=89,
        entry_date=ENTRY,
        now=ENTRY.replace(day=4),
    )
    assert long_v == short_v


def test_reaching_target_still_hits() -> None:
    # Regression: actually reaching the target (within 10% of the move) is a hit.
    verdict = compute_signal(
        target_price=110,
        entry_price=100,
        current_price=109.5,
        entry_date=ENTRY,
        now=ENTRY.replace(day=4),
    )
    assert verdict == "hit"
