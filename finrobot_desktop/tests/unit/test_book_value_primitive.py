"""Tests for the book-value-per-share per-ADR reconciliation primitive.

Expected values are anchored to EXTERNAL live-pulled figures (stockanalysis.com,
Yahoo), never re-derived with the primitive's own formula:

  - BP (2026-07-06 live): FMP /shares-float outstandingShares = 437,084,167 vs the
    market_cap/price-implied ADR count 2,622.5M (a 6:1 ADR ratio); FMP raw bvps
    ≈ $128.03/share (per the off-basis count). External per-ADR book value:
    stockanalysis.com balance sheet Book Value Per Share = $21.43, external P/B ≈
    price $37.40 / $21.43 ≈ 1.745. The reconciled per-ADR figure must land on that
    external $21 basis, NOT the $128 per-count figure.
  - SHEL / HSBC / AAPL: /shares-float == market_cap/price (no ADR-ratio mismatch),
    so reconciliation is a byte-identical no-op — external per-ADR BVPS already
    equals the stored figure (SHEL $59.31, HSBC $56.48 external).
"""

import math

from finrobot.engine.primitives.book_value import (
    SHARES_PRICE_CONSISTENCY_TOL,
    reconcile_book_value_to_price_basis,
)

# External live anchors (stockanalysis.com / FMP profile, 2026-07-06).
_BP_PROVIDER_BVPS = 128.03  # FMP raw bvps on the off-basis /shares-float count
_BP_REPORTED_SHARES = 437_084_167.0  # FMP /shares-float outstandingShares
_BP_MARKET_CAP = 98_081_500_000.0  # FMP profile marketCap (≈ price × ADR count)
_BP_PRICE = 37.40  # FMP profile price (per ADR)
_BP_EXTERNAL_PER_ADR_BVPS = 21.43  # stockanalysis.com balance-sheet Book Value/Share


class TestPerOrdinaryToPerAdrRescale:
    def test_bp_rescaled_to_external_per_adr_basis(self):
        bvps, note = reconcile_book_value_to_price_basis(
            _BP_PROVIDER_BVPS, _BP_REPORTED_SHARES, _BP_MARKET_CAP, _BP_PRICE
        )
        # Lands on the EXTERNAL per-ADR basis (~$21.43), not the $128 per-count figure.
        assert bvps is not None
        assert abs(bvps - _BP_EXTERNAL_PER_ADR_BVPS) / _BP_EXTERNAL_PER_ADR_BVPS < 0.03
        # Decisively away from the mis-scaled provider value.
        assert bvps < _BP_PROVIDER_BVPS / 5
        assert note is not None and "per-ADR" in note

    def test_book_equity_is_conserved(self):
        # 勾稽: reconciled × implied_shares == raw × reported_shares (book equity),
        # so pb_ratio = market_cap / (bvps × shares) is invariant to the rescale.
        bvps, _ = reconcile_book_value_to_price_basis(
            _BP_PROVIDER_BVPS, _BP_REPORTED_SHARES, _BP_MARKET_CAP, _BP_PRICE
        )
        implied_shares = _BP_MARKET_CAP / _BP_PRICE
        assert math.isclose(
            bvps * implied_shares,
            _BP_PROVIDER_BVPS * _BP_REPORTED_SHARES,
            rel_tol=1e-9,
        )

    def test_implied_pb_matches_external(self):
        # price / reconciled_bvps recovers the external P/B (~1.745).
        bvps, _ = reconcile_book_value_to_price_basis(
            _BP_PROVIDER_BVPS, _BP_REPORTED_SHARES, _BP_MARKET_CAP, _BP_PRICE
        )
        implied_pb = _BP_PRICE / bvps
        assert abs(implied_pb - 1.745) < 0.05


class TestNoOpPassThrough:
    def test_us_reported_equals_implied_is_byte_identical(self):
        # AAPL-like: /shares-float == market_cap/price → unchanged, note None.
        shares = 14_687_356_000.0
        price = 308.63
        market_cap = shares * price
        bvps_in = 7.25
        bvps, note = reconcile_book_value_to_price_basis(bvps_in, shares, market_cap, price)
        assert bvps == bvps_in
        assert note is None

    def test_already_per_adr_foreign_issuer_no_op(self):
        # SHEL-like ADR: reported == implied → external $59.31 already stored, no-op.
        shares = 2_788_095_000.0
        price = 78.02
        market_cap = shares * price
        bvps_in = 59.31
        bvps, note = reconcile_book_value_to_price_basis(bvps_in, shares, market_cap, price)
        assert bvps == bvps_in
        assert note is None

    def test_within_tolerance_multiclass_is_no_op(self):
        # GOOG-like: reported 12,094M vs implied 12,221M ≈ 1.0% < 10% tol → no-op,
        # keeping the multi-class name byte-identical (the tol boundary that protects
        # US byte-identity while still catching the 6× BP ADR ratio).
        reported = 12_094_870_293.0
        implied = 12_221_530_594.0
        price = 200.0
        market_cap = implied * price
        divergence = abs(reported - implied) / implied
        assert divergence < SHARES_PRICE_CONSISTENCY_TOL
        bvps, note = reconcile_book_value_to_price_basis(9.09, reported, market_cap, price)
        assert bvps == 9.09
        assert note is None


class TestDegenerateInputs:
    def test_none_bvps_returns_none(self):
        assert reconcile_book_value_to_price_basis(None, 1e9, 1e11, 100.0) == (None, None)

    def test_non_positive_bvps_unchanged(self):
        # Negative book equity (a distressed issuer) is never rescaled.
        assert reconcile_book_value_to_price_basis(-5.0, 1e9, 1e11, 100.0) == (-5.0, None)

    def test_missing_reported_shares_no_op(self):
        # When the provider had no share count it already divided book equity by
        # market_cap/price — bvps is already on the price basis, so no-op.
        assert reconcile_book_value_to_price_basis(50.0, None, 1e11, 100.0) == (50.0, None)
        assert reconcile_book_value_to_price_basis(50.0, 0.0, 1e11, 100.0) == (50.0, None)

    def test_missing_market_or_price_no_op(self):
        assert reconcile_book_value_to_price_basis(50.0, 1e9, None, 100.0) == (50.0, None)
        assert reconcile_book_value_to_price_basis(50.0, 1e9, 1e11, None) == (50.0, None)
        assert reconcile_book_value_to_price_basis(50.0, 1e9, 1e11, 0.0) == (50.0, None)
