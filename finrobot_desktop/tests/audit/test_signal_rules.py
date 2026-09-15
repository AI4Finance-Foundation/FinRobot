"""Audit tests for the signal verdict / hit-rate rules (v5 ADR-0001 / §7.1 / §7.3).

These tests pin down the boundaries so future refactors can't silently shift
hit/watching/failed semantics. They also enforce the leaf-layer invariants
that keep signal.py free of LLM / upper-layer dependencies.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from finrobot.engine.compute.operators.signal import (
    ClosedReturn,
    Signal,
    compute_hit_rate,
    compute_signal,
)

UTC = timezone.utc
ENTRY = datetime(2026, 1, 1, tzinfo=UTC)


def _at(days: int) -> datetime:
    return ENTRY + timedelta(days=days)


# ---------------------------------------------------------------------------
# Verdict rules — 8 boundary cases from ADR-0001 §3.1
# ---------------------------------------------------------------------------


class TestSignalVerdict:
    """compute_signal must classify these boundary scenarios deterministically."""

    def test_hit_in_band_within_ten_percent(self) -> None:
        # current=115 vs target=120 → |5|/120 = 4.2% (≤10%)
        assert (
            compute_signal(
                target_price=120,
                entry_price=100,
                current_price=115,
                entry_date=ENTRY,
                now=_at(30),
            )
            == "hit"
        )

    def test_band_hit_requires_moving_toward_target_bullish(self) -> None:
        # W2-F2 (probe 2026-06-09): BUY entry100/target105, current95 is a -5% LOSS
        # that moved AWAY from target, yet |95-105|/105 = 9.5% sits inside the band.
        # Rule 1 must NOT score it "hit" — that inflated the dashboard hit-rate. The
        # band requires moving toward the target (direction guard, like Rule 2).
        assert (
            compute_signal(
                target_price=105,
                entry_price=100,
                current_price=95,
                entry_date=ENTRY,
                now=_at(3),
            )
            == "watching"
        )

    def test_band_hit_requires_moving_toward_target_bearish(self) -> None:
        # SELL/short: target95<entry100. current104 is a loss (price rose) but
        # |104-95|/95 = 9.5% is inside the band — must not be a hit (wrong direction).
        assert (
            compute_signal(
                target_price=95,
                entry_price=100,
                current_price=104,
                entry_date=ENTRY,
                now=_at(3),
            )
            != "hit"
        )

    def test_band_hit_still_fires_when_moving_toward_target(self) -> None:
        # Regression: a real move toward the target inside the band is still a hit
        # (bullish current104→target105, and bearish current96→target95).
        assert (
            compute_signal(
                target_price=105, entry_price=100, current_price=104, entry_date=ENTRY, now=_at(3)
            )
            == "hit"
        )
        assert (
            compute_signal(
                target_price=95, entry_price=100, current_price=96, entry_date=ENTRY, now=_at(3)
            )
            == "hit"
        )

    def test_hit_when_progress_exceeds_half_expected_move(self) -> None:
        # expected_move = 20, actual_move = 12 → 60% > 50%
        assert (
            compute_signal(
                target_price=120,
                entry_price=100,
                current_price=112,
                entry_date=ENTRY,
                now=_at(30),
            )
            == "hit"
        )

    def test_watching_during_first_seven_days_even_if_reversed(self) -> None:
        # Reversed -20% but still inside 7-day grace → watching, not failed
        assert (
            compute_signal(
                target_price=120,
                entry_price=100,
                current_price=80,
                entry_date=ENTRY,
                now=_at(3),
            )
            == "watching"
        )

    def test_watching_when_progress_below_half(self) -> None:
        # actual_move=5 vs expected=20 → 25% — not enough for rule 2
        assert (
            compute_signal(
                target_price=120,
                entry_price=100,
                current_price=105,
                entry_date=ENTRY,
                now=_at(30),
            )
            == "watching"
        )

    def test_failed_when_reversed_past_ten_percent_after_grace(self) -> None:
        # actual_move = -12 (>10% of entry_price 100), 30 days later
        assert (
            compute_signal(
                target_price=120,
                entry_price=100,
                current_price=88,
                entry_date=ENTRY,
                now=_at(30),
            )
            == "failed"
        )

    def test_failed_when_past_target_date_without_hit(self) -> None:
        # Up only 5%, never broke into band/progress hit rules, past the deadline
        assert (
            compute_signal(
                target_price=120,
                entry_price=100,
                current_price=105,
                entry_date=ENTRY,
                target_date=_at(365),
                now=_at(400),
            )
            == "failed"
        )

    def test_target_equal_to_entry_raises(self) -> None:
        # A thesis with no directional view is meaningless — refuse to compute.
        with pytest.raises(ValueError, match="thesis must have a directional view"):
            compute_signal(
                target_price=100,
                entry_price=100,
                current_price=100,
                entry_date=ENTRY,
                now=_at(30),
            )

    def test_bearish_target_hit_when_price_drops_into_band(self) -> None:
        # entry=100 → target=80 (short thesis); current=82 is within ±10% of 80.
        assert (
            compute_signal(
                target_price=80,
                entry_price=100,
                current_price=82,
                entry_date=ENTRY,
                now=_at(30),
            )
            == "hit"
        )

    def test_bearish_target_progress_rule(self) -> None:
        # entry=100, target=80, current=88 → moved 12 out of 20 expected = 60%
        assert (
            compute_signal(
                target_price=80,
                entry_price=100,
                current_price=88,
                entry_date=ENTRY,
                now=_at(30),
            )
            == "hit"
        )

    def test_negative_entry_price_raises(self) -> None:
        with pytest.raises(ValueError, match="entry_price must be > 0"):
            compute_signal(
                target_price=120,
                entry_price=-1,
                current_price=80,
                entry_date=ENTRY,
                now=_at(30),
            )

    def test_naive_datetime_treated_as_utc(self) -> None:
        # JSON round-trip can drop tzinfo; verdict must still work.
        naive_entry = ENTRY.replace(tzinfo=None)
        naive_now = _at(30).replace(tzinfo=None)
        assert (
            compute_signal(
                target_price=120,
                entry_price=100,
                current_price=115,
                entry_date=naive_entry,
                now=naive_now,
            )
            == "hit"
        )


# ---------------------------------------------------------------------------
# Hit-rate aggregation — survivor-bias-corrected statistics (§7.3)
# ---------------------------------------------------------------------------


class TestHitRateStats:
    """compute_hit_rate must use the closed-sample denominator and include failed."""

    def test_basic_three_two_one_distribution(self) -> None:
        signals: list[Signal | None] = ["hit", "hit", "failed", "watching", "watching"]
        closed = [
            ClosedReturn(ticker_return=0.10, sp500_return=0.05),
            ClosedReturn(ticker_return=0.15, sp500_return=0.05),
            ClosedReturn(ticker_return=-0.12, sp500_return=0.03),
        ]
        stats = compute_hit_rate(signals=signals, closed_returns=closed)
        assert stats.n_total == 5
        assert stats.n_closed == 3
        assert stats.n_hit == 2
        assert stats.hit_rate == pytest.approx(2 / 3)
        # mean of (0.05, 0.10, -0.15) = 0.0
        assert stats.avg_excess_return == pytest.approx(0.0)

    def test_all_watching_returns_none_for_both_rates(self) -> None:
        stats = compute_hit_rate(signals=["watching", "watching", "watching"], closed_returns=[])
        assert stats.n_total == 3
        assert stats.n_closed == 0
        assert stats.n_hit == 0
        assert stats.hit_rate is None
        assert stats.avg_excess_return is None

    def test_failed_artifacts_count_in_excess_average(self) -> None:
        # If we accidentally averaged only hits, avg_excess would be +0.075 (mean(0.05, 0.10)).
        # Including the failed artifact pulls it down to 0.0 — survivor bias removed.
        signals: list[Signal | None] = ["hit", "hit", "failed"]
        closed = [
            ClosedReturn(ticker_return=0.10, sp500_return=0.05),
            ClosedReturn(ticker_return=0.15, sp500_return=0.05),
            ClosedReturn(ticker_return=-0.12, sp500_return=0.03),
        ]
        stats = compute_hit_rate(signals=signals, closed_returns=closed)
        assert stats.avg_excess_return == pytest.approx(0.0)

    def test_signals_with_none_dropped_from_total(self) -> None:
        signals: list[Signal | None] = [None, None, "hit", "failed"]
        closed = [
            ClosedReturn(ticker_return=0.10, sp500_return=0.05),
            ClosedReturn(ticker_return=-0.12, sp500_return=0.03),
        ]
        stats = compute_hit_rate(signals=signals, closed_returns=closed)
        assert stats.n_total == 2  # None entries are not "signaled"
        assert stats.n_closed == 2
        assert stats.n_hit == 1
        assert stats.hit_rate == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Red-line: signal.py is leaf-layer and LLM-free
# ---------------------------------------------------------------------------


SIGNAL_PATH = (
    Path(__file__).resolve().parents[2]
    / "finrobot"
    / "engine"
    / "compute"
    / "operators"
    / "signal.py"
)


class TestSignalModuleIsolation:
    """compute/signal.py must not leak upward or into LLM / artifact code."""

    def test_signal_module_has_no_forbidden_imports(self) -> None:
        src = SIGNAL_PATH.read_text()
        forbidden = (
            "from finrobot.engine.pipelines",
            "from finrobot.engine.agents",
            "from finrobot.engine.orchestrator",
            "import pydantic_ai",
            "from pydantic_ai",
            "import openai",
            "from openai",
            "import anthropic",
            "from anthropic",
            "import litellm",
            "from litellm",
            # signal.py must not depend on the artifact layer either — keep the
            # numeric core pure; route adapters bridge to ArtifactSummary.
            "from finrobot.artifact",
            "import finrobot.artifact",
        )
        violations = [
            pat for pat in forbidden if re.search(rf"^\s*{re.escape(pat)}", src, re.MULTILINE)
        ]
        assert not violations, f"signal.py leaks: {violations}"

    def test_signal_module_uses_only_stdlib_and_dataclass(self) -> None:
        # Sanity check: at most a handful of imports, none from finrobot.*.
        src = SIGNAL_PATH.read_text()
        finrobot_imports = re.findall(r"^\s*from\s+finrobot\.", src, re.MULTILINE)
        assert not finrobot_imports, (
            "signal.py imports finrobot.* — must remain a pure numeric leaf. "
            f"Found: {finrobot_imports}"
        )
