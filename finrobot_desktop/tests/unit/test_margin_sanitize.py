"""Tests for margin sanitization — withhold an economically-impossible gross/operating
margin (>100% ⟹ negative cost, or <-500% mixup) instead of crashing the IncomeStatement
bound or fabricating a 100% figure.

External caliber anchor (FMP live 2026-07-06): UL's TTM gross_margin = 100.14% because
FMP reports grossProfit ≈ revenue with quarterly costOfRevenue = 0, while the annual
filings show the real gross margin ≈ 42-47% (2023 = 42.24%). The real figure is
unrecoverable in the TTM path (no quarterly COGS), so the honest treatment is to
WITHHOLD (None → N/A), never clamp to a fabricated 100%.
"""

import pytest
from pydantic import ValidationError

from finrobot.engine.compute.coordinators.extractor import (
    _MARGIN_CEILING,
    _MARGIN_FLOOR,
    _sanitize_margin,
)
from finrobot.engine.models.financial import IncomeStatement


class TestSanitizeMarginBoundaries:
    def test_normal_margin_is_byte_identical(self):
        # AAPL ~47.9%, KO ~61.7% (live) pass through unchanged, no warning.
        for gm in (0.4786, 0.6174, 0.0, 0.999):
            warnings: list[str] = []
            assert _sanitize_margin(gm, label="gross_margin", warnings=warnings) == gm
            assert warnings == []

    def test_negative_loss_maker_within_band_is_kept(self):
        # RIVN-class: a below-cost seller reports a negative gross margin — legitimate,
        # kept (the -5 floor, not the ceiling, guards the downside).
        warnings: list[str] = []
        assert _sanitize_margin(-0.0172, label="gross_margin", warnings=warnings) == -0.0172
        assert _sanitize_margin(-1.5, label="operating_margin", warnings=warnings) == -1.5
        assert warnings == []

    def test_above_100pct_is_withheld_with_warning(self):
        # UL live: 100.14% → None (withheld), NOT clamped to a fabricated 100%.
        warnings: list[str] = []
        assert _sanitize_margin(1.0014, label="gross_margin", warnings=warnings) is None
        assert len(warnings) == 1
        assert "exceeds 100%" in warnings[0]
        assert "withheld" in warnings[0]

    def test_below_negative_500pct_is_withheld(self):
        # -50 (a -5000% percent/decimal mixup) → None.
        warnings: list[str] = []
        assert _sanitize_margin(-50.0, label="gross_margin", warnings=warnings) is None
        assert len(warnings) == 1

    def test_none_passes_through(self):
        assert _sanitize_margin(None, label="gross_margin") is None

    def test_exact_bounds_are_kept(self):
        # Exactly 100% (COGS == 0, borderline-plausible) and exactly -500% are inside
        # the credible band — kept, not withheld. Only STRICTLY beyond is withheld.
        assert _sanitize_margin(_MARGIN_CEILING, label="gross_margin") == _MARGIN_CEILING
        assert _sanitize_margin(_MARGIN_FLOOR, label="gross_margin") == _MARGIN_FLOOR

    def test_warning_channel_optional(self):
        # Peer path passes no warnings list — must still withhold silently, not raise.
        assert _sanitize_margin(1.5, label="gross_margin") is None


class TestIncomeStatementBound:
    def test_sanitized_none_constructs_cleanly(self):
        # The withheld (None) margin builds an IncomeStatement with no crash — the
        # regression that motivated this fix (UL 500'd the whole report).
        stmt = IncomeStatement(revenue=1.0e11, gross_margin=None, operating_margin=0.17)
        assert stmt.gross_margin is None

    def test_model_tolerates_epsilon_cushion(self):
        # The relaxed le=1.02 backstop keeps a residual-rounding value from any future
        # un-sanitized constructor from hard-crashing the schema.
        stmt = IncomeStatement(revenue=1.0e11, gross_margin=1.01)
        assert stmt.gross_margin == 1.01

    def test_model_still_rejects_gross_mixup(self):
        # A gross percent/decimal mixup (>102%) still fails the schema assertion — the
        # cushion is small, not a blanket removal of the ceiling.
        with pytest.raises(ValidationError):
            IncomeStatement(revenue=1.0e11, gross_margin=1.5)
