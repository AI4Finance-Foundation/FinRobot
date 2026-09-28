"""Tests for the momentum-vs-verdict narrative backstop (BACKLOG A2/P1-1).

Pure, deterministic — no LLM involved. Pins:
  - is_momentum_divergent's BUY<-15% / SELL>+30% thresholds (and their None-safety).
  - audit_momentum_narrative_hedge's warning-vs-silent behavior (never gates the
    verdict/target/confidence — only flags a missing hedge paragraph).
  - compute_momentum_context's derivation of the three momentum reads from a
    FinancialData snapshot (currency-invariant ratios, graceful None-degrade).
"""

from __future__ import annotations

from datetime import datetime, timezone

from finrobot.engine.compute.operators.audit.narrative_divergence import (
    BUY_DIVERGENCE_1Y_RETURN_PCT,
    SELL_DIVERGENCE_1Y_RETURN_PCT,
    audit_momentum_narrative_hedge,
    compute_momentum_context,
    is_momentum_divergent,
)
from finrobot.engine.models.financial import FinancialData, IncomeStatement, MarketData


def _financial_data(
    *,
    current_price: float,
    high_52w: float | None = None,
    low_52w: float | None = None,
    trailing_1y_return_pct: float | None = None,
) -> FinancialData:
    return FinancialData(
        ticker="TEST",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        income=IncomeStatement(revenue=1.0),
        market=MarketData(
            market_cap=1.0,
            shares_outstanding=1.0,
            current_price=current_price,
            price_52w_high=high_52w,
            price_52w_low=low_52w,
            trailing_1y_return_pct=trailing_1y_return_pct,
        ),
    )


class TestIsMomentumDivergent:
    def test_buy_below_threshold_is_divergent(self) -> None:
        assert is_momentum_divergent("BUY", -20.0) is True

    def test_buy_at_threshold_is_not_divergent(self) -> None:
        # Strict "<", not "<=" — the threshold itself is not yet divergent.
        assert is_momentum_divergent("BUY", BUY_DIVERGENCE_1Y_RETURN_PCT) is False

    def test_buy_mild_pullback_is_not_divergent(self) -> None:
        assert is_momentum_divergent("BUY", -5.0) is False

    def test_buy_positive_return_is_not_divergent(self) -> None:
        assert is_momentum_divergent("BUY", 5.0) is False

    def test_sell_above_threshold_is_divergent(self) -> None:
        assert is_momentum_divergent("SELL", 45.0) is True

    def test_sell_at_threshold_is_not_divergent(self) -> None:
        assert is_momentum_divergent("SELL", SELL_DIVERGENCE_1Y_RETURN_PCT) is False

    def test_sell_mild_rally_is_not_divergent(self) -> None:
        assert is_momentum_divergent("SELL", 10.0) is False

    def test_hold_never_divergent(self) -> None:
        # HOLD has no directional call to defend against momentum.
        assert is_momentum_divergent("HOLD", -50.0) is False
        assert is_momentum_divergent("HOLD", 90.0) is False

    def test_case_insensitive_and_whitespace_tolerant(self) -> None:
        assert is_momentum_divergent(" buy ", -20.0) is True
        assert is_momentum_divergent("sell", 45.0) is True

    def test_none_verdict_never_fabricates_divergence(self) -> None:
        assert is_momentum_divergent(None, -50.0) is False

    def test_none_return_never_fabricates_divergence(self) -> None:
        # No price history → nothing to compare the verdict against; 绝不编数字.
        assert is_momentum_divergent("BUY", None) is False
        assert is_momentum_divergent("SELL", None) is False


class TestAuditMomentumNarrativeHedge:
    def test_buy_strong_pullback_no_hedge_note_warns(self) -> None:
        warning = audit_momentum_narrative_hedge("BUY", -20.0, None)
        assert warning is not None
        assert "[NARRATIVE-MOMENTUM]" in warning
        assert "BUY" in warning
        assert "20.0%" in warning

    def test_buy_strong_pullback_with_hedge_note_is_silent(self) -> None:
        warning = audit_momentum_narrative_hedge(
            "BUY",
            -20.0,
            "The market is pricing in a demand air-pocket; we see a temporary "
            "inventory correction, not a structural decline.",
        )
        assert warning is None

    def test_buy_mild_pullback_not_divergent_is_silent_even_without_note(self) -> None:
        # +5% / -5% is ordinary — no hedge paragraph required, so no warning either.
        warning = audit_momentum_narrative_hedge("BUY", 5.0, None)
        assert warning is None

    def test_sell_strong_rally_no_hedge_note_warns(self) -> None:
        warning = audit_momentum_narrative_hedge("SELL", 45.0, None)
        assert warning is not None
        assert "SELL" in warning
        assert "45.0%" in warning

    def test_sell_strong_rally_with_hedge_note_is_silent(self) -> None:
        warning = audit_momentum_narrative_hedge(
            "SELL", 45.0, "The rally is pricing in multiple expansion we view as unsustainable."
        )
        assert warning is None

    def test_whitespace_only_hedge_note_still_warns(self) -> None:
        # An LLM emitting an empty-ish string must not count as "cooperated".
        warning = audit_momentum_narrative_hedge("BUY", -20.0, "   ")
        assert warning is not None

    def test_never_gates_hold(self) -> None:
        assert audit_momentum_narrative_hedge("HOLD", -80.0, None) is None

    def test_none_verdict_or_return_never_warns(self) -> None:
        assert audit_momentum_narrative_hedge(None, -20.0, None) is None
        assert audit_momentum_narrative_hedge("BUY", None, None) is None


class TestComputeMomentumContext:
    def test_all_three_reads_derived_from_financial_data(self) -> None:
        fd = _financial_data(
            current_price=80.0, high_52w=120.0, low_52w=70.0, trailing_1y_return_pct=-20.5
        )
        ctx = compute_momentum_context(fd)
        assert ctx.one_year_return_pct == -20.5
        # (80 - 70) / (120 - 70) = 0.20
        assert ctx.range_position_52w is not None
        assert abs(ctx.range_position_52w - 0.20) < 1e-9
        # (80 - 120) / 120 * 100 = -33.33...
        assert ctx.drawdown_from_52w_high_pct is not None
        assert abs(ctx.drawdown_from_52w_high_pct - (-33.333333)) < 1e-3

    def test_none_financial_data_degrades_to_all_none(self) -> None:
        ctx = compute_momentum_context(None)
        assert ctx.one_year_return_pct is None
        assert ctx.range_position_52w is None
        assert ctx.drawdown_from_52w_high_pct is None

    def test_missing_52w_bounds_degrades_range_and_drawdown_only(self) -> None:
        fd = _financial_data(current_price=80.0, trailing_1y_return_pct=-10.0)
        ctx = compute_momentum_context(fd)
        assert ctx.one_year_return_pct == -10.0
        assert ctx.range_position_52w is None
        assert ctx.drawdown_from_52w_high_pct is None

    def test_degenerate_zero_width_range_degrades_to_none(self) -> None:
        # high == low: a zero-width 52w range never fabricates a position.
        fd = _financial_data(current_price=100.0, high_52w=100.0, low_52w=100.0)
        ctx = compute_momentum_context(fd)
        assert ctx.range_position_52w is None
