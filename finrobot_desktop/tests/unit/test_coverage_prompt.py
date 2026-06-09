"""coverage/prompt.py — the per-turn watchlist snapshot block.

The snapshot is *data* the chat assistant is given every turn. The behavioural
policy for what to DO with movers (surface them, but only in a conversational
reply — never woven into a single-ticker report body) lives in
``engine/instructions.md``, not here. So the snapshot must list movers as data
WITHOUT an unconditional "proactively call these out" command — that imperative
leaked watchlist names (TSLA/AMD) into an AAPL deep-dive report body.
"""

from __future__ import annotations

from datetime import datetime, timezone

from finrobot.coverage.models import CoverageOverview, CoverageRow
from finrobot.coverage.prompt import format_coverage_snapshot

UTC = timezone.utc


def _row(ticker: str, *, change: float | None = None, upside: float | None = None) -> CoverageRow:
    return CoverageRow(
        ticker=ticker,
        price=100.0,
        currency="USD",
        change_pct_1d=change,
        upside_to_target_live=upside,
    )


def _overview(rows: list[CoverageRow]) -> CoverageOverview:
    return CoverageOverview(
        group_id="cov_test",
        group_name="Studied Tickers",
        rows=rows,
        generated_at=datetime(2026, 6, 9, tzinfo=UTC),
    )


def test_movers_are_listed_as_data() -> None:
    out = format_coverage_snapshot(
        _overview([_row("TSLA", change=6.0), _row("AAPL", change=0.1)]),
        change_threshold=5.0,
    )
    assert out is not None
    assert "TSLA +6.0%" in out  # the mover datum is preserved
    assert "AAPL" in out  # non-mover still in the row listing


def test_snapshot_carries_no_unconditional_surface_command() -> None:
    """The leaking imperative must be gone — surfacing policy is scoped in instructions.md."""
    out = format_coverage_snapshot(
        _overview([_row("TSLA", change=6.0)]),
        change_threshold=5.0,
    )
    assert out is not None
    assert "proactively call these out" not in out
